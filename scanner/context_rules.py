# Context rules — refine findings after regex + NER

DOB_KEYWORDS = ["born","dob","date of birth","birthday","birth date","d.o.b"]
FINANCIAL_KEYWORDS = ["account","bank","ifsc","cvv","card","credit","debit","upi","balance"]
ADDRESS_KEYWORDS = ["address","home","flat","apartment","house","street","road","live","lives","pin","pincode"]

# Words that are NEVER sensitive regardless of what NER says
ALWAYS_SAFE = {
    "i","me","my","we","us","our","you","your","he","she","it","they","them","their",
    "hi","hii","hello","hey","thanks","okay","ok","yes","no","please","sorry",
    "india","usa","uk","europe","asia","america","world",
    "google","microsoft","apple","amazon","facebook","twitter",
}

def apply_context_rules(findings, text):
    updated = []
    text_lower = text.lower()

    for f in findings:
        value = f["value"]
        ftype = f["type"]

        # Hard skip — always safe words
        if value.lower() in ALWAYS_SAFE:
            continue

        # Skip anything that is just a single common word
        if len(value.split()) == 1 and len(value) < 5:
            continue

        start = f.get("start", 0)
        ctx_start = max(0, start - 60)
        ctx_end = min(len(text), start + len(value) + 60)
        context = text_lower[ctx_start:ctx_end]

        # Date — only flag if near DOB keywords
        if ftype == "DATE":
            if any(kw in context for kw in DOB_KEYWORDS):
                f["type"] = "DATE OF BIRTH"
                f["replace"] = "[DOB]"
                f["risk"] = "HIGH"
            else:
                continue  # Skip plain dates

        # Location — upgrade if near address keywords
        if ftype in ("LOCATION", "ADDRESS"):
            if any(kw in context for kw in ADDRESS_KEYWORDS):
                f["risk"] = "HIGH"

        updated.append(f)

    # Remove duplicates
    seen = set()
    final = []
    for f in updated:
        key = f["value"].lower()
        if key not in seen:
            seen.add(key)
            final.append(f)

    # Sort HIGH first
    risk_order = {"HIGH":0,"MED":1,"LOW":2}
    final.sort(key=lambda x: risk_order.get(x["risk"],2))
    return final