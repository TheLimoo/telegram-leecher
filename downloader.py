"""Download engine — detects source type and downloads files."""
import asyncio
import json
import os
import re
import shutil
import logging
from pathlib import Path
from typing import Callable, Optional

from config import DOWNLOAD_DIR, DOWNLOAD_TIMEOUT, MAX_FILE_SIZE

logger = logging.getLogger(__name__)

# URL patterns
MAGNET_RE = re.compile(r"^magnet:\?xt=urn:", re.IGNORECASE)
TORRENT_FILE_RE = re.compile(r"^https?://.*\.torrent(\?.*)?$", re.IGNORECASE)
YOUTUBE_RE = re.compile(
    r"(?:youtube\.com|youtu\.be|youtube-nocookie\.com)",
    re.IGNORECASE
)
APARAT_RE = re.compile(r"aparat\.com", re.IGNORECASE)
GDRIVE_RE = re.compile(
    r"(drive\.google\.com/(file/d|drive|folders)|docs\.google\.com/(document|spreadsheets))",
    re.IGNORECASE,
)


def detect_source(url: str) -> str:
    """Detect what kind of download source a URL is."""
    url = url.strip()
    if MAGNET_RE.match(url):
        return "magnet"
    if TORRENT_FILE_RE.match(url):
        return "torrent"
    if GDRIVE_RE.search(url):
        return "gdrive"
    if YOUTUBE_RE.search(url) or APARAT_RE.search(url):
        return "youtube"
    return "direct"


