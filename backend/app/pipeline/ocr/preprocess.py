"""Render a PDF page to an image that OCR engines read well.

Scanned books are usually grey or sepia with uneven lighting. Rendering at
300 dpi in greyscale, stretching the contrast and (optionally) binarising
with an Otsu threshold is the cheap, model-free preparation that moves
Tesseract accuracy the most. Everything here is Pillow + NumPy; no OpenCV.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image, ImageOps


@dataclass
class RenderedPage:
    image: Image.Image
    dpi: int
    page_width_pt: float
    page_height_pt: float

    @property
    def scale(self) -> float:
        """Pixels per PDF point."""
        return self.dpi / 72.0

    def to_points(
        self, x0: float, y0: float, x1: float, y1: float
    ) -> tuple[float, float, float, float]:
        s = self.scale
        return (x0 / s, y0 / s, x1 / s, y1 / s)


def render_page(page: Any, dpi: int = 300) -> RenderedPage:
    """Rasterise a PyMuPDF page to a greyscale PIL image."""
    import fitz

    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY, alpha=False)
    image = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    return RenderedPage(
        image=image,
        dpi=dpi,
        page_width_pt=float(page.rect.width),
        page_height_pt=float(page.rect.height),
    )


def otsu_threshold(gray: np.ndarray) -> int:
    """Classic Otsu: the threshold that minimises intra-class variance."""
    hist = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    if total == 0:
        return 128
    weight_bg = np.cumsum(hist)
    weight_fg = total - weight_bg
    cum_sum = np.cumsum(hist * np.arange(256))
    mean_bg = np.divide(cum_sum, weight_bg, out=np.zeros(256), where=weight_bg > 0)
    mean_fg = np.divide(cum_sum[-1] - cum_sum, weight_fg, out=np.zeros(256), where=weight_fg > 0)
    between = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
    return int(np.argmax(between))


def enhance(image: Image.Image, *, binarize: bool = False) -> Image.Image:
    """Auto-contrast; optionally binarise. Returns a new image."""
    out = image if image.mode == "L" else image.convert("L")
    out = ImageOps.autocontrast(out, cutoff=1)
    if binarize:
        arr = np.asarray(out)
        threshold = otsu_threshold(arr)
        out = Image.fromarray(np.where(arr > threshold, 255, 0).astype(np.uint8), mode="L")
    return out


def ink_ratio(image: Image.Image) -> float:
    """Share of dark pixels: ~0 for a blank page, ~0.05-0.15 for a text page,
    high for photographs. Used to skip empty pages without an OCR call."""
    arr = np.asarray(image if image.mode == "L" else image.convert("L"))
    if arr.size == 0:
        return 0.0
    return float((arr < 128).mean())
