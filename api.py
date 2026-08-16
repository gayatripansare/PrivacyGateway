"""
api.py

PrivacyGate Background Service — FastAPI
Runs silently on Windows startup.
Chrome extension sends files/text here, gets back cleaned version + report.

Endpoints:
  POST /scan-text        — scan plain text, return findings + cleaned text
  POST /scan-file        — scan any file, return cleaned file + report
  GET  /status           — is the service running?
  GET  /stats            — total scans, PII blocked, breakdown by type
  GET  /history          — last N scan records
  DELETE /history        — clear all history

Supported file types:
  .txt .csv .json .py .js .html .md  — plain text redaction
  .pdf                                — pymupdf redaction
  .docx .doc                          — python-docx XML redaction
  .xlsx .xlsm                         — openpyxl redaction
  .pptx                               — python-pptx redaction
  .jpg .jpeg .png .bmp .webp          — Pillow + OpenCV redaction

Install:
  pip install fastapi uvicorn python-multipart

Run:
  uvicorn api:app --host 127.0.0.1 --port 8000 --log-level error
"""

import os
import sys
import uuid
import time
import shutil
import sqlite3
import tempfile
import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ─────────────────────────────────────────────────────────
# PATH SETUP
# Make sure scanner/redactor modules are importable
# when api.py is run from any working directory
# ─────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# ─────────────────────────────────────────────────────────
# SCANNER IMPORTS
# ─────────────────────────────────────────────────────────

from scanner.regex_scanner import scan_text_regex
from scanner.ner_scanner   import scan_text_ner
from scanner.context_rules import apply_context_rules

# ─────────────────────────────────────────────────────────
# REDACTOR IMPORTS
# ─────────────────────────────────────────────────────────

from redactor.text_redactor  import redact_text
from redactor.xlsx_redactor  import redact_xlsx,  get_full_text_xlsx
from redactor.pptx_redactor  import redact_pptx,  get_full_text_pptx
from redactor.image_redactor import redact_image,  extract_text_image

# pdf and docx redactors live in text_redactor.py already
from redactor.text_redactor import redact_docx, redact_pdf

# ─────────────────────────────────────────────────────────
# DATABASE — SQLite, stored in C:\ProgramData\PrivacyGate\
# Separate from desktop app's audit_log.json
# ─────────────────────────────────────────────────────────

DB_DIR  = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "PrivacyGate"
DB_PATH = DB_DIR / "scans.db"

def _get_db():
    """Return a SQLite connection. Creates DB and tables if needed."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    return conn


def _init_db(conn):
    """Create tables if they don't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scans (
            id            TEXT PRIMARY KEY,
            timestamp     TEXT NOT NULL,
            source        TEXT NOT NULL,   -- 'text' | 'file'
            file_name     TEXT,
            file_type     TEXT,
            original_size INTEGER,
            findings_count INTEGER NOT NULL DEFAULT 0,
            types_found   TEXT,            -- JSON array as string
            high_count    INTEGER DEFAULT 0,
            med_count     INTEGER DEFAULT 0,
            low_count     INTEGER DEFAULT 0,
            duration_ms   INTEGER,
            status        TEXT DEFAULT 'ok' -- 'ok' | 'error'
        )
    """)
    conn.commit()


def _log_scan(source, findings, file_name=None, file_type=None,
              original_size=None, duration_ms=None, status="ok"):
    """Write one scan record to SQLite."""
    import json
    scan_id    = str(uuid.uuid4())
    timestamp  = datetime.datetime.now().isoformat(timespec="seconds")
    types_found = list(set(f.get("type", "") for f in findings))

    high = sum(1 for f in findings if f.get("risk") == "HIGH")
    med  = sum(1 for f in findings if f.get("risk") == "MED")
    low  = sum(1 for f in findings if f.get("risk") == "LOW")

    conn = _get_db()
    try:
        conn.execute("""
            INSERT INTO scans
              (id, timestamp, source, file_name, file_type, original_size,
               findings_count, types_found, high_count, med_count, low_count,
               duration_ms, status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            scan_id, timestamp, source, file_name, file_type, original_size,
            len(findings), json.dumps(types_found),
            high, med, low, duration_ms, status
        ))
        conn.commit()
    finally:
        conn.close()

    return scan_id


# ─────────────────────────────────────────────────────────
# TEMP FILE MANAGEMENT
# Cleaned files are written to temp dir and served back.
# We clean up files older than 10 minutes automatically.
# ─────────────────────────────────────────────────────────

