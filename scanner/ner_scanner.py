"""
scanner/ner_scanner.py - Optimized
- Model loaded once at startup (not per call)
- Runs in thread pool so it doesn't block the API
- Skipped entirely for images (regex is enough)
"""

import spacy
from concurrent.futures import ThreadPoolExecutor

# Load once at import time — not per request
try:
    nlp = spacy.load("en_core_web_sm")
    # Disable unused pipes for speed
    nlp.select_pipes(enable=["ner"])
except OSError:
    raise OSError("Run: python -m spacy download en_core_web_sm")

# Thread pool for NER (keeps API non-blocking)
_executor = ThreadPoolExecutor(max_workers=2)

ENTITY_MAP = {
    "PERSON": ("NAME",      "[NAME]",     "MED"),
    "GPE":    ("LOCATION",  "[LOCATION]", "LOW"),
    "LOC":    ("ADDRESS",   "[ADDRESS]",  "MED"),
    "MONEY":  ("FINANCIAL", "[FINANCIAL]","MED"),
}

FALSE_POSITIVES = {
    "i","we","he","she","it","they","you","me","us","him","her",
    "monday","tuesday","wednesday","thursday","friday","saturday","sunday",
    "january","february","march","april","may","june","july","august",
    "september","october","november","december",
    "today","tomorrow","yesterday","morning","evening","night",
    "india","usa","uk","google","microsoft","apple","amazon",
    "hello","hi","hey","hii","thanks","thank","please","yes","no","okay","ok",
    "the","a","an","is","are","was","were","been","being","have","has","had",
    "do","does","did","will","would","could","should","may","might","shall",
    "what","when","where","who","why","how","which",
}

MIN_ENTITY_LENGTH = 4


def _run_ner(text):
    findings = []
    seen = set()
    # Limit text length for speed — NER on huge text is slow
    doc = nlp(text[:10000])
    for ent in doc.ents:
        if ent.label_ not in ENTITY_MAP:
            continue
        value = ent.text.strip()
        if len(value) < MIN_ENTITY_LENGTH:
            continue
        if value.lower() in FALSE_POSITIVES:
            continue
        if value.lower() in seen:
            continue
        seen.add(value.lower())
        ftype, replace, risk = ENTITY_MAP[ent.label_]
        findings.append({
            "type": ftype, "value": value,
            "replace": replace, "risk": risk,
            "start": ent.start_char, "end": ent.end_char,
            "ner_label": ent.label_,
        })
    findings.sort(key=lambda x: x["start"])
    return findings


def scan_text_ner(text, document_type="General"):
    """
    Run NER synchronously. Fast because:
    - Model already loaded
    - Pipes disabled except ner
    - Text capped at 10000 chars
    """
    if not text or len(text.strip()) < 4:
        return []
    return _run_ner(text)


def scan_text_ner_async(text):
    """
    Submit NER to thread pool. Returns a Future.
    Use when you want to run NER in parallel with regex.
    """
    return _executor.submit(_run_ner, text)