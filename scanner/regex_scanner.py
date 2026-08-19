"""
scanner/regex_scanner.py
PrivacyGate — Complete Regex PII Scanner (Python)
Must stay in sync with scanner.js (JavaScript version)
"""

import re

# Format: (type, placeholder, risk, pattern)
PATTERNS = [

    # ── CONTACT ──────────────────────────────────────────────────────────
    ("EMAIL",        "[EMAIL]",        "HIGH", r'\b[a-zA-Z0-9._%+\-]+\s*@\s*[a-zA-Z0-9.\-]+\s*\.\s*[a-zA-Z]{2,}\b'),

    # Indian mobile — all formats
    ("PHONE",        "[PHONE]",        "HIGH", r'(\+91|0091)[\s\-]?[6-9]\d{4}[\s\-]?\d{5}'),
    ("PHONE",        "[PHONE]",        "HIGH", r'\b(0)?[6-9]\d{4}[\s]?\d{5}\b'),
    # International
    ("PHONE",        "[PHONE]",        "HIGH", r'\+[1-9]\d{0,3}(?:[\s().\-]*\d){8,14}\b'),
    # OCR-tolerant international/national phone groups, including CV resumes
    ("PHONE",        "[PHONE]",        "HIGH", r'(?<!\w)(?:\(?(?:00|\+)?\d{1,3}\)?[\s.\-]*)?(?:\(?\d{2,4}\)?[\s.\-]*)?\d{3,4}[\s.\-]+\d{2,4}(?:[\s.\-]+\d{2,4})?(?!\w)'),
    # US format
    ("PHONE",        "[PHONE]",        "HIGH", r'\b\d{3}[\s\-\.]\d{3}[\s\-\.]\d{4}\b'),

    # ── INDIAN GOVERNMENT IDs ─────────────────────────────────────────────
    ("AADHAAR",      "[AADHAAR]",      "HIGH", r'\b\d{4}\s\d{4}\s\d{4}\b'),
    ("AADHAAR",      "[AADHAAR]",      "HIGH", r'\b\d{12}\b'),
    ("PAN",          "[PAN]",          "HIGH", r'\b[A-Z]{5}[0-9]{4}[A-Z]\b'),
    ("VOTER_ID",     "[VOTER_ID]",     "HIGH", r'\b[A-Z]{3}[0-9]{7}\b'),
    ("PASSPORT",     "[PASSPORT]",     "HIGH", r'\b[A-Z]{1}[0-9]{7}\b'),
    ("DRIVING_LIC",  "[DL]",           "HIGH", r'\b[A-Z]{2}[0-9]{2}[A-Z]{1,2}[0-9]{4,7}\b'),
    ("GST",          "[GST]",          "HIGH", r'\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}\b'),
    ("CIN",          "[CIN]",          "HIGH", r'\b[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}\b'),

    # ── GLOBAL GOVERNMENT IDs ─────────────────────────────────────────────
    ("SSN",          "[SSN]",          "HIGH", r'\b\d{3}-\d{2}-\d{4}\b'),
    ("NI_NUMBER",    "[NI]",           "HIGH", r'\b[A-Z]{2}[\s]?\d{2}[\s]?\d{2}[\s]?\d{2}[\s]?[A-Z]\b'),
    ("TAX_ID",       "[TAX_ID]",       "HIGH", r'\b\d{2}-\d{7}\b'),

    # ── FINANCIAL ────────────────────────────────────────────────────────
    ("CREDIT_CARD",  "[CARD]",         "HIGH", r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b'),
    ("BANK_ACCOUNT", "[BANK_ACCT]",    "HIGH", r'\b(?:account|acct|a/c|bank\s*(?:account|a/c))\s*(?:number|no\.?|#)?\s*[:\-]?\s*\d{9,18}\b'),
    ("IFSC",         "[IFSC]",         "HIGH", r'\b[A-Z]{4}0[A-Z0-9]{6}\b'),
    ("UPI",          "[UPI]",          "HIGH", r'\b[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{2,64}\b'),
    # SWIFT/BIC is intentionally context-gated below; a bare eight-letter
    # token in a resume is too ambiguous to classify safely.
    ("SWIFT",        "[SWIFT]",        "HIGH", r'\b(?:swift|bic)\s*(?:code|number|no\.?)?\s*[:#-]?\s*[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b'),
    ("IBAN",         "[IBAN]",         "HIGH", r'\b[A-Z]{2}[0-9]{2}[A-Z0-9]{4}[0-9]{7}([A-Z0-9]{0,16})\b'),

    # ── CRYPTO ───────────────────────────────────────────────────────────
    ("CRYPTO_BTC",   "[CRYPTO]",       "HIGH", r'\b(1|3)[a-km-zA-HJ-NP-Z1-9]{25,34}\b'),
    ("CRYPTO_ETH",   "[ETH]",          "HIGH", r'\b0x[a-fA-F0-9]{40}\b'),

    # ── API KEYS & SECRETS ────────────────────────────────────────────────
    ("OPENAI_KEY",   "[API_KEY]",      "HIGH", r'\bsk-[a-zA-Z0-9]{20,}\b'),
    ("AWS_KEY",      "[AWS_KEY]",      "HIGH", r'\bAKIA[0-9A-Z]{16}\b'),
    ("GITHUB_TOKEN", "[GITHUB_TOKEN]", "HIGH", r'\bghp_[a-zA-Z0-9]{36}\b'),
    ("GITHUB_OAUTH", "[GITHUB_TOKEN]", "HIGH", r'\bgho_[a-zA-Z0-9]{36}\b'),
    ("STRIPE_KEY",   "[STRIPE_KEY]",   "HIGH", r'\bsk_live_[a-zA-Z0-9]{24,}\b'),
    ("STRIPE_TEST",  "[STRIPE_TEST]",  "HIGH", r'\bsk_test_[a-zA-Z0-9]{24,}\b'),
    ("SLACK_TOKEN",  "[SLACK_TOKEN]",  "HIGH", r'\bxox[baprs]-[a-zA-Z0-9\-]{10,}\b'),
    ("GOOGLE_API",   "[GOOGLE_KEY]",   "HIGH", r'\bAIza[0-9A-Za-z\-_]{35}\b'),
    ("JWT",          "[JWT]",          "HIGH", r'eyJ[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+'),
    ("PRIVATE_KEY",  "[PRIVATE_KEY]",  "HIGH", r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----'),
    ("PASSWORD",     "[PASSWORD]",     "HIGH", r'(?:password|passwd|pwd|pass|secret|token)\s*[=:]\s*\S+'),
    ("DATABASE_URL", "[DB_URL]",       "HIGH", r'(?:mongodb|postgres|mysql|redis|postgresql)://[^\s"\']+'),
    ("IP_ADDRESS",   "[IP]",           "MED",  r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),

    # ── SOCIAL MEDIA — ALL PLATFORMS ──────────────────────────────────────
    ("LINKEDIN",     "[LINKEDIN]",     "MED",  r'(?:https?://)?(?:www\.)?linkedin\.com/in/[A-Za-z0-9\-_%]+/?'),
    ("GITHUB",       "[GITHUB]",       "MED",  r'(?:https?://)?(?:www\.)?github\.com/[A-Za-z0-9\-_]+/?'),
    ("TWITTER",      "[TWITTER]",      "MED",  r'(?:https?://)?(?:www\.)?(?:twitter|x)\.com/[A-Za-z0-9_]+/?'),
    ("INSTAGRAM",    "[INSTAGRAM]",    "MED",  r'(?:https?://)?(?:www\.)?instagram\.com/[A-Za-z0-9_\.]+/?'),
    ("FACEBOOK",     "[FACEBOOK]",     "MED",  r'(?:https?://)?(?:www\.)?facebook\.com/[A-Za-z0-9\.\-_]+/?'),
    ("YOUTUBE",      "[YOUTUBE]",      "MED",  r'(?:https?://)?(?:www\.)?youtube\.com/(?:c/|channel/|user/|@)[A-Za-z0-9\-_]+/?'),
    ("TIKTOK",       "[TIKTOK]",       "MED",  r'(?:https?://)?(?:www\.)?tiktok\.com/@[A-Za-z0-9\-_.]+/?'),
    ("SNAPCHAT",     "[SNAPCHAT]",     "MED",  r'(?:https?://)?(?:www\.)?snapchat\.com/add/[A-Za-z0-9\-_.]+/?'),
    ("REDDIT",       "[REDDIT]",       "MED",  r'(?:https?://)?(?:www\.)?reddit\.com/u(?:ser)?/[A-Za-z0-9\-_]+/?'),
    ("DISCORD",      "[DISCORD]",      "MED",  r'(?:https?://)?(?:www\.)?discord\.(?:com|gg)/(?:invite/)?[A-Za-z0-9\-_]+/?'),
    ("TELEGRAM",     "[TELEGRAM]",     "MED",  r'(?:https?://)?(?:www\.)?t\.me/[A-Za-z0-9_]+/?'),
    ("WHATSAPP",     "[WHATSAPP]",     "MED",  r'(?:https?://)?(?:www\.)?wa\.me/[0-9]+/?'),
    ("PINTEREST",    "[PINTEREST]",    "MED",  r'(?:https?://)?(?:www\.)?pinterest\.com/[A-Za-z0-9_]+/?'),
    ("USERNAME",     "[USERNAME]",     "MED",  r'(?<![a-zA-Z0-9])@[A-Za-z0-9_]{3,30}\b'),

    # ── LOCATION ─────────────────────────────────────────────────────────
    ("PINCODE",      "[PINCODE]",      "MED",  r'\b[1-9][0-9]{5}\b'),
    ("ZIPCODE",      "[ZIPCODE]",      "MED",  r'\b\d{5}(?:-\d{4})?\b'),

    # ── GENERAL URL ──────────────────────────────────────────────────────
    ("URL",          "[URL]",          "LOW",  r'https?://[^\s]{10,}'),
]

MIN_VALUE_LENGTH = 4

SAFE_WORDS = {
    "i","me","my","we","us","he","she","it","they","you",
    "hi","hello","hey","thanks","okay","ok","yes","no","please",
    "the","and","for","are","was","were","this","that","with",
    "from","have","been","will","what","when","where","who","how",
    "india","usa","uk","google","microsoft","apple","amazon",
    "monday","tuesday","wednesday","thursday","friday","saturday","sunday",
}


def scan_text_regex(text, document_type="General"):
    findings = []
    seen     = set()

    for ptype, replace, risk, pattern in PATTERNS:
        try:
            for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
                value = match.group().strip()

                if len(value) < MIN_VALUE_LENGTH:            continue
                if value.lower() in SAFE_WORDS:              continue
                if value.lower() in seen:                    continue
                # A phone must contain at least ten digits. This avoids
                # classifying resume years such as "2020 2024" as phones.
                if ptype == "PHONE" and len(re.sub(r"\D", "", value)) < 10:
                    continue
                if value.isdigit() and len(value) < 6:
                    continue

                seen.add(value.lower())
                findings.append({
                    "type":    ptype,
                    "value":   value,
                    "replace": replace,
                    "risk":    risk,
                    "start":   match.start(),
                    "end":     match.end(),
                })
        except re.error:
            continue

    # Prefer complete/high-confidence findings when one detector returns a
    # shorter span inside another, e.g. UPI inside a complete EMAIL.
    priority = {"EMAIL": 100, "PHONE": 95, "CREDIT_CARD": 90, "UPI": 70}
    findings.sort(key=lambda x: (x["start"], -(x["end"] - x["start"]), -priority.get(x["type"], 0)))
    filtered = []
    for finding in findings:
        contained = any(
            finding["start"] >= kept["start"] and finding["end"] <= kept["end"]
            and priority.get(kept["type"], 0) >= priority.get(finding["type"], 0)
            for kept in filtered
        )
        if not contained:
            filtered.append(finding)
    return filtered