TEMP_DIR = Path(tempfile.gettempdir()) / "privacygate_cleaned"
TEMP_DIR.mkdir(exist_ok=True)


def _temp_output_path(original_name: str) -> Path:
    """Generate a unique temp path preserving the original file extension."""
    ext  = Path(original_name).suffix.lower()
    name = f"pg_{uuid.uuid4().hex}{ext}"
    return TEMP_DIR / name


def _cleanup_old_temp_files():
    """Delete temp files older than 10 minutes."""
    cutoff = time.time() - 600  # 10 minutes
    try:
        for f in TEMP_DIR.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────
# FILE TYPE ROUTING
# ─────────────────────────────────────────────────────────

TEXT_EXTENSIONS = {
    ".txt", ".csv", ".json", ".jsonl", ".py", ".js", ".ts",
    ".html", ".htm", ".xml", ".md", ".yaml", ".yml",
    ".ini", ".cfg", ".env", ".sh", ".bat", ".sql",
    ".log", ".jsx", ".tsx", ".css", ".scss",
}

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif",
}


def _get_file_type(filename: str) -> str:
    """Return normalized file type string from filename."""
    ext = Path(filename).suffix.lower()
    if ext in (".docx", ".doc"):
        return "docx"
    if ext == ".pdf":
        return "pdf"
    if ext in (".xlsx", ".xlsm"):
        return "xlsx"
    if ext == ".pptx":
        return "pptx"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in TEXT_EXTENSIONS:
        return "text"
    return "text"  # default — try as plain text


def _extract_text_from_file(file_path: Path, file_type: str) -> str:
    """
    Extract plain text from a file for scanning.
    Returns text string — fed into scanner modules.
    """
    if file_type == "text":
        return file_path.read_text(encoding="utf-8", errors="ignore")

    if file_type == "pdf":
        try:
            import pdfplumber
            with pdfplumber.open(str(file_path)) as pdf:
                return "\n".join(p.extract_text() or "" for p in pdf.pages)
        except ImportError:
            raise HTTPException(500, "pdfplumber not installed: pip install pdfplumber")

    if file_type == "docx":
        try:
            import docx as docxlib
            doc = docxlib.Document(str(file_path))
            parts = [p.text for p in doc.paragraphs]
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        parts.append(cell.text)
            return "\n".join(parts)
        except ImportError:
            raise HTTPException(500, "python-docx not installed: pip install python-docx")

    if file_type == "xlsx":
        return get_full_text_xlsx(str(file_path))

    if file_type == "pptx":
        return get_full_text_pptx(str(file_path))

    if file_type == "image":
        return extract_text_image(str(file_path))

    return ""


def _run_scanner(text: str, sensitivity: str = "standard") -> list:
    """
    Run all scanner layers on text. Returns combined findings list.
    sensitivity: 'standard' | 'deep'
    """
    findings = []
    findings.extend(scan_text_regex(text))
    findings.extend(scan_text_ner(text))

    if sensitivity == "deep":
        findings = apply_context_rules(findings, text)

    # Deduplicate by value
    seen = set()
    unique = []
    for f in findings:
        key = f.get("value", "").lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(f)

    return unique


def _redact_file(file_path: Path, file_type: str, findings: list,
                 out_path: Path) -> Path:
    """
    Route to correct redactor based on file type.
    Returns path to cleaned file.
    """
    if not findings:
        # Nothing to redact — copy original unchanged
        shutil.copy2(str(file_path), str(out_path))
        return out_path

    if file_type == "text":
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        cleaned_text, _, _ = redact_text(text, findings)
        out_path.write_text(cleaned_text, encoding="utf-8")
        return out_path

    if file_type == "pdf":
        redact_pdf(str(file_path), findings, str(out_path))
        return out_path

    if file_type == "docx":
        redact_docx(str(file_path), findings, str(out_path))
        return out_path

    if file_type == "xlsx":
        redact_xlsx(str(file_path), findings, str(out_path))
        return out_path

    if file_type == "pptx":
        redact_pptx(str(file_path), findings, str(out_path))
        return out_path

    if file_type == "image":
        redact_image(str(file_path), findings, str(out_path))
        return out_path

    # Unknown — copy unchanged
    shutil.copy2(str(file_path), str(out_path))
    return out_path


# ─────────────────────────────────────────────────────────
# FASTAPI APP
# ─────────────────────────────────────────────────────────

