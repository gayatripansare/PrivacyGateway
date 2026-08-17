"""
redactor/image_redactor.py - Fast + Full version

What it does:
  1. Strips ALL EXIF metadata (GPS, device info, timestamps)
  2. Detects and blurs human faces using OpenCV
  3. Finds text regions containing PII via Tesseract OCR and blacks them out
  4. Returns cleaned image in the SAME format as input

Install: pip install Pillow opencv-python pytesseract
         + Tesseract OCR: https://github.com/UB-Mannheim/tesseract/wiki
"""

import os
from pathlib import Path


# ── Tesseract path (Windows) ──────────────────────────────
TESSERACT_PATH = r'C:\Program Files\Tesseract-OCR\tesseract.exe'


def _set_tesseract():
    try:
        import pytesseract
        if os.path.exists(TESSERACT_PATH):
            pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
    except ImportError:
        pass


# ── EXIF stripping ────────────────────────────────────────

def _strip_exif(pil_image):
    from PIL import Image
    data = pil_image.tobytes()
    return Image.frombytes(pil_image.mode, pil_image.size, data)


# ── Face detection + blur ─────────────────────────────────

def _detect_faces(cv_image):
    import cv2
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    if not os.path.exists(cascade_path):
        raise FileNotFoundError(f"Haar cascade not found: {cascade_path}")
    cascade = cv2.CascadeClassifier(cascade_path)
    gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(30, 30))
    return [(int(x), int(y), int(w), int(h)) for (x, y, w, h) in faces] if len(faces) else []


def _blur_region(cv_image, x, y, w, h, strength=51):
    import cv2
    if strength % 2 == 0:
        strength += 1
    pad = int(min(w, h) * 0.15)
    x1, y1 = max(0, x - pad), max(0, y - pad)
    x2, y2 = min(cv_image.shape[1], x + w + pad), min(cv_image.shape[0], y + h + pad)
    cv_image[y1:y2, x1:x2] = cv2.GaussianBlur(cv_image[y1:y2, x1:x2], (strength, strength), 0)
    return cv_image


# ── OCR text region redaction ─────────────────────────────

def _black_out_regions(cv_image, findings):
    """
    Fast OCR: resizes image to max 1200px wide, uses PSM 11.
    Blacks out word bounding boxes that match any PII value.
    """
    try:
        import pytesseract
        from pytesseract import Output
        import cv2

        _set_tesseract()

        pii_vals = {f.get("value", "").lower().strip() for f in findings}
        pii_vals.discard("")
        if not pii_vals:
            return cv_image

        # Resize for speed
        h, w = cv_image.shape[:2]
        if w > 1200:
            scale = 1200 / w
            small = cv2.resize(cv_image, (1200, int(h * scale)))
            sx, sy = w / 1200, h / int(h * scale)
        else:
            small = cv_image
            sx = sy = 1.0

        data = pytesseract.image_to_data(
            small, output_type=Output.DICT,
            config="--psm 11 --oem 3"
        )

        for i in range(len(data["text"])):
            word = data["text"][i].strip().lower()
            if not word or int(data["conf"][i]) < 30:
                continue
            for pval in pii_vals:
                if word in pval or pval in word:
                    x = int(data["left"][i]  * sx)
                    y = int(data["top"][i]   * sy)
                    bw = int(data["width"][i] * sx)
                    bh = int(data["height"][i]* sy)
                    if bw > 0 and bh > 0:
                        pad = 3
                        cv_image[max(0, y-pad):y+bh+pad, max(0, x-pad):x+bw+pad] = 0
                    break

    except Exception:
        pass
    return cv_image


# ── PIL <-> CV2 helpers ───────────────────────────────────

def _pil_to_cv(pil_image):
    import cv2, numpy as np
    if pil_image.mode == "RGBA":
        return cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGBA2BGRA)
    elif pil_image.mode == "L":
        return cv2.cvtColor(np.array(pil_image), cv2.COLOR_GRAY2BGR)
    else:
        return cv2.cvtColor(np.array(pil_image.convert("RGB")), cv2.COLOR_RGB2BGR)


def _cv_to_pil(cv_image):
    import cv2, numpy as np
    from PIL import Image
    if cv_image.ndim == 2:
        return Image.fromarray(cv_image, "L")
    elif cv_image.shape[2] == 4:
        return Image.fromarray(cv2.cvtColor(cv_image, cv2.COLOR_BGRA2RGBA))
    else:
        return Image.fromarray(cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB))


# ── Public: redact_image ──────────────────────────────────

def redact_image(src_path, findings, out_path,
                 blur_faces=True, redact_text_regions=True, strip_exif=True):
    """
    Redact PII from an image and save to out_path.

    Returns (out_path, report) where report = {
        faces_blurred, text_regions_redacted, exif_stripped
    }
    """
    from PIL import Image

    try:
        import cv2, numpy as np
        HAS_CV2 = True
    except ImportError:
        HAS_CV2 = False

    if not os.path.exists(src_path):
        raise FileNotFoundError(f"Source image not found: {src_path}")

    report = {"faces_blurred": 0, "text_regions_redacted": 0, "exif_stripped": False}

    src_ext  = Path(src_path).suffix.lower()
    fmt_map  = {".jpg":"JPEG",".jpeg":"JPEG",".png":"PNG",
                ".bmp":"BMP",".webp":"WEBP",".gif":"GIF"}
    save_fmt = fmt_map.get(src_ext, "PNG")

    pil_image = Image.open(src_path)
    if pil_image.mode in ("P", "CMYK", "YCbCr"):
        pil_image = pil_image.convert("RGB")

    if strip_exif:
        pil_image = _strip_exif(pil_image)
        report["exif_stripped"] = True

    if HAS_CV2:
        cv_image = _pil_to_cv(pil_image)

        if blur_faces:
            try:
                faces = _detect_faces(cv_image)
                for (x, y, w, h) in faces:
                    cv_image = _blur_region(cv_image, x, y, w, h)
                report["faces_blurred"] = len(faces)
            except Exception as e:
                report["face_error"] = str(e)

        if redact_text_regions and findings:
            try:
                before = cv_image.copy()
                cv_image = _black_out_regions(cv_image, findings)
                changed = int((cv_image != before).any(axis=2).sum())
                report["text_regions_redacted"] = changed
            except Exception as e:
                report["text_region_error"] = str(e)

        pil_image = _cv_to_pil(cv_image)

    kw = {}
    if save_fmt == "JPEG":
        kw = {"quality": 95, "optimize": True}
        if pil_image.mode == "RGBA":
            pil_image = pil_image.convert("RGB")
    elif save_fmt == "PNG":
        kw = {"optimize": True}

    pil_image.save(out_path, format=save_fmt, **kw)
    return out_path, report


# ── Public: extract_text_image ────────────────────────────

def extract_text_image(src_path):
    """
    Fast OCR: resizes to 1200px wide, grayscale + Otsu threshold, PSM 11.
    Returns extracted text string.
    """
    try:
        import pytesseract
        from PIL import Image
        import cv2, numpy as np

        _set_tesseract()

        img = Image.open(src_path).convert("RGB")

        w, h = img.size
        if w > 1200:
            img = img.resize((1200, int(h * 1200 / w)), Image.LANCZOS)

        arr = np.array(img)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        processed = Image.fromarray(thresh)

        return pytesseract.image_to_string(processed, config="--psm 11 --oem 3").strip()

    except ImportError:
        raise ImportError("pip install pytesseract Pillow opencv-python")
    except Exception as e:
        raise RuntimeError(f"OCR failed on {src_path}: {e}")