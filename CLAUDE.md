# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is cogcat

`cat` for GeoTIFFs. A CLI tool that renders raster files (GeoTIFF, COG, JPEG2000, NetCDF, etc.) directly in the terminal using half-block ANSI characters via rich-pixels. Works over SSH and headless environments.

## Commands

```bash
# Install dependencies
uv sync

# Install with optional matplotlib colormaps
uv sync --extra colormaps

# Run the CLI
uv run cogcat <source> [OPTIONS]

# Run directly during development
uv run python -m cogcat.cli <source>
```

No tests or linter are configured yet.

## Architecture

Single-pass pipeline: **CLI → Reader → Render → Display**

- `src/cogcat/cli.py` — Typer CLI entry point (`cogcat.cli:app`). Parses args, orchestrates the pipeline.
- `src/cogcat/reader.py` — Opens rasters via rasterio, selects overview level or center-crops, downsamples to terminal size. Returns `(numpy array [bands, h, w], metadata dict)`.
- `src/cogcat/render.py` — Converts numpy array to PIL Image. Single-band: applies colormap. Multi-band (≥3): applies 2–98% percentile stretch per band for RGB composite.
- `src/cogcat/colormaps.py` — Built-in LUTs (viridis, terrain, grayscale) via linear interpolation. Falls back to matplotlib colormaps if `[colormaps]` extra installed.
- `src/cogcat/display.py` — Rich console output: metadata panel with optional box-drawing crop inset, ASCII histogram, image rendering via `rich-pixels`.

## Key Design Details

- Terminal pixel budget: `cols × (rows - margin) × 2` (half-block chars encode 2 vertical pixels per row).
- Smart reading strategy: uses COG overviews when available, otherwise center-crops large rasters. `--full` disables this.
- Negative band indexes supported (Python-style: `-1` = last band).
- Nodata pixels rendered as transparent (alpha=0).
- Build system: hatchling with `src/cogcat` layout.
