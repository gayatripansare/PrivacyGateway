import re

# Only match STRUCTURED data with clear patterns
# Nothing vague — no single words, no short strings
PATTERNS = [
    ("EMAIL",        "[EMAIL]",        "HIGH", r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b'),
    ("PHONE",        "[PHONE]",        "HIGH", r'(?<!\d)(\+91[\-\s]?)?[6-9]\d{9}(?!\d)'),
    ("PHONE",        "[PHONE]",        "HIGH", r'\+?[1-9]\d{1,3}[\s\-]\d{3}[\s\-]\d{3}[\s\-]\d{4}'),
    ("AADHAAR",      "[AADHAAR]",      "HIGH", r'\b\d{4}\s\d{4}\s\d{4}\b'),
    ("PAN",          "[PAN]",          "HIGH", r'\b[A-Z]{5}[0-9]{4}[A-Z]\b'),
    ("SSN",          "[SSN]",          "HIGH", r'\b\d{3}-\d{2}-\d{4}\b'),
    ("CREDIT CARD",  "[CARD]",         "HIGH", r'\b(?:\d[ -]?){15,16}\b'),
    ("API KEY",      "[API KEY]",      "HIGH", r'\bsk-[a-zA-Z0-9]{20,}\b'),
    ("AWS KEY",      "[AWS KEY]",      "HIGH", r'\bAKIA[0-9A-Z]{16}\b'),
    ("GITHUB TOKEN", "[GITHUB TOKEN]", "HIGH", r'\bghp_[a-zA-Z0-9]{36}\b'),
    ("CRYPTO",       "[CRYPTO]",       "HIGH", r'\b(1|3)[a-km-zA-HJ-NP-Z1-9]{25,34}\b'),
    ("ETH WALLET",   "[ETH]",          "HIGH", r'\b0x[a-fA-F0-9]{40}\b'),
    ("PASSWORD",     "[PASSWORD]",     "HIGH", r'(?i)(password|passwd|pwd)\s*[=:]\s*\S+'),
    ("URL",          "[URL]",          "LOW",  r'https?://[^\s]{10,}'),
    ("IP ADDRESS",   "[IP]",           "MED",  r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
]

MIN_VALUE_LENGTH = 5

def scan_text_regex(text, document_type="General"):
    findings = []
    seen = set()
    for ptype, replace, risk, pattern in PATTERNS:
        try:
            for match in re.finditer(pattern, text):
                value = match.group().strip()
                if len(value) < MIN_VALUE_LENGTH:
                    continue
                if value.lower() in seen:
                    continue
                seen.add(value.lower())
                findings.append({
                    "type": ptype, "value": value,
                    "replace": replace, "risk": risk,
                    "start": match.start(), "end": match.end()
                })
        except re.error:
            continue
    findings.sort(key=lambda x: x["start"])
    return findings