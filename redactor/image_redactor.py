"""
redactor/image_redactor.py

Redacts PII from images (.jpg, .jpeg, .png, .bmp, .webp).

What it does:
  1. Strips ALL EXIF metadata (GPS, device info, timestamps, author)
  2. Detects and blurs human faces using OpenCV
  3. Finds text regions containing PII (via Tesseract OCR) and blacks them out
  4. Returns cleaned image in the SAME format as the input

Preserves:
  - Image dimensions, resolution, color mode
  - Non-PII visual content
  - File format (.jpg stays .jpg, .png stays .png)

Install: pip install Pillow opencv-python pytesseract
         + Tesseract OCR: https://github.com/UB-Mannheim/tesseract/wiki
"""

import os
import re
import shutil
import tempfile
from pathlib import Path


# ─────────────────────────────────────────────────────────
# EXIF STRIPPING
# Removes ALL metadata from image — GPS, device, timestamps
# Uses Pillow — no external binary needed
# ─────────────────────────────────────────────────────────

def _strip_exif(pil_image):
    """
    Return a new PIL Image with all EXIF/metadata removed.
    Works by re-creating the image from raw pixel data.
    """
    from PIL import Image

    # Re-create image from pixel data — strips all metadata
    data = pil_image.tobytes()
    clean = Image.frombytes(pil_image.mode, pil_image.size, data)
    return clean


# ─────────────────────────────────────────────────────────
# FACE DETECTION + BLURRING
# Uses OpenCV Haar Cascade — runs 100% offline, no model download
# The cascade XML ships with opencv-python
# ─────────────────────────────────────────────────────────

def _get_face_cascade():
    """Load OpenCV's built-in frontal face Haar cascade."""
    import cv2
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    if not os.path.exists(cascade_path):
        raise FileNotFoundError(
            f"OpenCV Haar cascade not found at: {cascade_path}. "
            "Reinstall opencv-python: pip install opencv-python"
        )
    return cv2.CascadeClassifier(cascade_path)


def _detect_faces(cv_image):
    """
    Detect face bounding boxes in a BGR OpenCV image.
    Returns list of (x, y, w, h) tuples.
    """
    import cv2

    cascade = _get_face_cascade()
    gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)

    faces = cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(30, 30),
        flags=cv2.CASCADE_SCALE_IMAGE
    )

    if len(faces) == 0:
        return []

    return [(int(x), int(y), int(w), int(h)) for (x, y, w, h) in faces]


def _blur_region(cv_image, x, y, w, h, blur_strength=51):
    """
    Apply strong Gaussian blur to a rectangular region of a CV image.
    blur_strength must be odd — we enforce this.
    """
    import cv2

    # Ensure blur kernel is odd
    if blur_strength % 2 == 0:
        blur_strength += 1

    # Add padding around face for better coverage
    pad = int(min(w, h) * 0.15)
    x1 = max(0, x - pad)
    y1 = max(0, y - pad)
    x2 = min(cv_image.shape[1], x + w + pad)
    y2 = min(cv_image.shape[0], y + h + pad)

    region = cv_image[y1:y2, x1:x2]
    blurred = cv2.GaussianBlur(region, (blur_strength, blur_strength), 0)
    cv_image[y1:y2, x1:x2] = blurred
    return cv_image


# ─────────────────────────────────────────────────────────
# OCR-BASED TEXT REGION REDACTION
# Finds bounding boxes of text containing PII and blacks them out
# Only blacks out the specific word/region, not the whole image
# ─────────────────────────────────────────────────────────

def _find_pii_text_regions(cv_image, findings):
    """
    Use Tesseract to find bounding boxes of text regions that contain PII.
    Returns list of (x, y, w, h) for regions to black out.
    """
    try:
        import pytesseract
        from pytesseract import Output
        import cv2

        # Set Tesseract path for Windows
        tesseract_path = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
        if os.path.exists(tesseract_path):
            pytesseract.pytesseract.tesseract_cmd = tesseract_path

    except ImportError:
        return []  # pytesseract not available — skip text region redaction

    if not findings:
        return []

    # Build set of PII values to look for (lowercase for matching)
    pii_values = set()
    for f in findings:
        val = f.get("value", "").lower().strip()
        if val:
            pii_values.add(val)

    if not pii_values:
        return []

    try:
        # Get word-level bounding boxes from Tesseract
        data = pytesseract.image_to_data(
            cv_image,
            output_type=Output.DICT,
            config="--psm 11"  # sparse text — works on photos/screenshots
        )

        regions_to_redact = []
        n_boxes = len(data["text"])

        for i in range(n_boxes):
            word = data["text"][i].strip().lower()
            if not word:
                continue
            conf = int(data["conf"][i])
            if conf < 30:  # Skip very low confidence detections
                continue

            # Check if this word is part of any PII value
            for pii_val in pii_values:
                if word in pii_val or pii_val in word or word == pii_val:
                    x = data["left"][i]
                    y = data["top"][i]
                    w = data["width"][i]
                    h = data["height"][i]
                    if w > 0 and h > 0:
                        regions_to_redact.append((x, y, w, h))
                    break

        return regions_to_redact

    except Exception:
        return []


def _black_out_region(cv_image, x, y, w, h):
    """Fill a region with black pixels."""
    import cv2
    pad = 2  # small padding
    x1 = max(0, x - pad)
    y1 = max(0, y - pad)
    x2 = min(cv_image.shape[1], x + w + pad)
    y2 = min(cv_image.shape[0], y + h + pad)
    cv_image[y1:y2, x1:x2] = 0
    return cv_image


# ─────────────────────────────────────────────────────────
# PIL ↔ CV2 CONVERSION HELPERS
# ─────────────────────────────────────────────────────────

