"""Download engine — detects source type and downloads files."""
import asyncio
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
    r"(?:youtube\.com|youtu\.be|youtube-nocookie\.com)", re.IGNORECASE
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


def _get_aria2_filename(url: str) -> Optional[str]:
    """Try to get filename from aria2c header check."""
    try:
        import subprocess

        result = subprocess.run(
            ["aria2c", "--dry-run", "--follow-torrent=false", url],
            capture_output=True,
            text=True,
            timeout=15,
        )
        for line in result.stderr.splitlines():
            if "Files:" in line or "fname=" in line:
                match = re.search(r"fname=([^\s]+)", line)
                if match:
                    return match.group(1)
    except Exception:
        pass
    return None


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
    stdout, stderr = await _run_process(cmd, timeout=DOWNLOAD_TIMEOUT + 300)  # extra time for torrents
    
    files = list(Path(dest).iterdir())
    if not files:
        raise FileNotFoundError(f"No file downloaded from magnet link")
    
    # For torrents, might have multiple files — pick the largest
    if len(files) == 1 and files[0].is_dir():
        # Single directory — return path to it
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


async def _download_youtube(url: str, dest: str, progress_cb: Optional[Callable] = None) -> str:
    """Download via yt-dlp (YouTube/Aparat)."""
    output_template = os.path.join(dest, "%(title)s.%(ext)s")
    
    # Try multiple format strategies
    formats = [
        "best[filesize<50M]/best[height<=720]/best",
        "best[height<=720]/best",
        "best/worst",
    ]
    
    for fmt in formats:
        cmd = [
            "yt-dlp",
            "-f", fmt,
            "-o", output_template,
            "--no-playlist",
            "--merge-output-format", "mp4",
            "--no-overwrites",
            "--restrict-filenames",
            "--print-to-file", "after_move:filepath", "/dev/stdout",
            "--ignore-errors",
            "--no-warnings",
            url,
        ]
        try:
            stdout, stderr = await _run_process(cmd, timeout=180)
            
            # Try to get filename from stdout
            for line in stdout.strip().splitlines():
                if line.strip() and os.path.exists(line.strip()):
                    return line.strip()
            
            # Fallback: find the file
            files = list(Path(dest).iterdir())
            if files:
                return str(max(files, key=lambda f: f.stat().st_size if f.is_file() else 0))
        except TimeoutError:
            continue
        except Exception:
            continue
    
    raise FileNotFoundError(f"No file downloaded from {url} (tried multiple formats)")


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
