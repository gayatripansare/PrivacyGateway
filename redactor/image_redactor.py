"""PrivacyGate image redaction with OCR-aware, placeholder-based redaction."""

import os
from pathlib import Path

TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def _set_tesseract():
    try:
        import pytesseract
        if os.path.exists(TESSERACT_PATH):
            pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
    except ImportError:
        pass


def _strip_exif(pil_image):
    from PIL import Image
    return Image.frombytes(pil_image.mode, pil_image.size, pil_image.tobytes())


def _detect_faces(cv_image):
    import cv2
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(30, 30))
    return [(int(x), int(y), int(w), int(h)) for x, y, w, h in faces] if len(faces) else []


def _blur_region(cv_image, x, y, w, h, strength=51):
    import cv2
    strength += strength % 2 == 0
    pad = int(min(w, h) * 0.15)
    x1, y1 = max(0, x - pad), max(0, y - pad)
    x2, y2 = min(cv_image.shape[1], x + w + pad), min(cv_image.shape[0], y + h + pad)
    cv_image[y1:y2, x1:x2] = cv2.GaussianBlur(cv_image[y1:y2, x1:x2], (strength, strength), 0)
    return cv_image


def _norm(value):
    return "".join(ch.lower() for ch in value if ch.isalnum())


def _placeholder_for(finding):
    return str(finding.get("replace") or f"[{finding.get('type', 'REDACTED')}]" )


def _draw_placeholder(cv_image, box, label):
    """Cover one matched OCR region with a readable, high-contrast placeholder."""
    import cv2
    x1, y1, x2, y2 = box
    h, w = cv_image.shape[:2]
    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w - 1, x2), min(h - 1, y2)
    if x2 <= x1 or y2 <= y1:
        return False

    # The sample resumes use a light background. Use an opaque light panel rather
    # than a black fill, then fit the placeholder text inside the matched region.
    cv2.rectangle(cv_image, (x1, y1), (x2, y2), (255, 255, 255), thickness=-1)
    text = label[:24]
    available_w = max(20, x2 - x1 - 6)
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = min(0.55, max(0.25, (y2 - y1) / 26.0))
    while scale > 0.2 and cv2.getTextSize(text, font, scale, 1)[0][0] > available_w:
        scale -= 0.03
    text_w, text_h = cv2.getTextSize(text, font, scale, 1)[0]
    baseline_y = y1 + max(text_h + 2, ((y2 - y1) + text_h) // 2)
    cv2.putText(cv_image, text, (x1 + 3, min(y2 - 2, baseline_y)), font, scale, (30, 30, 30), 1, cv2.LINE_AA)
    return True


def _ocr_words(cv_image):
    import cv2
    import pytesseract
    from pytesseract import Output
    _set_tesseract()
    h, w = cv_image.shape[:2]
    if w > 1600:
        scale = 1600 / w
        small = cv2.resize(cv_image, (1600, max(1, int(h * scale))))
        sx, sy = w / 1600, h / max(1, int(h * scale))
    else:
        small, sx, sy = cv_image, 1.0, 1.0
    data = pytesseract.image_to_data(small, output_type=Output.DICT, config="--psm 11 --oem 3")
    words = []
    for i, raw in enumerate(data.get("text", [])):
        text = raw.strip()
        try:
            conf = float(data["conf"][i])
        except (ValueError, TypeError, KeyError):
            conf = 0
        if not text or conf < 20:
            continue
        left = int(float(data["left"][i]) * sx)
        top = int(float(data["top"][i]) * sy)
        right = left + int(float(data["width"][i]) * sx)
        bottom = top + int(float(data["height"][i]) * sy)
        words.append({
            "text": text,
            "norm": _norm(text),
            "line": (data.get("block_num", [0])[i], data.get("par_num", [0])[i], data.get("line_num", [0])[i]),
            "box": (left, top, right, bottom),
        })
    return words


def _redact_ocr_regions(cv_image, findings):
    """Match complete findings against concatenated OCR lines, not individual words."""
    try:
        import re
        words = _ocr_words(cv_image)
        by_line = {}
        for word in words:
            by_line.setdefault(word["line"], []).append(word)

        redacted = 0
        for finding in findings:
            target = _norm(finding.get("value", ""))
            if len(target) < 4:
                continue
            matched = False
            for line_words in by_line.values():
                line_words.sort(key=lambda item: item["box"][0])
                joined = "".join(item["norm"] for item in line_words)
                start = joined.find(target)
                if start < 0:
                    # OCR may drop one punctuation character; retry against a
                    # whitespace-preserving representation for phone numbers.
                    raw_line = " ".join(item["text"] for item in line_words)
                    compact = re.sub(r"[^a-z0-9@]", "", raw_line.lower())
                    start = compact.find(target)
                if start < 0:
                    continue

                end = start + len(target)
                cursor = 0
                selected = []
                for item in line_words:
                    next_cursor = cursor + len(item["norm"])
                    if next_cursor > start and cursor < end:
                        selected.append(item)
                    cursor = next_cursor
                if not selected:
                    continue
                xs = [item["box"][0] for item in selected] + [item["box"][2] for item in selected]
                ys = [item["box"][1] for item in selected] + [item["box"][3] for item in selected]
                x1, x2 = min(xs) - 3, max(xs) + 3
                y1, y2 = min(ys) - 3, max(ys) + 3
                if _draw_placeholder(cv_image, (x1, y1, x2, y2), _placeholder_for(finding)):
                    redacted += 1
                    matched = True
                    break
            if not matched:
                continue
        return redacted
    except Exception:
        return 0


def _pil_to_cv(pil_image):
    import cv2
    import numpy as np
    if pil_image.mode == "RGBA":
        return cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGBA2BGRA)
    if pil_image.mode == "L":
        return cv2.cvtColor(np.array(pil_image), cv2.COLOR_GRAY2BGR)
    return cv2.cvtColor(np.array(pil_image.convert("RGB")), cv2.COLOR_RGB2BGR)


