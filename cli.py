#!/usr/bin/env python3
"""
ViralXXXPorn Media Scraper CLI
==============================
Usage:
  viralxscraper model <slug>           Scrape a model's videos
  viralxscraper video <url-or-id>      Scrape a single video
  viralxscraper search <query>         Search videos
  viralxscraper latest                 Latest videos
  viralxscraper top                    Top rated videos
  viralxscraper popular                Most viewed videos
  viralxscraper info <slug>            Get model info

Options:
  -p, --pages N         Max pages to scrape (default: 1, 0=all)
  -d, --details         Get full details for each video
  -o, --output FILE     Output file (json, csv, or txt)
  -f, --format FORMAT   Output format: json, csv, table, text (default: table)
  -q, --quiet           Suppress progress output
  -v, --verbose         Show debug info
"""

import sys
import json
import csv
import logging
from pathlib import Path
from typing import Optional, List, Any

import typer
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from rich.text import Text

# Ensure we can import from the project directory
sys.path.insert(0, str(Path(__file__).parent))

from viralxscraper import (
    scrape_model,
    scrape_video,
    scrape_search,
    scrape_latest,
    scrape_top_rated,
    scrape_most_viewed,
    scrape_model_info,
    BASE_URL,
)

app = typer.Typer(
    name="viralxscraper",
    help="Media scraper for viralxxxporn.com",
    add_completion=False,
)

console = Console()
logger = logging.getLogger("viralxscraper")


def setup_logging(quiet: bool, verbose: bool):
    if verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")
    elif quiet:
        logging.basicConfig(level=logging.ERROR)
    else:
        logging.basicConfig(level=logging.WARNING)


# ────────────────────────────────────────────────────────────────────
# Output formatters
# ────────────────────────────────────────────────────────────────────


def format_videos_table(videos: list) -> Table:
    """Format videos as a rich table."""
    table = Table(title=f"Videos ({len(videos)})", border_style="dim", header_style="bold magenta")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Title", style="white")
    table.add_column("Duration", style="green")
    table.add_column("Quality", style="yellow")
    table.add_column("Views", style="dim")

    for v in videos:
        table.add_row(
            str(v.video_id),
            v.title[:80] + ("..." if len(v.title) > 80 else ""),
            v.duration,
            v.quality,
            v.views,
        )

    return table


def format_video_detail(detail) -> str:
    """Format a single video's full details."""
    lines = [
        f"[cyan]ID:[/cyan]        {detail.video_id}",
        f"[cyan]Title:[/cyan]     [white]{detail.title}[/white]",
        f"[cyan]URL:[/cyan]       {detail.url}",
        f"[cyan]Duration:[/cyan]  {detail.duration}",
        f"[cyan]Views:[/cyan]     {detail.views}",
        f"[cyan]Rating:[/cyan]    {detail.rating}",
        f"[cyan]Embed:[/cyan]     {detail.embed_url}",
        f"[cyan]Categories:[/cyan] {', '.join(detail.categories) if detail.categories else 'N/A'}",
        f"[cyan]Models:[/cyan]    {', '.join(detail.models) if detail.models else 'N/A'}",
        f"[cyan]Tags:[/cyan]      {', '.join(detail.tags) if detail.tags else 'N/A'}",
        f"[cyan]Thumbnail:[/cyan] {detail.thumbnail}",
    ]

    if detail.description:
        desc = detail.description[:200]
        lines.append(f"[cyan]Desc:[/cyan]      {desc}{'...' if len(detail.description) > 200 else ''}")

    if detail.direct_url:
        lines.append(f"[cyan]Direct URL:[/cyan] {detail.direct_url}")

    if detail.files:
        lines.append("[cyan]Quality variants:[/cyan]")
        for q, url in sorted(detail.files.items()):
            lines.append(f"  [yellow]{q}[/yellow]: {url}")

    return "\n".join(lines)