app = FastAPI(
    title="PrivacyGate",
    description="Local privacy scanning service — no data leaves your machine.",
    version="1.0.0",
    docs_url=None,   # Disable Swagger UI in production
    redoc_url=None,
)

# Allow Chrome extension to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],           # Extension can call from any origin
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────────────────

class TextScanRequest(BaseModel):
    text: str
    sensitivity: Optional[str] = "standard"   # standard | deep


class TextScanResponse(BaseModel):
    scan_id:       str
    findings_count: int
    findings:      list
    cleaned_text:  str
    types_found:   list
    high_count:    int
    med_count:     int
    low_count:     int
    duration_ms:   int


# ─────────────────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────────────────

@app.get("/status")
def status():
    """Health check — extension calls this to verify service is running."""
    return {
        "status":  "running",
        "service": "PrivacyGate",
        "version": "1.0.0",
    }


@app.post("/scan-text", response_model=TextScanResponse)
def scan_text_endpoint(req: TextScanRequest):
    """
    Scan plain text for PII and return cleaned version.
    Called by extension for text paste interception.
    """
    if not req.text or not req.text.strip():
        raise HTTPException(400, "Text is empty.")

    start = time.time()
    findings = _run_scanner(req.text, req.sensitivity or "standard")
    cleaned_text, _, _ = redact_text(req.text, findings)
    duration_ms = int((time.time() - start) * 1000)

    scan_id = _log_scan(
        source="text",
        findings=findings,
        duration_ms=duration_ms,
    )

    types_found = list(set(f.get("type", "") for f in findings))
    high = sum(1 for f in findings if f.get("risk") == "HIGH")
    med  = sum(1 for f in findings if f.get("risk") == "MED")
    low  = sum(1 for f in findings if f.get("risk") == "LOW")

    return TextScanResponse(
        scan_id=scan_id,
        findings_count=len(findings),
        findings=findings,
        cleaned_text=cleaned_text,
        types_found=types_found,
        high_count=high,
        med_count=med,
        low_count=low,
        duration_ms=duration_ms,
    )


