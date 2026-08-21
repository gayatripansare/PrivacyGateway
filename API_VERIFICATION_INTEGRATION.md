from fastapi.responses import FileResponse
from verification import verify_cleaned_file

verification = verify_cleaned_file(
    original_path=str(source_path),
    cleaned_path=str(cleaned_path),
    original_findings=findings,
)

headers = {
    "X-PrivacyGate-State": verification["state"],
    "X-PrivacyGate-Reason": verification["reason"],
    "X-PrivacyGate-Original-Hash": verification["original_sha256"],
    "X-PrivacyGate-Cleaned-Hash": verification["cleaned_sha256"],
    "X-PrivacyGate-Remaining-PII": json.dumps(verification["remaining_pii"]),
    "X-Findings-Count": str(len(findings)),
    "X-Findings-Summary": json.dumps(findings),
}

if verification["state"] != "verified":
    # Do not return the file as a usable clean result. The extension will
    # block automatic upload. You may return JSON 422 instead if preferred.
    headers["X-PrivacyGate-State"] = verification["state"]

return FileResponse(
    path=str(cleaned_path),
    filename=original_filename,
    media_type=detected_media_type,
    headers=headers,
)