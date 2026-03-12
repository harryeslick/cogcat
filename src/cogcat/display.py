"""Rich output: metadata panel, histogram, image display."""

from __future__ import annotations

import io
from typing import Any

import numpy as np
from PIL import Image
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich_pixels import Pixels


def _fmt_px(n: int) -> str:
    """Format pixel count compactly."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n / 1_000:.0f}k"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _build_inset(metadata: dict[str, Any], max_width: int = 22, max_height: int = 8) -> Text:
    """Build a half-block pixel minimap showing crop extent within the full raster.

    Full raster = dim dots, crop region = bright yellow blocks.
    Works correctly even for tiny crops (1% of raster).
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

    # Pixel grid: half-block gives 2 vertical pixels per char row
    # Correct for character cell proportions (chars are ~2x taller than wide)
    aspect = full_w / full_h if full_h else 1.0
    char_aspect = aspect * 2.0  # chars are roughly 2:1 height:width

    if char_aspect >= 1.0:
        pw = max_width
        ph = max(2, int(round(max_width / char_aspect / 2)) * 2)
        ph = min(ph, max_height * 2)
    else:
        ph = max_height * 2
        pw = max(2, int(round(ph * char_aspect / 2)) * 2)
        pw = min(pw, max_width)

    # Crop region in pixel coordinates
    x0 = int(left / full_w * pw)
    y0 = int(top / full_h * ph)
    x1 = max(x0 + 1, int((left + crop_w) / full_w * pw))
    y1 = max(y0 + 1, int((top + crop_h) / full_h * ph))
    x1 = min(x1, pw)
    y1 = min(y1, ph)

    # Boolean pixel grid
    pixels = [[False] * pw for _ in range(ph)]
    for r in range(y0, y1):
        for c in range(x0, x1):
            pixels[r][c] = True

    # Render with half-block chars
    CROP = "bold yellow"
    BG = "dim white"
    result = Text()
    for row in range(0, ph, 2):
        for col in range(pw):
            t = pixels[row][col]
            b = pixels[row + 1][col] if row + 1 < ph else False
            if t and b:
                result.append("█", style=CROP)
            elif t:
                result.append("▀", style=CROP)
            elif b:
                result.append("▄", style=CROP)
            else:
                result.append("░", style=BG)
        if row + 2 < ph:
            result.append("\n")

    # Dimension label below minimap
    dim_label = f"{_fmt_px(crop_w)}×{_fmt_px(crop_h)}"
    result.append(f"\n{dim_label:^{pw}}", style="bold yellow")

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
        layout.add_column(width=32)
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
    """Print a compact crop/scale summary below the image."""
    crop_type = metadata.get("crop_type", "center")
    ci = metadata["crop_info"]

    # Build skip parts — only show edges with >0 skip
    parts = []
    arrows = {"left": "←", "right": "→", "top": "↑", "bottom": "↓"}
    for edge in ("left", "right", "top", "bottom"):
        if ci[edge] > 0:
            parts.append(f"{arrows[edge]}{_fmt_px(ci[edge])}")

    label = "window" if crop_type == "window" else "center crop"
    suffix = "" if crop_type == "window" else " — use --full to load all"
    skip_str = "  ".join(parts) if parts else ""

    line = Text()
    line.append(f"  ⚠ {label}", style="yellow")
    if skip_str:
        line.append(f"  skipped: {skip_str}", style="yellow")
    if suffix:
        line.append(suffix, style="dim yellow")
    console.print(line)


