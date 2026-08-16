"""
docx_native_render.py

Renders a .docx directly as COLORED native tkinter widgets — no LibreOffice,
no Poppler, no external binary of any kind. Reads run colors, bold/italic,
font size, and table cell shading straight out of the docx XML via
python-docx, and builds matching tk.Frame/tk.Text widgets.

This is the fast, dependency-free alternative to the
LibreOffice -> PDF -> image pipeline. Use it FIRST; only fall back to
doc_to_page_images() if this raises or python-docx isn't installed.

Install (only dependency):
    pip install python-docx
"""

import tkinter as tk
from docx.oxml.ns import qn


# ─────────────────────────────────────────────────────────
# XML EXTRACTION HELPERS
# ─────────────────────────────────────────────────────────

def _run_color(run):
    """Return '#RRGGBB' text color for a run, or None if not set."""
    try:
        if run.font.color and run.font.color.rgb:
            return f"#{run.font.color.rgb}"
    except Exception:
        pass
    return None


def _run_size(run, default=10):
    try:
        if run.font.size:
            return int(run.font.size.pt)
    except Exception:
        pass
    return default


def _cell_shading(cell):
    """Return '#RRGGBB' background fill for a table cell, or None."""
    try:
        tcPr = cell._tc.tcPr
        if tcPr is not None:
            shd = tcPr.find(qn('w:shd'))
            if shd is not None:
                fill = shd.get(qn('w:fill'))
                if fill and fill.lower() != "auto":
                    return f"#{fill}"
    except Exception:
        pass
    return None


def _para_shading(paragraph):
    """Some headers use paragraph-level shading instead of cell shading."""
    try:
        pPr = paragraph._p.pPr
        if pPr is not None:
            shd = pPr.find(qn('w:shd'))
            if shd is not None:
                fill = shd.get(qn('w:fill'))
                if fill and fill.lower() != "auto":
                    return f"#{fill}"
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────
# WIDGET BUILDERS
# ─────────────────────────────────────────────────────────

def _render_paragraph(container, paragraph, default_bg="#ffffff", base_font="Segoe UI"):
    """Render one paragraph as a Text widget with per-run color/bold tags."""
    bg = _para_shading(paragraph) or default_bg
    text = paragraph.text

    if not text.strip():
        tk.Frame(container, bg=bg, height=8).pack(fill="x")
        return

    align = "w"
    try:
        if str(paragraph.alignment) == "CENTER (1)":
            align = "center"
    except Exception:
        pass

    txt = tk.Text(
        container, wrap="word", height=1, bg=bg, relief="flat",
        highlightthickness=0, padx=4, pady=3, bd=0,
        font=(base_font, 10)
    )
    if not paragraph.runs:
        txt.insert("end", text)
    else:
        for i, run in enumerate(paragraph.runs):
            color = _run_color(run) or "#1a1a1a"
            size = _run_size(run)
            weight = "bold" if run.font.bold else "normal"
            slant = "italic" if run.font.italic else "roman"
            tag = f"r{i}_{id(run)}"
            txt.tag_configure(tag, foreground=color,
                              font=(base_font, size, weight, slant))
            if align == "center":
                txt.tag_configure(tag, justify="center")
            txt.insert("end", run.text, tag)

    txt.config(state="disabled")
    txt.pack(fill="x")

    # Auto-size height to actual wrapped line count
    def _fit():
        txt.config(state="normal")
        txt.update_idletasks()
        n_lines = int(txt.count("1.0", "end", "displaylines")[0]) if txt.count("1.0", "end", "displaylines") else 1
        txt.config(height=max(1, n_lines), state="disabled")
    container.after(10, _fit)


def _render_table(container, table, base_font="Segoe UI"):
    """Render a docx table as a grid of colored Frames — preserves shading."""
    t_frame = tk.Frame(container, bg="#c9c9c9")
    t_frame.pack(fill="x", pady=(2, 6))

    for row in table.rows:
        row_frame = tk.Frame(t_frame, bg="#c9c9c9")
        row_frame.pack(fill="x")
        for cell in row.cells:
            bg = _cell_shading(cell) or "#ffffff"
            cell_frame = tk.Frame(
                row_frame, bg=bg,
                highlightbackground="#dddddd", highlightthickness=1
            )
            cell_frame.pack(side="left", fill="both", expand=True, padx=1, pady=1)
            for p in cell.paragraphs:
                _render_paragraph(cell_frame, p, default_bg=bg, base_font=base_font)


# ─────────────────────────────────────────────────────────
# PUBLIC ENTRY POINT
# ─────────────────────────────────────────────────────────

def render_docx_native(parent, docx_path, base_font="Segoe UI"):
    """
    Build a scrollable, fully colored native rendering of a .docx inside
    `parent` (a tk widget). Walks the document body in original order so
    paragraphs and tables interleave correctly.

    Returns the outer scroll Frame (already packed into `parent`).
    Raises on failure — caller should catch and fall back if needed.
    """
    import docx as docxlib
    from docx.text.paragraph import Paragraph
    from docx.table import Table

    outer = tk.Frame(parent, bg="#ffffff")
    outer.pack(fill="both", expand=True)

    cvs = tk.Canvas(outer, bg="#ffffff", highlightthickness=0)
    sb = tk.Scrollbar(outer, orient="vertical", command=cvs.yview)
    cvs.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    cvs.pack(side="left", fill="both", expand=True)

    inner = tk.Frame(cvs, bg="#ffffff")
    win = cvs.create_window((0, 0), window=inner, anchor="nw")

    def _on_inner_configure(e):
        cvs.configure(scrollregion=cvs.bbox("all"))
    def _on_canvas_configure(e):
        cvs.itemconfig(win, width=e.width)

    inner.bind("<Configure>", _on_inner_configure)
    cvs.bind("<Configure>", _on_canvas_configure)
    cvs.bind("<MouseWheel>", lambda e: cvs.yview_scroll(int(-1 * (e.delta / 120)), "units"))

    doc = docxlib.Document(docx_path)
    body = doc.element.body

    for child in body.iterchildren():
        tag = child.tag.split('}')[-1]
        if tag == 'p':
            _render_paragraph(inner, Paragraph(child, doc), base_font=base_font)
        elif tag == 'tbl':
            _render_table(inner, Table(child, doc), base_font=base_font)
        # sectPr and other structural tags are skipped

    return outer