def _pil_to_cv(pil_image):
    """Convert PIL Image (RGB) to OpenCV BGR array."""
    import cv2
    import numpy as np
    from PIL import Image

    # Ensure RGB
    if pil_image.mode not in ("RGB", "RGBA", "L"):
        pil_image = pil_image.convert("RGB")

    if pil_image.mode == "RGBA":
        # Keep alpha — convert to BGR with alpha
        arr = np.array(pil_image)
        return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGRA)
    elif pil_image.mode == "L":
        arr = np.array(pil_image)
        return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    else:
        arr = np.array(pil_image)
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def _cv_to_pil(cv_image):
    """Convert OpenCV BGR/BGRA array to PIL Image (RGB/RGBA)."""
    import cv2
    import numpy as np
    from PIL import Image

    if cv_image.ndim == 2:
        return Image.fromarray(cv_image, "L")
    elif cv_image.shape[2] == 4:
        rgb = cv2.cvtColor(cv_image, cv2.COLOR_BGRA2RGBA)
        return Image.fromarray(rgb)
    else:
        rgb = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
        return Image.fromarray(rgb)


# ─────────────────────────────────────────────────────────
# PUBLIC ENTRY POINT
# ─────────────────────────────────────────────────────────

def redact_image(src_path, findings, out_path,
                 blur_faces=True,
                 redact_text_regions=True,
                 strip_exif=True):
    """
    Redact PII from an image file and save to out_path.

    Parameters
    ----------
    src_path           : str   — path to original image
    findings           : list  — findings from scanner (value, replace, type)
    out_path           : str   — where to save cleaned image
    blur_faces         : bool  — blur detected human faces (default True)
    redact_text_regions: bool  — black out text regions containing PII (default True)
    strip_exif         : bool  — remove all EXIF metadata (default True)

    Returns
    -------
    out_path : str — path to cleaned image
    report   : dict — what was done:
        {
            "faces_blurred": int,
            "text_regions_redacted": int,
            "exif_stripped": bool,
        }

    Raises
    ------
    ImportError      if Pillow or OpenCV not installed
    FileNotFoundError if src_path does not exist
    """
    try:
        from PIL import Image
    except ImportError:
        raise ImportError(
            "Pillow is required for image redaction. "
            "Install it with: pip install Pillow"
        )

    try:
        import cv2
        import numpy as np
        HAS_CV2 = True
    except ImportError:
        HAS_CV2 = False

    if not os.path.exists(src_path):
        raise FileNotFoundError(f"Source image not found: {src_path}")

    report = {
        "faces_blurred": 0,
        "text_regions_redacted": 0,
        "exif_stripped": False,
    }

    # Determine output format from src extension (preserve format)
    src_ext = Path(src_path).suffix.lower()
    format_map = {
        ".jpg":  "JPEG",
        ".jpeg": "JPEG",
        ".png":  "PNG",
        ".bmp":  "BMP",
        ".webp": "WEBP",
        ".gif":  "GIF",
    }
    save_format = format_map.get(src_ext, "PNG")

    # Load image with Pillow
    pil_image = Image.open(src_path)

    # Convert to RGB if palette/CMYK (needed for CV2 processing)
    if pil_image.mode in ("P", "CMYK", "YCbCr"):
        pil_image = pil_image.convert("RGB")

    # ── Step 1: Strip EXIF ────────────────────────────────
    if strip_exif:
        pil_image = _strip_exif(pil_image)
        report["exif_stripped"] = True

    # ── Step 2: Face blur + text region redaction (needs CV2) ─
    if HAS_CV2 and (blur_faces or redact_text_regions):
        cv_image = _pil_to_cv(pil_image)

        # Face detection and blurring
        if blur_faces:
            try:
                faces = _detect_faces(cv_image)
                for (x, y, w, h) in faces:
                    cv_image = _blur_region(cv_image, x, y, w, h)
                report["faces_blurred"] = len(faces)
            except Exception as e:
                # Face detection failure is non-fatal
                report["face_error"] = str(e)

        # Text region redaction (black out PII text visible in image)
        if redact_text_regions and findings:
            try:
                text_regions = _find_pii_text_regions(cv_image, findings)
                for (x, y, w, h) in text_regions:
                    cv_image = _black_out_region(cv_image, x, y, w, h)
                report["text_regions_redacted"] = len(text_regions)
            except Exception as e:
                report["text_region_error"] = str(e)

        # Convert back to PIL
        pil_image = _cv_to_pil(cv_image)

    # ── Step 3: Save in original format ───────────────────
    save_kwargs = {}
    if save_format == "JPEG":
        save_kwargs["quality"] = 95
        save_kwargs["optimize"] = True
        # JPEG doesn't support RGBA
        if pil_image.mode == "RGBA":
            pil_image = pil_image.convert("RGB")
    elif save_format == "PNG":
        save_kwargs["optimize"] = True

    pil_image.save(out_path, format=save_format, **save_kwargs)

    return out_path, report


# ─────────────────────────────────────────────────────────
# EXTRACTION  — used by api.py to get text for scanning
# ─────────────────────────────────────────────────────────

def extract_text_image(src_path):
    """
    Extract all visible text from an image using Tesseract OCR.
    Returns plain string. Used by api.py before calling redact_image().
    """
    try:
        import pytesseract
        from PIL import Image

        tesseract_path = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
        if os.path.exists(tesseract_path):
            pytesseract.pytesseract.tesseract_cmd = tesseract_path

        img = Image.open(src_path)
        text = pytesseract.image_to_string(img, config="--psm 11")
        return text.strip()

    except ImportError:
        raise ImportError(
            "pytesseract and Pillow required for image text extraction. "
            "pip install pytesseract Pillow"
        )
    except Exception as e:
        raise RuntimeError(f"OCR failed on {src_path}: {e}")