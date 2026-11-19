"""Portrait photo cut from an identity document.

A withdrawal document carries the holder's photo. The photo is cut from the
identity document the customer uploaded, or from another document image they
choose. The uploaded bytes are never rewritten: the crop is a new file.

The face is located with Pillow only. Skin-toned pixels are marked in YCbCr,
grouped on a coarse grid, and the most face-like group becomes the proposal.
When nothing face-like is found the proposal is the usual photo position on
an identity card. Either way the customer sees the box and can move it, and
the box they confirm is the one that is cut.
"""

from __future__ import annotations

import io
from typing import Any, Dict, List, Optional, Sequence, Tuple

PORTRAIT_SIZE = (360, 450)
PORTRAIT_ASPECT = PORTRAIT_SIZE[0] / PORTRAIT_SIZE[1]
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
IMAGE_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_GRID_LONG_SIDE = 64
_MIN_SIDE = 0.05


class PhotoCropError(ValueError):
    """The image cannot be read or the box cannot be cut."""

    def __init__(self, message: str, code: str = "photo_unreadable"):
        super().__init__(message)
        self.code = code


def _pil():
    try:
        from PIL import Image, ImageChops, ImageOps
    except Exception as exc:  # pragma: no cover - Pillow is a platform requirement
        raise PhotoCropError("Image processing is not available", "photo_engine_unavailable") from exc
    return Image, ImageChops, ImageOps


def _first_pdf_page(data: bytes):
    """First page of a PDF as an image, or None when no renderer is installed."""
    try:
        from pdf2image import convert_from_bytes

        pages = convert_from_bytes(data, dpi=110, first_page=1, last_page=1)
    except Exception:
        return None
    return pages[0] if pages else None


def can_render(mime_type: str, data: bytes = b"") -> bool:
    """True when a portrait can be cut from this file."""
    kind = str(mime_type or "").split(";")[0].strip().lower()
    if kind in IMAGE_MIME_TYPES:
        return True
    if kind == "application/pdf" or data[:5] == b"%PDF-":
        return _first_pdf_page(data) is not None if data else False
    return False