async def _run_process(cmd: list[str], timeout: int = DOWNLOAD_TIMEOUT) -> tuple[str, str]:
    """Run an async subprocess and return (stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return stdout.decode(errors="replace"), stderr.decode(errors="replace")
    except asyncio.TimeoutError:
        proc.kill()
        raise TimeoutError(f"Download timed out after {timeout}s")


def _format_size(size_bytes: int) -> str:
    """Format bytes to human-readable size."""
    if size_bytes is None:
        return "Unknown"
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


async def get_youtube_formats(url: str) -> list[dict]:
    """Get available formats for a YouTube/Aparat video with estimated sizes."""
    cmd = [
        "yt-dlp",
        "-J",  # JSON output
        "--no-playlist",
        "--no-warnings",
        url,
    ]
    
    try:
        stdout, stderr = await _run_process(cmd, timeout=30)
        
        # Try to parse JSON
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse yt-dlp JSON: {stdout[:200]}")
            return []
        
        if not data:
            return []
        
        formats = []
        seen_resolutions = set()
        
        for fmt in data.get("formats", []):
            height = fmt.get("height")
            ext = fmt.get("ext", "mp4")
            filesize = fmt.get("filesize") or fmt.get("filesize_approx")
            format_id = fmt.get("format_id", "")
            vcodec = fmt.get("vcodec", "none")
            acodec = fmt.get("acodec", "none")
            
            # Skip audio-only or unknown formats
            if not height or vcodec == "none":
                continue
            
            # Group by resolution, prefer mp4
            if height in seen_resolutions:
                continue
            
            # Estimate size if not available (approx based on bitrate)
            if not filesize:
                tbr = fmt.get("tbr")  # Total bitrate in kbps
                duration = data.get("duration", 0)
                if tbr and duration:
                    filesize = int((tbr * 1024 / 8) * duration)  # kbps to bytes
            
            formats.append({
                "format_id": format_id,
                "height": height,
                "ext": ext,
                "filesize": filesize,
                "filesize_str": _format_size(filesize),
                "vcodec": vcodec,
                "acodec": acodec,
            })
            seen_resolutions.add(height)
        
        # Sort by resolution (highest first)
        formats.sort(key=lambda x: x["height"], reverse=True)
        
        # Keep only best 5 formats to avoid overwhelming the user
        return formats[:5]
    
    except Exception as e:
        logger.error(f"Failed to get formats: {e}")
        return []


async def _download_direct(url: str, dest: str, progress_cb: Optional[Callable] = None) -> str:
    """Download via aria2c (direct link)."""
    cmd = [
        "aria2c",
        "--dir=" + dest,
        "--summary-interval=0",
        "--follow-torrent=false",
        "--max-connection-per-server=16",
        "--split=16",
        "--continue=true",
        "--max-file-not-found=5",
        "--retry-wait=3",
        "--timeout=30",
        "--allow-overwrite=true",
        "--console-log-level=warn",
        url,
    ]
    stdout, stderr = await _run_process(cmd)
    
    # Find downloaded file
    files = list(Path(dest).iterdir())
    if not files:
        raise FileNotFoundError(f"No file downloaded from {url}")
    
    # Return the largest file (likely the actual download)
    return str(max(files, key=lambda f: f.stat().st_size if f.is_file() else 0))


async def _download_magnet(url: str, dest: str, progress_cb: Optional[Callable] = None) -> str:
    """Download via aria2c (magnet link)."""
    cmd = [
        "aria2c",
        "--dir=" + dest,
        "--summary-interval=0",
        "--follow-torrent=false",
        "--max-connection-per-server=16",
        "--split=16",
        "--bt-stop-timeout=300",
        "--seed-time=0",
        "--bt-enable-lpd=false",
        "--enable-dht=true",
        "--dht-listen-port=6881",
        "--listen-port=6881",
        "--console-log-level=warn",
        url,
    ]
    stdout, stderr = await _run_process(cmd, timeout=DOWNLOAD_TIMEOUT + 300)
    
    files = list(Path(dest).iterdir())
    if not files:
        raise FileNotFoundError(f"No file downloaded from magnet link")
    
    # For torrents, might have multiple files — pick the largest
    if len(files) == 1 and files[0].is_dir():
        return str(files[0])
    
    return str(max(files, key=lambda f: f.stat().st_size if f.is_file() else 0))


async def _download_torrent_file(url: str, dest: str, progress_cb: Optional[Callable] = None) -> str:
    """Download a .torrent file first, then download its contents."""
    # Download the .torrent file
    torrent_path = os.path.join(dest, "temp.torrent")
    cmd = ["aria2c", "--dir=" + dest, "-o=temp.torrent", "--console-log-level=warn", url]
    await _run_process(cmd, timeout=30)
    
    # Download the torrent contents
    cmd = [
        "aria2c",
        "--dir=" + dest,
        "--summary-interval=0",
        "--follow-torrent=true",
        "--bt-stop-timeout=300",
        "--seed-time=0",
        "--console-log-level=warn",
        torrent_path,
    ]
    stdout, stderr = await _run_process(cmd, timeout=DOWNLOAD_TIMEOUT + 300)
    
    # Clean up .torrent file
    if os.path.exists(torrent_path):
        os.remove(torrent_path)
    
    files = list(Path(dest).iterdir())
    if not files:
        raise FileNotFoundError(f"No file downloaded from torrent")
    
    if len(files) == 1 and files[0].is_dir():
        return str(files[0])
    
    return str(max(files, key=lambda f: f.stat().st_size if f.is_file() else 0))


async def _download_youtube(url: str, dest: str, quality: str = "best", progress_cb: Optional[Callable] = None) -> str:
    """Download via yt-dlp (YouTube/Aparat) with quality selection."""
    output_template = os.path.join(dest, "%(title)s.%(ext)s")
    
    # Format selection based on quality - use bestvideo+bestaudio strategy
    if quality == "best":
        fmt = "bestvideo+bestaudio/best"
    elif quality == "720p":
        fmt = "bestvideo[height<=720]+bestaudio[ext=m4a]/best[height<=720]"
    elif quality == "480p":
        fmt = "bestvideo[height<=480]+bestaudio[ext=m4a]/best[height<=480]"
    elif quality == "360p":
        fmt = "bestvideo[height<=360]+bestaudio[ext=m4a]/best[height<=360]"
    elif quality == "worst":
        fmt = "worstvideo+worstaudio/worst"
    else:
        # Assume it's a format_id from quality selection
        fmt = f"{quality}+bestaudio/{quality}/best"
    
    cmd = [
        "yt-dlp",
        "-f", fmt,
        "-o", output_template,
        "--no-playlist",
        "--merge-output-format", "mp4",
        "--no-overwrites",
        "--restrict-filenames",
        "--postprocessor-args", "ffmpeg:-crf 23",  # Balance quality/size
        "--print-to-file", "after_move:filepath", "/dev/stdout",
        "--ignore-errors",
        "--no-warnings",
        url,
    ]
    
    try:
        stdout, stderr = await _run_process(cmd, timeout=300)
        
        # Try to get filename from stdout
        for line in stdout.strip().splitlines():
            if line.strip() and os.path.exists(line.strip()):
                return line.strip()
        
        # Fallback: find the file
        files = list(Path(dest).iterdir())
        if files:
            return str(max(files, key=lambda f: f.stat().st_size if f.is_file() else 0))
    except TimeoutError:
        # Try simpler format on timeout
        cmd = ["yt-dlp", "-f", "best", "-o", output_template, "--no-playlist", url]
        stdout, stderr = await _run_process(cmd, timeout=180)
        files = list(Path(dest).iterdir())
        if files:
            return str(max(files, key=lambda f: f.stat().st_size if f.is_file() else 0))
    
    raise FileNotFoundError(f"No file downloaded from {url}")


async def _download_gdrive(url: str, dest: str, progress_cb: Optional[Callable] = None) -> str:
    """Download via gdown (Google Drive)."""
    cmd = [
        "gdown",
        url,
        "-O", dest + "/",
        "--fuzzy",
        "--remaining-ok",
    ]
    stdout, stderr = await _run_process(cmd)
    
    files = list(Path(dest).iterdir())
    if not files:
        raise FileNotFoundError(f"No file downloaded from Google Drive")
    
    return str(max(files, key=lambda f: f.stat().st_size if f.is_file() else 0))


DOWNLOADERS = {
    "direct": _download_direct,
    "magnet": _download_magnet,
    "torrent": _download_torrent_file,
    "youtube": _download_youtube,
    "gdrive": _download_gdrive,
}


async def download(
    url: str,
    quality: str = "best",
    progress_cb: Optional[Callable] = None,
) -> tuple[str, str, str]:
    """
    Download a file from any supported source.
    
    Returns: (file_path, filename, source_type)
    """
    source_type = detect_source(url)
    downloader = DOWNLOADERS.get(source_type)
    if not downloader:
        raise ValueError(f"Unsupported source: {source_type}")
    
    # Create unique temp dir for this download
    import uuid
    dest = os.path.join(DOWNLOAD_DIR, str(uuid.uuid4())[:8])
    os.makedirs(dest, exist_ok=True)
    
    try:
        # Pass quality for YouTube downloads
        if source_type == "youtube":
            file_path = await downloader(url, dest, quality, progress_cb)
        else:
            file_path = await downloader(url, dest, progress_cb)
        
        if os.path.isdir(file_path):
            # For directories (torrents with multiple files), zip them
            zip_path = file_path + ".zip"
            shutil.make_archive(file_path, "zip", file_path)
            shutil.rmtree(file_path)
            file_path = zip_path
        
        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        
        if file_size > MAX_FILE_SIZE:
            os.remove(file_path)
            raise ValueError(
                f"File too large: {file_size / 1024 / 1024:.1f}MB "
                f"(max: {MAX_FILE_SIZE / 1024 / 1024 / 1024:.0f}GB)"
            )
        
        return file_path, filename, source_type
    
    except Exception:
        # Cleanup on failure
        if os.path.exists(dest):
            shutil.rmtree(dest, ignore_errors=True)
        raise


def cleanup(file_path: str) -> None:
    """Remove downloaded file and its parent temp dir."""
    if not file_path:
        return
    try:
        parent = os.path.dirname(file_path)
        if parent and parent.startswith(DOWNLOAD_DIR):
            shutil.rmtree(parent, ignore_errors=True)
        elif os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        logger.warning(f"Cleanup failed: {e}")


def get_file_info(path: str) -> dict:
    """Get file metadata."""
    if os.path.isdir(path):
        total_size = sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file())
        return {"name": os.path.basename(path), "size": total_size, "is_dir": True}
    
    return {
        "name": os.path.basename(path),
        "size": os.path.getsize(path),
        "is_dir": False,
    }
