"""slidesmd CLI — index and search your PowerPoint presentations."""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from slidesmd.extractor import extract
from slidesmd.indexer import build_index
from slidesmd.watcher import watch as _watch

app = typer.Typer(help="Auto-index PowerPoint presentations into agents.md for Copilot.")
console = Console()


@app.command()
def index(
    folder: Path = typer.Argument(..., help="Path to your presentations folder"),
) -> None:
    """Scan a folder and generate/refresh agents.md."""
    if not folder.exists():
        console.print(f"[red]Folder not found: {folder}[/red]")
        raise typer.Exit(1)

    pptx_files = list(folder.rglob("*.pptx"))
    if not pptx_files:
        console.print("[yellow]No .pptx files found.[/yellow]")
        raise typer.Exit(0)

    presentations = []
    with console.status("Extracting presentation metadata..."):
        for f in pptx_files:
            try:
                presentations.append(extract(f))
            except Exception as e:
                console.print(f"[yellow]Skipped {f.name}: {e}[/yellow]")

    index_path = build_index(presentations, folder)
    console.print(f"[green]✓ Index written to {index_path}[/green]")
    console.print(f"  {len(presentations)} presentations indexed.")


@app.command()
def watch(
    folder: Path = typer.Argument(..., help="Path to your presentations folder"),
) -> None:
    """Watch a folder and auto-update agents.md when files change."""
    if not folder.exists():
        console.print(f"[red]Folder not found: {folder}[/red]")
        raise typer.Exit(1)

    _watch(folder)


@app.command()
def search(
    folder: Path = typer.Argument(..., help="Path to your presentations folder"),
    query: str = typer.Argument(..., help="Search term to look for"),
) -> None:
    """Search presentations by keyword across titles, topics, and to-dos."""
    pptx_files = list(folder.rglob("*.pptx"))
    if not pptx_files:
        console.print("[yellow]No .pptx files found.[/yellow]")
        raise typer.Exit(0)

    results = []
    q = query.lower()

    for f in pptx_files:
        try:
            meta = extract(f)
            searchable = " ".join([
                meta.title,
                *meta.topics,
                *meta.todos,
            ]).lower()
            if q in searchable:
                results.append(meta)
        except Exception:
            pass

    if not results:
        console.print(f"[yellow]No presentations found matching '{query}'.[/yellow]")
        return

    table = Table(title=f"Search results for '{query}'")
    table.add_column("Title", style="cyan")
    table.add_column("Slides", justify="right")
    table.add_column("File", style="dim")

    for meta in results:
        table.add_row(meta.title, str(meta.slide_count), str(meta.file_path))

    console.print(table)
