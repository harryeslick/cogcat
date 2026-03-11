"""Rich output: metadata panel, histogram, image display."""

from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich_pixels import Pixels


def _build_inset(metadata: dict[str, Any], max_width: int = 24, max_height: int = 10) -> Text:
    """Build a box-drawing inset showing crop extent within the full raster.

    Outer box = full raster extent (proportional), inner box = rendered crop area.
    Returns a Rich Text renderable.
    """
    crop_info = metadata.get("crop_info", {})
    full_w = metadata["width"]
    full_h = metadata["height"]

    left = crop_info.get("left", 0)
    right = crop_info.get("right", 0)
    top = crop_info.get("top", 0)
    bottom = crop_info.get("bottom", 0)

    crop_w = full_w - left - right
    crop_h = full_h - top - bottom

    # Compute outer box dimensions proportional to raster aspect ratio.
    # Terminal chars are ~2x taller than wide, so scale height by 0.5.
    aspect = full_w / full_h if full_h > 0 else 1.0
    char_aspect = aspect * 2.0  # correct for character cell proportions (chars ~2x taller than wide)

    if char_aspect >= 1.0:
        # Wider than tall
        width = max_width
        height = max(5, int(round((max_width - 2) / char_aspect)) + 2)
        height = min(height, max_height)
    else:
        # Taller than wide
        height = max_height
        width = max(7, int(round((max_height - 2) * char_aspect)) + 2)
        width = min(width, max_width)

    # Inner box position in character coordinates (inside the outer box)
    iw = width - 2
    ih = height - 2

    ix0 = int(left / full_w * iw)
    iy0 = int(top / full_h * ih)
    ix1 = int((left + crop_w) / full_w * iw)
    iy1 = int((top + crop_h) / full_h * ih)
    ix1 = max(ix1, ix0 + 2)
    iy1 = max(iy1, iy0 + 2)
    ix1 = min(ix1, iw)
    iy1 = min(iy1, ih)

    result = Text()
    for row in range(height):
        for col in range(width):
            # Outer box border
            if row == 0 and col == 0:
                ch = "╭"
            elif row == 0 and col == width - 1:
                ch = "╮"
            elif row == height - 1 and col == 0:
                ch = "╰"
            elif row == height - 1 and col == width - 1:
                ch = "╯"
            elif row == 0 or row == height - 1:
                ch = "─"
            elif col == 0 or col == width - 1:
                ch = "│"
            else:
                r = row - 1
                c = col - 1
                on_inner_top = r == iy0 and ix0 <= c <= ix1
                on_inner_bottom = r == iy1 and ix0 <= c <= ix1
                on_inner_left = c == ix0 and iy0 <= r <= iy1
                on_inner_right = c == ix1 and iy0 <= r <= iy1

                if r == iy0 and c == ix0:
                    ch = "┌"
                elif r == iy0 and c == ix1:
                    ch = "┐"
                elif r == iy1 and c == ix0:
                    ch = "└"
                elif r == iy1 and c == ix1:
                    ch = "┘"
                elif on_inner_top or on_inner_bottom:
                    ch = "─"
                elif on_inner_left or on_inner_right:
                    ch = "│"
                else:
                    ch = " "

            # Style: inner box in yellow, outer in dim
            r_inner = row - 1
            c_inner = col - 1
            is_inner = (
                0 <= r_inner
                and 0 <= c_inner
                and (
                    (r_inner == iy0 and ix0 <= c_inner <= ix1)
                    or (r_inner == iy1 and ix0 <= c_inner <= ix1)
                    or (c_inner == ix0 and iy0 <= r_inner <= iy1)
                    or (c_inner == ix1 and iy0 <= r_inner <= iy1)
                )
            )
            result.append(ch, style="bold yellow" if is_inner else "dim white")

        if row < height - 1:
            result.append("\n")

    return result


def show_metadata(
    console: Console, metadata: dict[str, Any], inset: bool = True
) -> None:
    """Print a metadata panel, with optional crop inset on the right."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="bold cyan", no_wrap=True)
    table.add_column("Value")

    table.add_row("File", metadata["filename"])
    table.add_row("CRS", metadata["crs"])
    table.add_row("Bounds", metadata["bounds"])
    table.add_row("Resolution", metadata["pixel_size"])
    table.add_row("Size", metadata["shape"])
    table.add_row("Bands", str(metadata["band_count"]))
    table.add_row("Dtype", metadata["dtype"])
    table.add_row("Nodata", str(metadata["nodata"]) if metadata["nodata"] is not None else "—")

    if metadata.get("overview_used"):
        overviews = metadata.get("overviews", [])
        active = metadata.get("overview_level")
        if overviews:
            parts = []
            for o in overviews:
                if o == active:
                    parts.append(f"[bold green]{o}[/bold green]")
                else:
                    parts.append(f"[dim]{o}[/dim]")
            table.add_row("Overviews", " ".join(parts))
        else:
            table.add_row("Overview", "Yes (used for fast preview)")

    cropped = metadata.get("cropped", False)

    if cropped and inset:
        inset_text = _build_inset(metadata)
        inset_panel = Panel(
            inset_text, title="[bold]Extent[/bold]", border_style="dim", expand=False,
        )
        # Use a layout table to place metadata and inset side by side
        layout = Table(show_header=False, box=None, padding=0, expand=True)
        layout.add_column(ratio=1)
        layout.add_column(width=30)
        layout.add_row(table, inset_panel)
        panel = Panel(layout, title="[bold]Raster Metadata[/bold]", border_style="dim")
    else:
        panel = Panel(table, title="[bold]Raster Metadata[/bold]", border_style="dim")

    console.print(panel)


def show_histogram(
    console: Console,
    array: np.ndarray,
    nodata: float | None = None,
    bins: int = 20,
    width: int = 40,
) -> None:
    """Print a small ASCII histogram of pixel values."""
    flat = array.ravel().astype(np.float64)
    if nodata is not None:
        flat = flat[flat != nodata]
    flat = flat[~np.isnan(flat)]

    if flat.size == 0:
        console.print("[dim]No valid data for histogram[/dim]")
        return

    counts, edges = np.histogram(flat, bins=bins)
    max_count = counts.max() if counts.max() > 0 else 1

    console.print()
    console.print("[bold]Histogram[/bold]")
    for i, count in enumerate(counts):
        bar_len = int(count / max_count * width)
        label = f"{edges[i]:>10.1f}"
        bar = "█" * bar_len
        console.print(Text(f"  {label} │{bar}", style="green"))


def show_crop_warning(console: Console, metadata: dict[str, Any]) -> None:
    """Print a warning line about the crop."""
    ci = metadata["crop_info"]
    crop_type = metadata.get("crop_type", "center")
    if crop_type == "window":
        label = "Window crop"
        suffix = ""
    else:
        label = "Center crop"
        suffix = " — use --full to load all"
    console.print(
        f"  [yellow]⚠ {label} (skipped L:{ci['left']} R:{ci['right']} "
        f"T:{ci['top']} B:{ci['bottom']}px{suffix})[/yellow]"
    )


def show_image(console: Console, image: Image.Image) -> None:
    """Render a PIL Image in the terminal using rich-pixels."""
    pixels = Pixels.from_image(image)
    console.print(pixels)
