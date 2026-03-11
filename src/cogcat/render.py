"""Image construction from raster arrays."""

from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image

from .colormaps import apply_colormap


def _percentile_stretch(band: np.ndarray, nodata: float | None, lo: float = 2.0, hi: float = 98.0) -> np.ndarray:
    """Stretch band values to 0-255 using percentile clipping."""
    arr = band.astype(np.float64)
    if nodata is not None:
        valid = arr[arr != nodata]
    else:
        valid = arr[~np.isnan(arr)]

    if valid.size == 0:
        return np.zeros_like(band, dtype=np.uint8)

    vmin = np.percentile(valid, lo)
    vmax = np.percentile(valid, hi)
    span = vmax - vmin if vmax != vmin else 1.0
    stretched = np.clip((arr - vmin) / span * 255, 0, 255).astype(np.uint8)
    return stretched


def render_image(
    array: np.ndarray,
    metadata: dict[str, Any],
    colormap: str = "viridis",
) -> Image.Image:
    """Convert raster array to a PIL Image for terminal display.

    Args:
        array: Shape (bands, h, w) from reader
        metadata: Metadata dict from reader
        colormap: Colormap name for single-band display
    """
    nodata = metadata.get("nodata")
    num_bands = array.shape[0]

    if num_bands == 1:
        return apply_colormap(array[0], name=colormap, nodata=nodata)

    # RGB composite (3 bands)
    r = _percentile_stretch(array[0], nodata)
    g = _percentile_stretch(array[1], nodata)
    b = _percentile_stretch(array[2], nodata)

    # Alpha from nodata
    if nodata is not None:
        alpha = np.where(array[0] == nodata, 0, 255).astype(np.uint8)
    else:
        alpha = np.full(array[0].shape, 255, dtype=np.uint8)

    rgba = np.dstack([r, g, b, alpha])
    return Image.fromarray(rgba, mode="RGBA")
