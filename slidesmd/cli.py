"""slidesmd CLI — index and search your PowerPoint presentations."""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from slidesmd.extractor import extract
from slidesmd.indexer import build_index
from slidesmd.watcher import watch as _watch
from slidesmd import embedder, querier

app = typer.Typer(help="Auto-index PowerPoint presentations into agents.md for Copilot.")


@app.command()
def mcp() -> None:
    """Start the SlidesMD MCP server (stdio transport)."""
    from slidesmd.mcp_server import main
    main()


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


@app.command("embed")
def embed_cmd(
    folder: Path = typer.Argument(..., help="Path to your presentations folder"),
) -> None:
    """Build or update the semantic embedding index for a folder."""
    if not folder.exists():
        console.print(f"[red]Folder not found: {folder}[/red]")
        raise typer.Exit(1)

    if not embedder.is_available():
        console.print(
            "[red]Semantic search dependencies not installed.[/red]\n"
            "Run: pip install slidesmd[semantic]"
        )
        raise typer.Exit(1)

    with console.status("Building embedding index..."):
        indexed, skipped = embedder.index_folder(folder)

    console.print(f"[green]{indexed} file(s) indexed, {skipped} skipped (unchanged or failed).[/green]")


@app.command("semantic-search")
def semantic_search_cmd(
    folder: Path = typer.Argument(..., help="Path to your presentations folder"),
    query: str = typer.Argument(..., help="Natural language query"),
    top_k: int = typer.Option(5, "--top-k", "-k", help="Number of results"),
) -> None:
    """Search slides by meaning using vector similarity."""
    if not folder.exists():
        console.print(f"[red]Folder not found: {folder}[/red]")
        raise typer.Exit(1)

    if not embedder.is_available():
        console.print(
            "[red]Semantic search dependencies not installed.[/red]\n"
            "Run: pip install slidesmd[semantic]"
        )
        raise typer.Exit(1)

    results = embedder.search(folder, query, top_k=top_k)

    if not results:
        console.print(f"[yellow]No results for '{query}'. Have you run `slidesmd embed` first?[/yellow]")
        return

    table = Table(title=f"Semantic search: '{query}'")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Score", justify="right")
    table.add_column("File", style="cyan")
    table.add_column("Slide", justify="right")
    table.add_column("Preview")

    for i, r in enumerate(results, 1):
        score = max(0.0, 1.0 - r.distance)
        preview = r.chunk.chunk_text[:100] + ("..." if len(r.chunk.chunk_text) > 100 else "")
        table.add_row(
            str(i),
            f"{score:.2f}",
            Path(r.chunk.file_path).name,
            str(r.chunk.slide_index + 1),
            preview,
        )

    console.print(table)


@app.command()
def query(
    folder: Path = typer.Argument(..., help="Path to your presentations folder"),
    question: str = typer.Argument(..., help="Question to ask about the slides"),
    model: str = typer.Option(querier.DEFAULT_MODEL, "--model", "-m", help="Ollama model to use"),
) -> None:
    """Ask a question about your presentations using a local Ollama model."""
    if not folder.exists():
        console.print(f"[red]Folder not found: {folder}[/red]")
        raise typer.Exit(1)

    if not querier.is_available():
        console.print("[red]ollama package not found. Run: pip install ollama[/red]")
        raise typer.Exit(1)

    pptx_files = list(folder.rglob("*.pptx"))

    if not pptx_files:
        console.print("[yellow]No .pptx files found.[/yellow]")
        raise typer.Exit(0)

    presentations = []
    with console.status("Extracting slide content..."):
        for f in pptx_files:
            try:
                presentations.append(extract(f))
            except Exception as e:
                console.print(f"[yellow]Skipped {f.name}: {e}[/yellow]")

    if not presentations:
        console.print("[red]No presentations could be extracted.[/red]")
        raise typer.Exit(1)

    console.print(f"[dim]Querying {len(presentations)} presentation(s) with {model}...[/dim]\n")

    try:
        for token in querier.query(presentations, question, model=model):
            console.print(token, end="", markup=False, highlight=False)
        console.print()
    except RuntimeError as e:
        console.print(f"\n[red]{e}[/red]")
        raise typer.Exit(1)
