"""Smart raster reading with overview selection and windowed reads."""

from __future__ import annotations

import os
from typing import Any

import numpy as np
import rasterio
from rasterio.windows import Window
from rich.console import Console


def _terminal_pixel_size(margin_rows: int = 2) -> tuple[int, int]:
    """Return (width, height) in pixels based on terminal size.

    Half-block characters encode 2 vertical pixels per character row.
    Reserves 2 columns and 2 rows for the image border.
    """
    console = Console(force_terminal=True)
    cols = console.size.width - 2   # border left + right
    rows = console.size.height - margin_rows - 2  # border top + bottom
    return max(cols, 1), max(rows * 2, 2)


def _fit_dimensions(src_w: int, src_h: int, max_w: int, max_h: int) -> tuple[int, int]:
    """Compute output dimensions that fit within max bounds preserving aspect ratio."""
    if src_w <= 0 or src_h <= 0:
        return max_w, max_h
    scale = min(max_w / src_w, max_h / src_h)
    return max(1, round(src_w * scale)), max(1, round(src_h * scale))


def read_raster(
    source: str,
    bands: list[int] | None = None,
    window: Window | None = None,
    full: bool = False,
    timeout: int = 10,
    margin_rows: int = 2,
    overview_level: int | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Read a raster file, returning pixel data sized to the terminal.

    Returns:
        (array of shape (bands, h, w), metadata dict)
    """
    is_url = source.startswith("http://") or source.startswith("https://")

    env_opts: dict[str, str] = {}
    if is_url:
        env_opts["GDAL_HTTP_TIMEOUT"] = str(timeout)
        env_opts["CPL_VSIL_CURL_ALLOWED_EXTENSIONS"] = ".tif,.tiff"

    with rasterio.Env(**env_opts):
        with rasterio.open(source) as ds:
            meta = _build_metadata(ds, source, is_url)
            target_w, target_h = _terminal_pixel_size(margin_rows)

            # Resolve negative band indexes (Python-style: -1 = last band)
            if bands:
                resolved = []
                for b in bands:
                    if b < 0:
                        resolved.append(ds.count + 1 + b)  # -1 → ds.count, -2 → ds.count-1
                    else:
                        resolved.append(b)
                bands = resolved

            # Resolve auto-sized window (width/height == 0 means fit to terminal)
            if window is not None and int(window.width) == 0 and int(window.height) == 0:
                col_off = int(window.col_off)
                row_off = int(window.row_off)
                # Resolve negative offsets first
                if col_off < 0:
                    col_off = ds.width + col_off
                if row_off < 0:
                    row_off = ds.height + row_off
                # Compute width/height from terminal pixel budget and remaining raster extent
                auto_w = min(target_w, ds.width - col_off)
                auto_h = min(target_h, ds.height - row_off)
                window = Window(col_off, row_off, max(1, auto_w), max(1, auto_h))

            # Resolve negative window offsets (count from right/bottom edge)
            if window is not None:
                col_off = int(window.col_off)
                row_off = int(window.row_off)
                if col_off < 0:
                    col_off = ds.width + col_off
                if row_off < 0:
                    row_off = ds.height + row_off
                if col_off != int(window.col_off) or row_off != int(window.row_off):
                    window = Window(col_off, row_off, int(window.width), int(window.height))

            # Determine which bands to read
            if bands:
                read_bands = bands
            elif ds.count >= 3:
                read_bands = [1, 2, 3]
            else:
                read_bands = [1]

            cropped = False
            crop_info = {"left": 0, "right": 0, "top": 0, "bottom": 0}

            if window is not None:
                # Explicit window — clamp to actual raster bounds for correct aspect ratio
                x_off = int(window.col_off)
                y_off = int(window.row_off)
                w_w = min(int(window.width), ds.width - x_off) if int(window.width) > 0 else ds.width - x_off
                w_h = min(int(window.height), ds.height - y_off) if int(window.height) > 0 else ds.height - y_off
                clamped_window = Window(x_off, y_off, w_w, w_h)
                fit_w, fit_h = _fit_dimensions(w_w, w_h, target_w, target_h)
                data = ds.read(
                    read_bands, window=clamped_window, out_shape=(len(read_bands), fit_h, fit_w)
                )
                # Mark as cropped if the window doesn't cover the full raster from origin
                if x_off > 0 or y_off > 0 or x_off + w_w < ds.width or y_off + w_h < ds.height:
                    cropped = True
                    crop_info = {
                        "left": x_off,
                        "right": max(0, ds.width - x_off - w_w),
                        "top": y_off,
                        "bottom": max(0, ds.height - y_off - w_h),
                    }
                    meta["crop_type"] = "window"
            elif full or (ds.width <= target_w and ds.height <= target_h):
                # Read everything, downsample to terminal
                fit_w, fit_h = _fit_dimensions(ds.width, ds.height, target_w, target_h)
                data = ds.read(read_bands, out_shape=(len(read_bands), fit_h, fit_w))
            else:
                # Smart read: use overviews or center window
                overviews = ds.overviews(read_bands[0])
                if overviews and not full:
                    meta["overviews"] = overviews
                    if overview_level is not None:
                        # User requested a specific overview level
                        if overview_level not in overviews:
                            raise ValueError(
                                f"Overview level {overview_level} not available. "
                                f"Choose from: {overviews}"
                            )
                        factor = overview_level
                        ovr_h = max(1, ds.height // factor)
                        ovr_w = max(1, ds.width // factor)
                        fit_w, fit_h = _fit_dimensions(ovr_w, ovr_h, target_w, target_h)
                        data = ds.read(
                            read_bands, out_shape=(len(read_bands), fit_h, fit_w)
                        )
                        meta["overview_level"] = overview_level
                    else:
                        # rasterio picks the right overview when out_shape is set
                        fit_w, fit_h = _fit_dimensions(ds.width, ds.height, target_w, target_h)
                        data = ds.read(
                            read_bands, out_shape=(len(read_bands), fit_h, fit_w)
                        )
                        # Determine which overview was actually used
                        best = min(overviews, key=lambda o: abs(ds.height // o - target_h))
                        meta["overview_level"] = best
                    meta["overview_used"] = True
                else:
                    # Center window crop
                    cx, cy = ds.width // 2, ds.height // 2
                    # Read a region that will downsample nicely
                    read_w = min(ds.width, target_w * 4)
                    read_h = min(ds.height, target_h * 4)
                    x_off = max(0, cx - read_w // 2)
                    y_off = max(0, cy - read_h // 2)
                    # Clamp
                    read_w = min(read_w, ds.width - x_off)
                    read_h = min(read_h, ds.height - y_off)

                    win = Window(x_off, y_off, read_w, read_h)
                    fit_w, fit_h = _fit_dimensions(read_w, read_h, target_w, target_h)
                    data = ds.read(
                        read_bands, window=win, out_shape=(len(read_bands), fit_h, fit_w)
                    )
                    cropped = True
                    crop_info = {
                        "left": x_off,
                        "right": max(0, ds.width - x_off - read_w),
                        "top": y_off,
                        "bottom": max(0, ds.height - y_off - read_h),
                    }
                    meta["crop_type"] = "center"

            meta["cropped"] = cropped
            meta["crop_info"] = crop_info
            meta["bands_read"] = read_bands
            meta["nodata"] = ds.nodata

            # Source vs rendered pixel dimensions for downscale info
            src_h, src_w = data.shape[1], data.shape[2]
            if window is not None:
                meta["source_pixels"] = (w_w, w_h)
            elif cropped:
                ci_w = ds.width - crop_info["left"] - crop_info["right"]
                ci_h = ds.height - crop_info["top"] - crop_info["bottom"]
                meta["source_pixels"] = (ci_w, ci_h)
            else:
                meta["source_pixels"] = (ds.width, ds.height)
            meta["render_pixels"] = (src_w, src_h)

            return data, meta


def _build_metadata(ds: rasterio.DatasetReader, source: str, is_url: bool) -> dict[str, Any]:
    """Extract metadata from an open dataset."""
    bounds = ds.bounds
    res = ds.res
    return {
        "filename": os.path.basename(source) if not is_url else source,
        "source": source,
        "is_url": is_url,
        "crs": str(ds.crs) if ds.crs else "None",
        "bounds": f"({bounds.left:.6f}, {bounds.bottom:.6f}, {bounds.right:.6f}, {bounds.top:.6f})",
        "pixel_size": f"{res[0]:.6f} x {res[1]:.6f}",
        "shape": f"{ds.height} x {ds.width}",
        "height": ds.height,
        "width": ds.width,
        "dtype": str(ds.dtypes[0]),
        "band_count": ds.count,
        "nodata": ds.nodata,
        "overview_used": False,
    }
