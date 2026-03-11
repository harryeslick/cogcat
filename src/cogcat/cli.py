"""CLI entry point for cogcat."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rasterio.windows import Window

app = typer.Typer(
    name="cogcat",
    help="Terminal GeoTIFF previewer — render rasters directly in your terminal.",
    add_completion=False,
    no_args_is_help=True,
)

console = Console()


def _parse_bands(value: str | None) -> list[int] | None:
    if value is None:
        return None
    return [int(b.strip()) for b in value.split(",")]


def _parse_window(value: str | None) -> Window | None:
    if value is None:
        return None
    parts = [int(x.strip()) for x in value.split(",")]
    if len(parts) == 2:
        # xoff,yoff only — width,height will be determined by terminal size in reader
        return Window(parts[0], parts[1], 0, 0)
    if len(parts) != 4:
        raise typer.BadParameter("Window must be xoff,yoff or xoff,yoff,width,height")
    return Window(parts[0], parts[1], parts[2], parts[3])


@app.command()
def main(
    source: str = typer.Argument(help="Path or URL to raster file"),
    bands: Optional[str] = typer.Option(None, "--bands", "-b", help="Comma-separated band numbers (e.g. 4,3,2). Negative indexes count from last band (-1 = last)"),
    colormap: str = typer.Option("viridis", "--colormap", "-c", help="Colormap for single-band display"),
    histogram: bool = typer.Option(False, "--histogram", "-H", help="Show pixel value histogram"),
    full: bool = typer.Option(False, "--full", help="Load entire raster (may be slow for large files)"),
    window: Optional[str] = typer.Option(None, "--window", "-w", help="Custom window as xoff,yoff[,width,height]. Omit width,height to auto-size to terminal. Negative offsets count from right/bottom edge"),
    no_meta: bool = typer.Option(False, "--no-meta", help="Hide metadata panel"),
    no_inset: bool = typer.Option(False, "--no-inset", help="Hide crop extent inset overlay"),
    timeout: int = typer.Option(10, "--timeout", help="URL fetch timeout in seconds"),
    margin_rows: int = typer.Option(2, "--margin-rows", help="Reserve terminal rows for prompt"),
    overview: Optional[int] = typer.Option(None, "--overview", help="Render a specific overview level (e.g. 2, 4, 8, 16)"),
) -> None:
    """Render a GeoTIFF (or any rasterio-supported raster) in the terminal."""
    from .display import show_crop_warning, show_histogram, show_image, show_metadata
    from .reader import read_raster
    from .render import render_image

    parsed_bands = _parse_bands(bands)
    parsed_window = _parse_window(window)

    is_url = source.startswith("http://") or source.startswith("https://")

    try:
        array, metadata = read_raster(
            source,
            bands=parsed_bands,
            window=parsed_window,
            full=full,
            timeout=timeout,
            margin_rows=margin_rows,
            overview_level=overview,
        )
    except Exception as e:
        console.print(f"[red]Error reading raster:[/red] {e}")
        raise typer.Exit(1)

    # Large URL warning
    if is_url and full and metadata["height"] * metadata["width"] > 100_000_000:
        if not typer.confirm(f"Raster is {metadata['shape']} ({metadata['height'] * metadata['width'] / 1e6:.0f}MP). Load fully?"):
            raise typer.Exit(0)

    if not no_meta:
        show_metadata(console, metadata, inset=not no_inset)

    image = render_image(array, metadata, colormap=colormap)
    show_image(console, image, metadata)

    if metadata.get("cropped"):
        show_crop_warning(console, metadata)

    if histogram:
        show_histogram(console, array, nodata=metadata.get("nodata"))
