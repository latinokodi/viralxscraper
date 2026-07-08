#!/usr/bin/env python3
"""
ViralXXXPorn Media Scraper — Album Downloader
Enter a model URL, scrape all videos, download in parallel (3 at a time).
"""

import sys
import os
import re
import logging
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

if os.name == "nt":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

console = Console()
logging.basicConfig(level=logging.ERROR)

sys.path.insert(0, str(Path(__file__).parent))
from viralxscraper import scrape_model, scrape_video, BASE_URL, download_video
from viralxscraper.utils import get_download_folder, set_download_folder

# ══════════════════════════════════════════════════════════════════════
# Theme
# ══════════════════════════════════════════════════════════════════════

ACCENT  = "#ffc107"
DIM     = "dim"
SUCCESS = "green"
ERROR   = "red"

# ══════════════════════════════════════════════════════════════════════
# Input
# ══════════════════════════════════════════════════════════════════════

def prompt(text: str, default: str = "") -> str:
    label = f"[{ACCENT}]{text}[/{ACCENT}]: " if not default else \
            f"[{ACCENT}]{text}[/{ACCENT}] [{DIM}]({default})[/{DIM}]: "
    r = console.input(label)
    return r.strip() or default


# ══════════════════════════════════════════════════════════════════════
# Header
# ══════════════════════════════════════════════════════════════════════

def header():
    console.print(f"[bold {ACCENT}]ViralXXXPorn Album Downloader[/bold {ACCENT}]  [{DIM}]viralxxxporn.com[/{DIM}]")
    console.print()


# ══════════════════════════════════════════════════════════════════════
# Progress helpers
# ══════════════════════════════════════════════════════════════════════

def with_spinner(desc: str, fn, *args, **kwargs):
    with Progress(SpinnerColumn(style=ACCENT),
                  TextColumn("[progress.description]{task.description}"),
                  console=console, transient=True) as prog:
        t = prog.add_task(desc, total=None)
        result = fn(*args, **kwargs)
        prog.remove_task(t)
    return result


def with_progress_bar(desc: str, items: list, fn):
    results = []
    with Progress(SpinnerColumn(style=ACCENT),
                  TextColumn("[progress.description]{task.description}"),
                  BarColumn(), TaskProgressColumn(),
                  console=console) as prog:
        t = prog.add_task(desc, total=len(items))
        for item in items:
            prog.update(t, description=f"{desc} ({len(results)}/{len(items)})")
            r = fn(item)
            if r: results.append(r)
            prog.advance(t)
    return results


# ══════════════════════════════════════════════════════════════════════
# Parallel download (3 threads)
# ══════════════════════════════════════════════════════════════════════

_print_lock = threading.Lock()
_done_count = 0
_active_count = 0


def _download_one(detail, folder, idx, total):
    """Download a single video in a thread. Returns (idx, path, size_mb, error)."""
    global _done_count, _active_count
    try:
        path = download_video(detail, folder)
        size_mb = os.path.getsize(path) / 1024 / 1024 if path else 0
        with _print_lock:
            _done_count += 1
            if path:
                console.print(f"  [green]✓[/green] [{idx}/{total}] {detail.title[:60]}  [dim]{size_mb:.1f} MB[/dim]")
            sys.stdout.write(f"\r  [{_done_count}/{total}] done, [{_active_count}] active    ")
            sys.stdout.flush()
        return (idx, path, size_mb, None if path else "no URL")
    except Exception as e:
        with _print_lock:
            _done_count += 1
            console.print(f"  [red]✗[/red] [{idx}/{total}] {detail.title[:60]}  {str(e)[:40]}")
            sys.stdout.write(f"\r  [{_done_count}/{total}] done, [{_active_count}] active    ")
            sys.stdout.flush()
        return (idx, None, 0, str(e))


def download_parallel(details, folder):
    """Download videos using 3 parallel threads."""
    global _done_count, _active_count
    _done_count = 0
    total = len(details)
    downloaded = []
    total_mb = 0

    console.print(f"[bold]Downloading {total} videos[/bold] → [{DIM}]{folder}[/{DIM}]\n")
    _active_count = min(3, total)
    sys.stdout.write(f"  [0/{total}] done, [{_active_count}] active    ")
    sys.stdout.flush()

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_download_one, d, folder, i, total): i
            for i, d in enumerate(details, 1)
        }
        for future in as_completed(futures):
            idx, path, size_mb, err = future.result()
            _active_count = max(0, _active_count - 1)
            with _print_lock:
                sys.stdout.write(f"\r  [{_done_count}/{total}] done, [{_active_count}] active    ")
                sys.stdout.flush()
            if path:
                downloaded.append(path)
                total_mb += size_mb

    sys.stdout.write("\r" + " " * 60 + "\r")
    sys.stdout.flush()
    console.print()
    if downloaded:
        console.print(f"[{SUCCESS}]Downloaded {len(downloaded)}/{total} videos, {total_mb:.1f} MB[/{SUCCESS}]")
    else:
        console.print(f"[{ERROR}]No videos downloaded[/{ERROR}]")

    return downloaded


# ══════════════════════════════════════════════════════════════════════
# Main flow
# ══════════════════════════════════════════════════════════════════════

def run():
    """Single session: URL → scrape → parallel download → loop."""
    console.clear(); header()

    # ── URL ──────────────────────────────────────────────────────────
    url = prompt("Album or model URL (empty to quit)")
    if not url:
        return False
    url = url.strip()
    if not url.startswith("http"):
        url = BASE_URL + url

    # ── Destination folder ──────────────────────────────────────────
    saved = get_download_folder()
    folder = prompt("Destination folder", saved)
    if not folder:
        return True
    folder = os.path.abspath(folder)
    if folder != saved:
        set_download_folder(folder)
    os.makedirs(folder, exist_ok=True)

    # ── Slug ────────────────────────────────────────────────────────
    slug = ""
    if "/models/" in url:
        m = re.search(r'/models/([^/?#]+)', url)
        slug = m.group(1) if m else ""

    # ── Scrape ──────────────────────────────────────────────────────
    console.clear(); header()
    console.print(f"Destination: [{DIM}]{folder}[/{DIM}]")

    is_video = "/video/" in url
    details = []

    if is_video:
        console.print("Loading video...\n")
        d = with_spinner("Loading...", scrape_video, url)
        if d and d.direct_url:
            details = [d]
        else:
            console.print(f"[{ERROR}]Could not load video[/{ERROR}]\n")
            return True
    else:
        console.print("Scanning model...\n")
        videos = with_spinner("Scanning...", scrape_model, slug, 0)
        if not videos:
            console.print(f"[{ERROR}]No videos found[/{ERROR}]\n")
            return True
        details = with_progress_bar("Extracting video URLs", videos,
                                    lambda v: scrape_video(v.url))

    if not details:
        console.print(f"[{ERROR}]Nothing to download[/{ERROR}]\n")
        return True

    details = [d for d in details if d.direct_url]
    if not details:
        console.print(f"[{ERROR}]No download URLs found[/{ERROR}]\n")
        return True

    # ── Download (3 parallel) ────────────────────────────────────────
    console.clear(); header()
    download_parallel(details, folder)
    console.print()

    return True  # loop for next URL


def main():
    try:
        while run():
            pass
    except KeyboardInterrupt:
        console.clear()
        console.print(f"\n[{ACCENT}]Interrupted. Goodbye![/{ACCENT}]\n")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[{ERROR}]Error: {e}[/{ERROR}]")
        import traceback; traceback.print_exc()
        console.input("\nPress Enter to exit...")
        sys.exit(1)


if __name__ == "__main__":
    main()