def format_model_info(info) -> str:
    """Format model profile info."""
    lines = [
        f"[cyan]Name:[/cyan]      [white]{info.name}[/white]",
        f"[cyan]Rank:[/cyan]      #{info.rank}" if info.rank else "",
        f"[cyan]URL:[/cyan]       {info.url}",
        f"[cyan]Views:[/cyan]     {info.views}",
        f"[cyan]Followers:[/cyan] {info.followers}",
        f"[cyan]Country:[/cyan]   {info.country}",
        f"[cyan]Age:[/cyan]       {info.age}",
        f"[cyan]Height:[/cyan]    {info.height}",
        f"[cyan]Weight:[/cyan]    {info.weight}",
        f"[cyan]Videos:[/cyan]    {info.video_count}" if info.video_count else "",
    ]
    if info.thumbnail:
        lines.append(f"[cyan]Thumbnail:[/cyan] {info.thumbnail}")
    return "\n".join(line for line in lines if line)


def export_data(data: Any, output: str, format: str):
    """Export data to file in the specified format."""
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)

    if format == "json":
        if hasattr(data, "dict"):
            payload = data.dict()
        elif isinstance(data, list):
            payload = [v.dict() if hasattr(v, "dict") else v for v in data]
        else:
            payload = data

        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False, default=str)

    elif format == "csv":
        if not isinstance(data, list):
            data = [data]
        rows = [v.dict() if hasattr(v, "dict") else v for v in data]
        if not rows:
            return
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            for row in rows:
                clean = {}
                for k, v in row.items():
                    if isinstance(v, (list, dict)):
                        v = json.dumps(v)
                    clean[k] = str(v) if v else ""
                writer.writerow(clean)

    elif format == "text":
        with open(path, "w", encoding="utf-8") as f:
            if hasattr(data, "__iter__") and not isinstance(data, str):
                for item in data:
                    if hasattr(item, "title"):
                        f.write(f"[{item.video_id}] {item.title}\n")
                        f.write(f"  URL: {item.url}\n")
                        f.write(f"  Duration: {item.duration}, Quality: {item.quality}\n")
                        if hasattr(item, "direct_url") and item.direct_url:
                            f.write(f"  Direct: {item.direct_url}\n")
                        f.write("\n")
                    else:
                        f.write(str(item) + "\n")
            else:
                f.write(str(data))

    else:
        raise ValueError(f"Unknown format: {format}")


def fetch_details(videos: list) -> list:
    """Helper to fetch full details for a list of videos with a progress bar."""
    detail_list = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Getting video details...", total=len(videos))
        for v in videos:
            progress.update(task, description=f"Details: {v.video_id}")
            d = scrape_video(v.url)
            if d:
                detail_list.append(d)
            progress.advance(task)
    return detail_list


def handle_output(data: Any, output: Optional[str], format: str):
    """Helper to handle printing or exporting data cleanly."""
    if output:
        export_data(data, output, format)
        count = len(data) if isinstance(data, list) else 1
        console.print(f"[green]Saved {count} items to {output}[/green]")
    else:
        if format == "json":
            if isinstance(data, list):
                payload = [v.dict() if hasattr(v, "dict") else v for v in data]
            else:
                payload = data.dict() if hasattr(data, "dict") else data
            print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        elif format == "csv":
            if not isinstance(data, list):
                data = [data]
            rows = [v.dict() if hasattr(v, "dict") else v for v in data]
            if rows:
                writer = csv.DictWriter(sys.stdout, fieldnames=rows[0].keys())
                writer.writeheader()
                for row in rows:
                    clean = {}
                    for k, v in row.items():
                        if isinstance(v, (list, dict)):
                            v = json.dumps(v)
                        clean[k] = str(v) if v else ""
                    writer.writerow(clean)
        else:
            if isinstance(data, list):
                console.print(format_videos_table(data))
                console.print(f"\n[dim]Total: {len(data)} results[/dim]")
            else:
                console.print(Panel(format_video_detail(data), title="Video Details", border_style="cyan"))


# ────────────────────────────────────────────────────────────────────
# Commands
# ────────────────────────────────────────────────────────────────────