def load_image(data: bytes, mime_type: str = ""):
    """Decode an upload into an upright RGB image. The bytes are not changed."""
    Image, _chops, ImageOps = _pil()
    if not data:
        raise PhotoCropError("The file is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise PhotoCropError("The image is larger than 12 MB", "photo_too_large")
    kind = str(mime_type or "").split(";")[0].strip().lower()
    if kind == "application/pdf" or data[:5] == b"%PDF-":
        page = _first_pdf_page(data)
        if page is None:
            raise PhotoCropError(
                "A photo cannot be cut from this PDF. Upload a picture of the document instead.",
                "photo_source_not_image",
            )
        return page.convert("RGB")
    try:
        image = Image.open(io.BytesIO(data))
        if image.format not in ("JPEG", "PNG", "WEBP", "MPO"):
            raise PhotoCropError("Upload a JPEG, PNG, or WebP picture", "photo_source_not_image")
        width, height = image.size
        if width * height > MAX_IMAGE_PIXELS:
            raise PhotoCropError("The image has too many pixels", "photo_too_large")
        image.load()
        image = ImageOps.exif_transpose(image)
    except PhotoCropError:
        raise
    except Exception as exc:
        raise PhotoCropError("The picture could not be read") from exc
    if image.mode != "RGB":
        background = Image.new("RGB", image.size, (255, 255, 255))
        rgba = image.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        image = background
    if image.width < 80 or image.height < 80:
        raise PhotoCropError("The picture is too small to cut a photo from", "photo_too_small")
    return image


def _skin_grid(image) -> Tuple[List[List[float]], int, int]:
    """Share of skin-toned pixels in each cell of a coarse grid."""
    Image, ImageChops, _ops = _pil()
    scale = 256.0 / max(image.size)
    small = image.resize(
        (max(16, int(image.width * scale)), max(16, int(image.height * scale))),
        Image.BILINEAR,
    ) if scale < 1 else image
    luma, blue, red = small.convert("YCbCr").split()
    mask = ImageChops.multiply(
        luma.point(lambda v: 255 if v > 50 else 0),
        ImageChops.multiply(
            blue.point(lambda v: 255 if 77 <= v <= 127 else 0),
            red.point(lambda v: 255 if 135 <= v <= 175 else 0),
        ),
    )
    # Skin is redder than it is green by a clear margin; beige paper and
    # grey walls pass the chroma test above and fail this one.
    channel_r, channel_g, _channel_b = small.split()
    mask = ImageChops.multiply(
        mask, ImageChops.subtract(channel_r, channel_g).point(lambda v: 255 if v >= 12 else 0),
    )
    grid_scale = _GRID_LONG_SIDE / max(small.size)
    cols = max(8, int(round(small.width * grid_scale)))
    rows = max(8, int(round(small.height * grid_scale)))
    cells = mask.convert("L").resize((cols, rows), Image.BOX).tobytes()
    grid = [[cells[r * cols + c] / 255.0 for c in range(cols)] for r in range(rows)]
    return grid, cols, rows


def _components(grid: Sequence[Sequence[float]], cols: int, rows: int) -> List[Dict[str, float]]:
    seen = [[False] * cols for _ in range(rows)]
    found: List[Dict[str, float]] = []
    for r0 in range(rows):
        for c0 in range(cols):
            if seen[r0][c0] or grid[r0][c0] < 0.5:
                continue
            stack = [(r0, c0)]
            seen[r0][c0] = True
            cells = 0
            weight = 0.0
            members: List[Tuple[int, int]] = []
            left, right, top, bottom = c0, c0, r0, r0
            while stack:
                r, c = stack.pop()
                cells += 1
                weight += grid[r][c]
                members.append((r, c))
                left, right = min(left, c), max(right, c)
                top, bottom = min(top, r), max(bottom, r)
                for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < rows and 0 <= nc < cols and not seen[nr][nc] and grid[nr][nc] >= 0.5:
                        seen[nr][nc] = True
                        stack.append((nr, nc))
            found.append({
                "cells": cells, "weight": weight,
                "left": left, "right": right + 1, "top": top, "bottom": bottom + 1,
                "members": members,
            })
    return found


def _face_like(component: Dict[str, float], cols: int, rows: int) -> float:
    """Score for one skin group. Zero means it is not a face."""
    width = component["right"] - component["left"]
    height = component["bottom"] - component["top"]
    if width < 2 or height < 2:
        return 0.0
    share = (width * height) / float(cols * rows)
    if share < 0.004 or share > 0.45:
        return 0.0
    # A desk or a wall behind the document reaches the picture's edges.
    touching = sum((
        component["left"] <= 0, component["top"] <= 0,
        component["right"] >= cols, component["bottom"] >= rows,
    ))
    if touching >= 2:
        return 0.0
    aspect = width / float(height)
    if aspect < 0.45 or aspect > 1.5:
        return 0.0
    fill = component["cells"] / float(width * height)
    if fill < 0.5:
        return 0.0
    return component["weight"] * fill


def _head(component: Dict[str, Any], grid: Sequence[Sequence[float]]) -> Tuple[float, float, float]:
    """Centre and width of the head inside one skin group, in grid cells.

    The group usually runs on into the neck and chest. The head is the part
    from its top down to about one and a half face widths, and the face
    width is taken from the wider rows so that a stray cell does not set it.
    """
    by_row: Dict[int, List[int]] = {}
    for row, col in component["members"]:
        by_row.setdefault(row, []).append(col)
    widths = sorted(len(cols_in_row) for cols_in_row in by_row.values())
    face_w = float(widths[min(len(widths) - 1, int(len(widths) * 0.8))])
    top = int(component["top"])
    last = top + max(2, int(round(face_w * 1.45)))
    total = sum_x = sum_y = 0.0
    for row, cols_in_row in by_row.items():
        if row > last:
            continue
        for col in cols_in_row:
            weight = grid[row][col]
            total += weight
            sum_x += weight * (col + 0.5)
            sum_y += weight * (row + 0.5)
    if total <= 0:
        return (
            (component["left"] + component["right"]) / 2.0,
            (component["top"] + component["bottom"]) / 2.0,
            max(1.0, face_w),
        )
    return sum_x / total, sum_y / total, max(1.0, face_w)


def _fit_box(cx: float, cy: float, width: float, height: float, image_w: int, image_h: int) -> List[float]:
    """A 4:5 box of at most the given pixel size, kept inside the image."""
    width = min(width, float(image_w))
    height = min(height, float(image_h))
    if width / height > PORTRAIT_ASPECT:
        width = height * PORTRAIT_ASPECT
    else:
        height = width / PORTRAIT_ASPECT
    left = min(max(0.0, cx - width / 2.0), image_w - width)
    top = min(max(0.0, cy - height / 2.0), image_h - height)
    return [
        round(left / image_w, 4), round(top / image_h, 4),
        round(width / image_w, 4), round(height / image_h, 4),
    ]


def _frame_line(profile: bytes, start: int, stop: int, inward: int) -> Optional[int]:
    """Index just inside a straight line found in ``profile[start:stop]``."""
    band = profile[start:stop]
    if not band:
        return None
    ordered = sorted(profile)
    floor = max(16.0, 4.0 * ordered[len(ordered) // 2])
    peak = max(band)
    if peak < floor:
        return None
    hits = [start + index for index, value in enumerate(band) if value >= peak * 0.5]
    return (max(hits) + 2) if inward > 0 else (min(hits) - 2)


def _inside_frame(image, box: List[float]) -> List[float]:
    """Pull the box inside the printed photo's border when one crosses its margin.

    A photo on a card ends in a straight edge. A straight line shows as a
    peak in the mean gradient along its direction, which a face does not
    produce. Only the outer sixth of each side is searched, and the box only
    shrinks.
    """
    Image, ImageChops, _ops = _pil()
    image_w, image_h = image.size
    left, top, width, height = box
    pixels = (
        int(round(left * image_w)), int(round(top * image_h)),
        int(round((left + width) * image_w)), int(round((top + height) * image_h)),
    )
    if pixels[2] - pixels[0] < 40 or pixels[3] - pixels[1] < 50:
        return box
    cols, rows = 160, 200
    grey = image.crop(pixels).convert("L").resize((cols, rows), Image.BILINEAR)
    across = ImageChops.difference(grey, ImageChops.offset(grey, 1, 0)).resize((cols, 1), Image.BOX).tobytes()
    down = ImageChops.difference(grey, ImageChops.offset(grey, 0, 1)).resize((1, rows), Image.BOX).tobytes()
    margin_x, margin_y = cols // 6, rows // 6
    new_left = _frame_line(across, 2, margin_x, 1) or 0
    new_right = _frame_line(across, cols - margin_x, cols - 1, -1) or cols
    new_top = _frame_line(down, 2, margin_y, 1) or 0
    new_bottom = _frame_line(down, rows - margin_y, rows - 1, -1) or rows
    if (new_left, new_top, new_right, new_bottom) == (0, 0, cols, rows):
        return box
    inner_w = (new_right - new_left) / float(cols) * (pixels[2] - pixels[0])
    inner_h = (new_bottom - new_top) / float(rows) * (pixels[3] - pixels[1])
    if inner_w / inner_h > PORTRAIT_ASPECT:
        inner_w = inner_h * PORTRAIT_ASPECT
    else:
        inner_h = inner_w / PORTRAIT_ASPECT
    span_x = (new_right - new_left) / float(cols) * (pixels[2] - pixels[0])
    span_y = (new_bottom - new_top) / float(rows) * (pixels[3] - pixels[1])
    origin_x = pixels[0] + new_left / float(cols) * (pixels[2] - pixels[0]) + (span_x - inner_w) / 2.0
    # Keep the head: spare height comes off the bottom before the top.
    origin_y = pixels[1] + new_top / float(rows) * (pixels[3] - pixels[1]) + (span_y - inner_h) * 0.3
    return [
        round(origin_x / image_w, 4), round(origin_y / image_h, 4),
        round(inner_w / image_w, 4), round(inner_h / image_h, 4),
    ]


def _default_box(image_w: int, image_h: int) -> List[float]:
    if image_w >= image_h:
        # A landscape card carries its photo on one side, about a third wide.
        height = image_h * 0.62
        return _fit_box(image_w * 0.20, image_h * 0.52, height * PORTRAIT_ASPECT, height, image_w, image_h)
    width = image_w * 0.6
    return _fit_box(image_w * 0.5, image_h * 0.36, width, width / PORTRAIT_ASPECT, image_w, image_h)


def propose_portrait_box(image) -> Dict[str, Any]:
    """Where the holder's photo most likely is, as fractions of the image.

    ``box`` is ``[left, top, width, height]``. ``method`` is ``skin_region``
    when a face-like area was found and ``default`` otherwise.
    """
    image_w, image_h = image.size
    try:
        grid, cols, rows = _skin_grid(image)
        best = None
        best_score = 0.0
        for component in _components(grid, cols, rows):
            score = _face_like(component, cols, rows)
            if score > best_score:
                best, best_score = component, score
    except PhotoCropError:
        raise
    except Exception:
        best = None
    if best is None:
        return {"box": _default_box(image_w, image_h), "method": "default"}
    cx, cy, face_w = _head(best, grid)
    cell_w = image_w / float(cols)
    cell_h = image_h / float(rows)
    # A head-and-shoulders frame: the face is about five eighths of its width.
    width = face_w * cell_w * 1.6
    height = width / PORTRAIT_ASPECT
    box = _fit_box(cx * cell_w, cy * cell_h + height * 0.04, width, height, image_w, image_h)
    try:
        box = _inside_frame(image, box)
    except Exception:
        pass
    return {"box": box, "method": "skin_region"}


def normalize_box(box: Any) -> List[float]:
    """Validate a ``[left, top, width, height]`` box given in fractions."""
    if isinstance(box, dict):
        box = [box.get("x", box.get("left")), box.get("y", box.get("top")),
               box.get("w", box.get("width")), box.get("h", box.get("height"))]
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        raise PhotoCropError("The photo box must be left, top, width, height", "photo_box_invalid")
    try:
        left, top, width, height = (float(value) for value in box)
    except (TypeError, ValueError) as exc:
        raise PhotoCropError("The photo box must be numbers", "photo_box_invalid") from exc
    if not all(value == value and abs(value) != float("inf") for value in (left, top, width, height)):
        raise PhotoCropError("The photo box must be numbers", "photo_box_invalid")
    if width < _MIN_SIDE or height < _MIN_SIDE:
        raise PhotoCropError("The photo box is too small", "photo_box_invalid")
    left = min(max(0.0, left), 1.0 - _MIN_SIDE)
    top = min(max(0.0, top), 1.0 - _MIN_SIDE)
    width = min(width, 1.0 - left)
    height = min(height, 1.0 - top)
    return [round(left, 4), round(top, 4), round(width, 4), round(height, 4)]


def crop_portrait(image, box: Any) -> Tuple[bytes, List[float]]:
    """Cut the confirmed box and return a 360x450 JPEG with the box used."""
    Image, _chops, ImageOps = _pil()
    left, top, width, height = normalize_box(box)
    image_w, image_h = image.size
    pixels = (
        int(round(left * image_w)), int(round(top * image_h)),
        int(round((left + width) * image_w)), int(round((top + height) * image_h)),
    )
    if pixels[2] - pixels[0] < 24 or pixels[3] - pixels[1] < 24:
        raise PhotoCropError("The photo box is too small", "photo_box_invalid")
    portrait = ImageOps.fit(image.crop(pixels), PORTRAIT_SIZE, Image.LANCZOS, centering=(0.5, 0.4))
    out = io.BytesIO()
    portrait.save(out, format="JPEG", quality=88, optimize=True)
    return out.getvalue(), [left, top, width, height]


def preview_jpeg(image, long_side: int = 900) -> bytes:
    """A reduced copy for the chat's crop screen. The original stays sealed."""
    Image, _chops, _ops = _pil()
    scale = float(long_side) / max(image.size)
    shown = image if scale >= 1 else image.resize(
        (max(1, int(image.width * scale)), max(1, int(image.height * scale))), Image.LANCZOS,
    )
    out = io.BytesIO()
    shown.save(out, format="JPEG", quality=80)
    return out.getvalue()


def portrait_from_document(data: bytes, mime_type: str = "", box: Optional[Any] = None) -> Dict[str, Any]:
    """Cut a portrait in one call. Without a box the proposal is used."""
    image = load_image(data, mime_type)
    proposal = propose_portrait_box(image)
    jpeg, used = crop_portrait(image, box if box is not None else proposal["box"])
    return {
        "jpeg": jpeg,
        "box": used,
        "method": "customer_box" if box is not None else proposal["method"],
        "proposal": proposal,
        "source_size": list(image.size),
    }
