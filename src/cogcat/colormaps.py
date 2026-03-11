"""Built-in colormaps and optional matplotlib bridge."""

from __future__ import annotations

import numpy as np
from PIL import Image


# 256-entry LUTs as (R, G, B) tuples
def _lerp_lut(stops: list[tuple[float, int, int, int]]) -> np.ndarray:
    """Interpolate a 256-entry RGB LUT from color stops.

    Each stop is (position_0_to_1, R, G, B).
    """
    lut = np.zeros((256, 3), dtype=np.uint8)
    for i in range(256):
        t = i / 255.0
        # Find bounding stops
        for j in range(len(stops) - 1):
            if stops[j][0] <= t <= stops[j + 1][0]:
                span = stops[j + 1][0] - stops[j][0]
                frac = (t - stops[j][0]) / span if span > 0 else 0.0
                for c in range(3):
                    lut[i, c] = int(stops[j][1 + c] + frac * (stops[j + 1][1 + c] - stops[j][1 + c]))
                break
    return lut


_BUILTIN_LUTS: dict[str, np.ndarray] = {}


def _get_builtin_luts() -> dict[str, np.ndarray]:
    if not _BUILTIN_LUTS:
        _BUILTIN_LUTS["grayscale"] = _lerp_lut([(0.0, 0, 0, 0), (1.0, 255, 255, 255)])
        _BUILTIN_LUTS["terrain"] = _lerp_lut([
            (0.0, 0, 100, 0),
            (0.3, 34, 139, 34),
            (0.5, 210, 180, 140),
            (0.7, 139, 90, 43),
            (0.85, 200, 200, 200),
            (1.0, 255, 255, 255),
        ])
        _BUILTIN_LUTS["viridis"] = _lerp_lut([
            (0.0, 68, 1, 84),
            (0.13, 72, 36, 117),
            (0.25, 56, 88, 140),
            (0.38, 39, 126, 142),
            (0.5, 31, 161, 135),
            (0.63, 74, 194, 109),
            (0.75, 159, 218, 58),
            (0.88, 223, 227, 24),
            (1.0, 253, 231, 37),
        ])
    return _BUILTIN_LUTS


def list_colormaps() -> list[str]:
    """Return available colormap names."""
    names = list(_get_builtin_luts().keys())
    try:
        import matplotlib.cm as cm
        names.extend(sorted(cm._cmap_registry.keys()))
    except Exception:
        pass
    return names


def apply_colormap(
    array: np.ndarray,
    name: str = "viridis",
    vmin: float | None = None,
    vmax: float | None = None,
    nodata: float | None = None,
) -> Image.Image:
    """Apply a colormap to a 2D array, returning an RGBA PIL Image."""
    arr = array.astype(np.float64)

    # Build nodata mask
    if nodata is not None:
        mask = arr == nodata
    else:
        mask = np.isnan(arr)

    valid = arr[~mask] if mask.any() else arr.ravel()
    if vmin is None:
        vmin = float(np.min(valid)) if valid.size > 0 else 0.0
    if vmax is None:
        vmax = float(np.max(valid)) if valid.size > 0 else 1.0

    # Normalize to 0-255
    span = vmax - vmin if vmax != vmin else 1.0
    normalized = np.clip((arr - vmin) / span * 255, 0, 255).astype(np.uint8)

    builtins = _get_builtin_luts()
    if name in builtins:
        lut = builtins[name]
        rgb = lut[normalized]
    else:
        # Try matplotlib
        try:
            import matplotlib.cm as cm
            import matplotlib.colors as mcolors

            cmap = cm.get_cmap(name)
            rgba = cmap(normalized / 255.0)
            rgb = (rgba[:, :, :3] * 255).astype(np.uint8)
        except Exception:
            # Fallback to viridis
            lut = builtins["viridis"]
            rgb = lut[normalized]

    # Build RGBA
    alpha = np.full(arr.shape, 255, dtype=np.uint8)
    if mask.any():
        alpha[mask] = 0

    rgba = np.dstack([rgb, alpha])
    return Image.fromarray(rgba, mode="RGBA")