@app.post("/scan-file")
async def scan_file_endpoint(
    file:        UploadFile = File(...),
    sensitivity: str        = Form("standard"),
):
    """
    Scan an uploaded file for PII.
    Returns cleaned file in original format + JSON report in headers.

    Response headers contain:
      X-Scan-Id          : unique scan ID
      X-Findings-Count   : number of PII items found
      X-Types-Found      : comma-separated list of PII types
      X-High-Count       : high risk count
      X-Med-Count        : medium risk count
      X-Low-Count        : low risk count
      X-Duration-Ms      : scan duration in milliseconds
      X-Original-Filename: original file name
    """
    _cleanup_old_temp_files()

    filename  = file.filename or "upload"
    file_type = _get_file_type(filename)

    # Save uploaded file to temp location
    suffix   = Path(filename).suffix.lower()
    tmp_in   = Path(tempfile.mktemp(suffix=suffix, dir=str(TEMP_DIR)))
    out_path = _temp_output_path(filename)

    try:
        # Write upload to disk
        content = await file.read()
        tmp_in.write_bytes(content)
        original_size = len(content)

        start = time.time()

        # Extract text for scanning
        try:
            text = _extract_text_from_file(tmp_in, file_type)
        except Exception as e:
            raise HTTPException(422, f"Could not read file: {e}")

        # Run scanner
        findings = _run_scanner(text, sensitivity)

        # Redact file — output in original format
        try:
            _redact_file(tmp_in, file_type, findings, out_path)
        except Exception as e:
            raise HTTPException(500, f"Redaction failed: {e}")

        duration_ms = int((time.time() - start) * 1000)

        # Log to database
        scan_id = _log_scan(
            source="file",
            findings=findings,
            file_name=filename,
            file_type=file_type,
            original_size=original_size,
            duration_ms=duration_ms,
        )

        types_found = list(set(f.get("type", "") for f in findings))
        high = sum(1 for f in findings if f.get("risk") == "HIGH")
        med  = sum(1 for f in findings if f.get("risk") == "MED")
        low  = sum(1 for f in findings if f.get("risk") == "LOW")

        # Build findings summary (safe to send — no actual PII values,
        # just types and placeholders)
        findings_summary = [
            {
                "type":    f.get("type"),
                "replace": f.get("replace"),
                "risk":    f.get("risk"),
            }
            for f in findings
        ]

        import json

        # Return cleaned file with metadata in headers
        return FileResponse(
            path=str(out_path),
            filename=f"PrivacyGate_Cleaned_{filename}",
            media_type="application/octet-stream",
            headers={
                "X-Scan-Id":           scan_id,
                "X-Findings-Count":    str(len(findings)),
                "X-Types-Found":       ",".join(types_found),
                "X-High-Count":        str(high),
                "X-Med-Count":         str(med),
                "X-Low-Count":         str(low),
                "X-Duration-Ms":       str(duration_ms),
                "X-Original-Filename": filename,
                "X-Findings-Summary":  json.dumps(findings_summary),
                # Required for extension to read custom headers
                "Access-Control-Expose-Headers": (
                    "X-Scan-Id, X-Findings-Count, X-Types-Found, "
                    "X-High-Count, X-Med-Count, X-Low-Count, "
                    "X-Duration-Ms, X-Original-Filename, X-Findings-Summary"
                ),
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Unexpected error: {e}")
    finally:
        # Clean up input temp file
        try:
            tmp_in.unlink(missing_ok=True)
        except Exception:
            pass


@app.get("/stats")
def get_stats():
    """
    Return aggregate statistics for the extension popup.
    Total scans, total PII blocked, breakdown by type.
    """
    import json

    conn = _get_db()
    try:
        # Overall totals
        row = conn.execute("""
            SELECT
                COUNT(*)            AS total_scans,
                SUM(findings_count) AS total_pii_blocked,
                SUM(high_count)     AS total_high,
                SUM(med_count)      AS total_med,
                SUM(low_count)      AS total_low
            FROM scans
            WHERE status = 'ok'
        """).fetchone()

        # Today's totals
        today = datetime.date.today().isoformat()
        today_row = conn.execute("""
            SELECT
                COUNT(*)            AS scans_today,
                SUM(findings_count) AS pii_today
            FROM scans
            WHERE status = 'ok'
              AND timestamp LIKE ?
        """, (f"{today}%",)).fetchone()

        # PII type breakdown — parse JSON arrays and count
        type_counts = {}
        rows = conn.execute(
            "SELECT types_found FROM scans WHERE status='ok' AND types_found IS NOT NULL"
        ).fetchall()
        for r in rows:
            try:
                types = json.loads(r["types_found"])
                for t in types:
                    if t:
                        type_counts[t] = type_counts.get(t, 0) + 1
            except Exception:
                pass

        # File type breakdown
        file_types = conn.execute("""
            SELECT file_type, COUNT(*) as cnt
            FROM scans
            WHERE source = 'file' AND status = 'ok' AND file_type IS NOT NULL
            GROUP BY file_type
            ORDER BY cnt DESC
        """).fetchall()

        return {
            "total_scans":      row["total_scans"]       or 0,
            "total_pii_blocked":row["total_pii_blocked"] or 0,
            "total_high":       row["total_high"]        or 0,
            "total_med":        row["total_med"]         or 0,
            "total_low":        row["total_low"]         or 0,
            "scans_today":      today_row["scans_today"] or 0,
            "pii_today":        today_row["pii_today"]   or 0,
            "type_breakdown":   type_counts,
            "file_type_breakdown": {
                r["file_type"]: r["cnt"] for r in file_types
            },
        }
    finally:
        conn.close()


@app.get("/history")
def get_history(limit: int = 50):
    """
    Return last N scan records. Used by desktop app audit panel
    and extension popup history tab.
    limit: max 200
    """
    import json

    limit = min(limit, 200)
    conn = _get_db()
    try:
        rows = conn.execute("""
            SELECT * FROM scans
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,)).fetchall()

        return {
            "records": [
                {
                    "id":             r["id"],
                    "timestamp":      r["timestamp"],
                    "source":         r["source"],
                    "file_name":      r["file_name"],
                    "file_type":      r["file_type"],
                    "findings_count": r["findings_count"],
                    "types_found":    json.loads(r["types_found"] or "[]"),
                    "high_count":     r["high_count"],
                    "med_count":      r["med_count"],
                    "low_count":      r["low_count"],
                    "duration_ms":    r["duration_ms"],
                    "status":         r["status"],
                }
                for r in rows
            ],
            "total": len(rows),
        }
    finally:
        conn.close()


@app.delete("/history")
def clear_history():
    """Clear all scan history. Called from desktop app settings panel."""
    conn = _get_db()
    try:
        conn.execute("DELETE FROM scans")
        conn.commit()
        return {"status": "cleared"}
    finally:
        conn.close()