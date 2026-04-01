from __future__ import annotations

import io
import os
from typing import Any

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageOps, UnidentifiedImageError


def _rewind(file_obj: Any) -> Any:
    try:
        file_obj.seek(0)
    except Exception:
        pass
    return file_obj


def _has_alpha(image: Image.Image) -> bool:
    if image.mode in {"RGBA", "LA"}:
        return True
    if image.mode == "P":
        return "transparency" in image.info
    return False


def optimize_uploaded_image(
    file_obj: Any,
    *,
    max_width: int,
    max_height: int,
    quality: int = 82,
) -> Any:
    """Resize and re-encode uploaded images when that reduces storage cost.

    The optimizer keeps the original file when:
    - it is not a readable image, or
    - re-encoding would not reduce size and no resize was needed.
    """
    if not file_obj:
        return file_obj

    original_name = (getattr(file_obj, "name", "") or "upload").strip() or "upload"

    try:
        file_obj.seek(0)
        original_bytes = file_obj.read()
        file_obj.seek(0)
    except Exception:
        return file_obj

    if not original_bytes:
        return file_obj

    try:
        with Image.open(io.BytesIO(original_bytes)) as opened:
            image = ImageOps.exif_transpose(opened)
            had_alpha = _has_alpha(image)
            image = image.copy()
    except (UnidentifiedImageError, OSError, ValueError):
        return _rewind(file_obj)

    resized = False
    if image.width > max_width or image.height > max_height:
        image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        resized = True

    if had_alpha:
        if image.mode not in {"RGBA", "LA"}:
            image = image.convert("RGBA")
    else:
        if image.mode != "RGB":
            image = image.convert("RGB")

    output = io.BytesIO()
    save_kwargs = {
        "format": "WEBP",
        "method": 6,
        "quality": int(quality),
    }
    if had_alpha:
        save_kwargs["lossless"] = True

    image.save(output, **save_kwargs)
    optimized_bytes = output.getvalue()

    if not resized and len(optimized_bytes) >= len(original_bytes):
        return _rewind(file_obj)

    stem, _ext = os.path.splitext(original_name)
    stem = (stem or "upload").strip().replace(" ", "_")[:80]
    return SimpleUploadedFile(
        f"{stem}.webp",
        optimized_bytes,
        content_type="image/webp",
    )