@app.command()
def model(
    slug: str = typer.Argument(..., help="Model slug (e.g., 'mandy-rose')"),
    pages: int = typer.Option(1, "--pages", "-p", help="Max pages (0=all)", min=0),
    details: bool = typer.Option(False, "--details", "-d", help="Get full video details"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file"),
    format: str = typer.Option("table", "--format", "-f", help="Output format"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Silent mode"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose mode"),
):
    """Scrape all videos from a model page."""
    setup_logging(quiet, verbose)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(f"Scraping model '{slug}'...", total=None)
        videos = scrape_model(slug, max_pages=pages if pages > 0 else 0)
        progress.stop()

    if details and videos:
        videos = fetch_details(videos)

    handle_output(videos, output, format)


@app.command()
def video(
    url: str = typer.Argument(..., help="Video URL or ID (e.g., /video/275314/...)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file"),
    format: str = typer.Option("text", "--format", "-f", help="Output format"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Get full details for a single video."""
    setup_logging(quiet, verbose)

    if url.isdigit():
        console.print("[red]Error: Must provide full video URL (slug required)[/red]")
        raise typer.Exit(1)

    if not url.startswith("http"):
        url = BASE_URL + url

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task(f"Scraping video...", total=None)
        detail = scrape_video(url)

    if not detail:
        console.print("[red]Failed to scrape video[/red]")
        raise typer.Exit(1)

    handle_output(detail, output, format)


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    pages: int = typer.Option(1, "--pages", "-p", help="Max pages", min=1, max=20),
    details: bool = typer.Option(False, "--details", "-d", help="Get full video details"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file"),
    format: str = typer.Option("table", "--format", "-f", help="Output format"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Search for videos."""
    setup_logging(quiet, verbose)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(f"Searching '{query}'...", total=None)
        videos = scrape_search(query, max_pages=pages)
        progress.stop()

    if details and videos:
        videos = fetch_details(videos)

    handle_output(videos, output, format)


@app.command()
def info(
    slug: str = typer.Argument(..., help="Model slug"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Get model profile information."""
    setup_logging(quiet, verbose)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task(f"Fetching info for '{slug}'...", total=None)
        model_info = scrape_model_info(slug)

    if not model_info:
        console.print(f"[red]Model '{slug}' not found[/red]")
        raise typer.Exit(1)

    console.print(Panel(format_model_info(model_info), title=f"Model: {model_info.name}", border_style="cyan"))


@app.command()
def latest(
    pages: int = typer.Option(1, "--pages", "-p", help="Max pages"),
    details: bool = typer.Option(False, "--details", "-d"),
    output: Optional[str] = typer.Option(None, "--output", "-o"),
    format: str = typer.Option("table", "--format", "-f"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Scrape latest videos."""
    setup_logging(quiet, verbose)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task(f"Fetching latest videos...", total=None)
        videos = scrape_latest(max_pages=pages)

    if details and videos:
        videos = fetch_details(videos)

    handle_output(videos, output, format)


@app.command()
def top(
    pages: int = typer.Option(1, "--pages", "-p", help="Max pages"),
    details: bool = typer.Option(False, "--details", "-d"),
    output: Optional[str] = typer.Option(None, "--output", "-o"),
    format: str = typer.Option("table", "--format", "-f"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Scrape top rated videos."""
    setup_logging(quiet, verbose)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task(f"Fetching top rated videos...", total=None)
        videos = scrape_top_rated(max_pages=pages)

    if details and videos:
        videos = fetch_details(videos)

    handle_output(videos, output, format)


@app.command()
def popular(
    pages: int = typer.Option(1, "--pages", "-p", help="Max pages"),
    details: bool = typer.Option(False, "--details", "-d"),
    output: Optional[str] = typer.Option(None, "--output", "-o"),
    format: str = typer.Option("table", "--format", "-f"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Scrape most viewed videos."""
    setup_logging(quiet, verbose)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task(f"Fetching most popular videos...", total=None)
        videos = scrape_most_viewed(max_pages=pages)

    if details and videos:
        videos = fetch_details(videos)

    handle_output(videos, output, format)


if __name__ == "__main__":
    app()