def show_image(console: Console, image: Image.Image, metadata: dict[str, Any] | None = None) -> None:
    """Render a PIL Image in the terminal with a box-drawing border.

    Crop skip amounts are overlaid on clipped edges. A downscale ratio is shown below.
    """
    pixels = Pixels.from_image(image)

    # Capture rendered pixels as ANSI text
    buf = io.StringIO()
    temp = Console(file=buf, width=image.width + 10, force_terminal=True)
    temp.print(pixels, end="")
    lines = buf.getvalue().rstrip("\n").split("\n")

    img_w = image.width
    img_h = len(lines)

    # Determine which edges are clipped
    meta = metadata or {}
    crop_info = meta.get("crop_info", {})
    cropped = meta.get("cropped", False)

    left_px = crop_info.get("left", 0) if cropped else 0
    right_px = crop_info.get("right", 0) if cropped else 0
    top_px = crop_info.get("top", 0) if cropped else 0
    bottom_px = crop_info.get("bottom", 0) if cropped else 0

    EDGE = "dim white"
    CLIP = "bold yellow"

    t_style = CLIP if top_px > 0 else EDGE
    b_style = CLIP if bottom_px > 0 else EDGE
    l_style = CLIP if left_px > 0 else EDGE
    r_style = CLIP if right_px > 0 else EDGE

    # Build top label (centered on top border)
    top_label = f" ↑{_fmt_px(top_px)}px " if top_px > 0 else ""
    # Build bottom label
    bot_label = f" ↓{_fmt_px(bottom_px)}px " if bottom_px > 0 else ""
    # Build side labels
    left_label = f"←{_fmt_px(left_px)}" if left_px > 0 else ""
    right_label = f"{_fmt_px(right_px)}→" if right_px > 0 else ""

    # --- Top border with optional label ---
    top_line = Text()
    top_line.append("╭", style=CLIP if (top_px > 0 or left_px > 0) else EDGE)
    if top_label and img_w > len(top_label) + 2:
        pad_total = img_w - len(top_label)
        pad_left = pad_total // 2
        pad_right = pad_total - pad_left
        top_line.append("─" * pad_left, style=t_style)
        top_line.append(top_label, style="bold yellow")
        top_line.append("─" * pad_right, style=t_style)
    else:
        top_line.append("─" * img_w, style=t_style)
    top_line.append("╮", style=CLIP if (top_px > 0 or right_px > 0) else EDGE)
    console.print(top_line)

    # --- Side labels: overlay on middle rows ---
    left_label_row = img_h // 2 if left_label else -1
    right_label_row = img_h // 2 if right_label else -1

    for i, line in enumerate(lines):
        row = Text()
        # Left border — possibly with label overlay
        if i == left_label_row:
            row.append("┤", style=l_style)
            row.append(Text.from_ansi(line))
            if i == right_label_row:
                row.append("├", style=r_style)
            else:
                row.append("│", style=r_style if right_px > 0 else EDGE)
        elif i == right_label_row:
            row.append("│", style=l_style if left_px > 0 else EDGE)
            row.append(Text.from_ansi(line))
            row.append("├", style=r_style)
        else:
            row.append("│", style=l_style if left_px > 0 else EDGE)
            row.append(Text.from_ansi(line))
            row.append("│", style=r_style if right_px > 0 else EDGE)
        console.print(row)

    # --- Print side labels on separate lines adjacent to the border ---
    # (Actually, let's put them inline with the border connector)

    # --- Bottom border with optional label ---
    bot_line = Text()
    bot_line.append("╰", style=CLIP if (bottom_px > 0 or left_px > 0) else EDGE)
    if bot_label and img_w > len(bot_label) + 2:
        pad_total = img_w - len(bot_label)
        pad_left = pad_total // 2
        pad_right = pad_total - pad_left
        bot_line.append("─" * pad_left, style=b_style)
        bot_line.append(bot_label, style="bold yellow")
        bot_line.append("─" * pad_right, style=b_style)
    else:
        bot_line.append("─" * img_w, style=b_style)
    bot_line.append("╯", style=CLIP if (bottom_px > 0 or right_px > 0) else EDGE)
    console.print(bot_line)

    # --- Side labels printed outside the border ---
    if left_label or right_label:
        side_line = Text()
        if left_label:
            side_line.append(f" {left_label}", style="bold yellow")
        if right_label:
            # Pad to right side
            pad = img_w + 2 - len(side_line.plain) - len(right_label) - 1
            side_line.append(" " * max(1, pad))
            side_line.append(f"{right_label} ", style="bold yellow")
        console.print(side_line)

    # --- Downscale info ---
    src = meta.get("source_pixels")
    rnd = meta.get("render_pixels")
    if src and rnd:
        src_w, src_h = src
        rnd_w, rnd_h = rnd
        ratio = max(src_w / max(rnd_w, 1), src_h / max(rnd_h, 1))
        scale_line = Text()
        scale_line.append(f"  {src_w}×{src_h}", style="dim cyan")
        scale_line.append(" → ", style="dim")
        scale_line.append(f"{rnd_w}×{rnd_h}", style="dim green")
        scale_line.append(f"  ({ratio:.0f}:1)", style="dim")
        console.print(scale_line)