def _cv_to_pil(cv_image):
    import cv2
    from PIL import Image
    if cv_image.ndim == 2:
        return Image.fromarray(cv_image, "L")
    if cv_image.shape[2] == 4:
        return Image.fromarray(cv2.cvtColor(cv_image, cv2.COLOR_BGRA2RGBA))
    return Image.fromarray(cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB))


def redact_image(src_path, findings, out_path, blur_faces=True, redact_text_regions=True, strip_exif=True):
    from PIL import Image
    try:
        import cv2
        has_cv2 = True
    except ImportError:
        has_cv2 = False

    if not os.path.exists(src_path):
        raise FileNotFoundError(f"Source image not found: {src_path}")
    report = {"faces_blurred": 0, "text_regions_redacted": 0, "exif_stripped": False}
    fmt_map = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".bmp": "BMP", ".webp": "WEBP", ".gif": "GIF"}
    save_fmt = fmt_map.get(Path(src_path).suffix.lower(), "PNG")
    pil_image = Image.open(src_path)
    if pil_image.mode in ("P", "CMYK", "YCbCr"):
        pil_image = pil_image.convert("RGB")
    if strip_exif:
        pil_image = _strip_exif(pil_image)
        report["exif_stripped"] = True

    if has_cv2:
        cv_image = _pil_to_cv(pil_image)
        if blur_faces:
            try:
                faces = _detect_faces(cv_image)
                for x, y, w, h in faces:
                    _blur_region(cv_image, x, y, w, h)
                report["faces_blurred"] = len(faces)
            except Exception as exc:
                report["face_error"] = str(exc)
        if redact_text_regions and findings:
            report["text_regions_redacted"] = _redact_ocr_regions(cv_image, findings)
        pil_image = _cv_to_pil(cv_image)

    kwargs = {}
    if save_fmt == "JPEG":
        kwargs = {"quality": 95, "optimize": True}
        if pil_image.mode == "RGBA":
            pil_image = pil_image.convert("RGB")
    elif save_fmt == "PNG":
        kwargs = {"optimize": True}
    pil_image.save(out_path, format=save_fmt, **kwargs)
    return out_path, report


def extract_text_image(src_path):
    try:
        import cv2
        import numpy as np
        import pytesseract
        from PIL import Image
        _set_tesseract()
        img = Image.open(src_path).convert("RGB")
        w, h = img.size
        # Upscaling small CV/resume screenshots improves recognition of thin
        # phone and email glyphs without changing the returned image size.
        if w < 1400:
            scale = min(2.0, 1400 / max(1, w))
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        elif w > 1800:
            img = img.resize((1800, max(1, int(h * 1800 / w))), Image.LANCZOS)
        arr = np.array(img)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        threshold = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 31, 11
        )
        passes = [(arr, "--psm 11 --oem 3"), (gray, "--psm 11 --oem 3"), (threshold, "--psm 11 --oem 3")]
        outputs, seen = [], set()
        for image, config in passes:
            text = pytesseract.image_to_string(image, config=config).strip()
            if text and text not in seen:
                outputs.append(text)
                seen.add(text)
        return "\\n".join(outputs)
    except ImportError:
        raise ImportError("pip install pytesseract Pillow opencv-python")
    except Exception as exc:
        raise RuntimeError(f"OCR failed on {src_path}: {exc}")
