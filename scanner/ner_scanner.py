import spacy

try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    raise OSError("Run: python -m spacy download en_core_web_sm")

ENTITY_MAP = {
    "PERSON": ("NAME",     "[NAME]",     "MED"),
    "GPE":    ("LOCATION", "[LOCATION]", "LOW"),
    "LOC":    ("ADDRESS",  "[ADDRESS]",  "MED"),
    "MONEY":  ("FINANCIAL","[FINANCIAL]","MED"),
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

def scan_text_ner(text, document_type="General"):
    findings = []
    seen = set()
    doc = nlp(text)
    for ent in doc.ents:
        if ent.label_ not in ENTITY_MAP:
            continue
        value = ent.text.strip()
        if len(value) < MIN_ENTITY_LENGTH:
            continue
        if value.lower() in FALSE_POSITIVES:
            continue
        words = value.split()
        if len(words) == 1 and value.lower() in FALSE_POSITIVES:
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