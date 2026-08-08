import re  # For precise text replacement

# ─────────────────────────────────────────────────────────
# TEXT REDACTOR
# This file takes the original text and a list of findings
# and replaces each sensitive value with its placeholder.
#
# Example:
# Original : "Hi I am Rohan, email me at rohan@gmail.com"
# Cleaned  : "Hi I am [NAME], email me at [EMAIL]"
#
# It also stores a mapping of placeholder → real value
# so the user can restore them later from the AI response.
# ─────────────────────────────────────────────────────────


def redact_text(original_text, findings):
    """
    Replace all checked findings in the text with placeholders.

    original_text = the full original message from the user
    findings      = list of findings the user checked to redact

    Returns:
        cleaned_text  = text with sensitive values replaced
        summary       = list of what was replaced (for summary screen)
        restore_map   = dict mapping placeholder → real value (for restore later)
    """

    cleaned_text = original_text    # Start with original, we will modify this
    summary      = []               # Track what was replaced
    restore_map  = {}               # Maps "[EMAIL_1]" → "rohan@gmail.com"

    # ── Track how many times each placeholder type is used ──
    # If there are 2 emails, they become [EMAIL_1] and [EMAIL_2]
    # so we can restore each one individually later
    type_counts = {}

    # Sort findings by position in reverse order
    # We replace from end to start so positions don't shift
    sorted_findings = sorted(findings, key=lambda x: x.get("start", 0), reverse=True)

    for finding in sorted_findings:
        value   = finding["value"]      # Real sensitive value e.g. "rohan@gmail.com"
        replace = finding["replace"]    # Base placeholder e.g. "[EMAIL]"
        ftype   = finding["type"]       # Type e.g. "EMAIL"

        # Count how many of this type we have replaced so far
        type_counts[ftype] = type_counts.get(ftype, 0) + 1
        count = type_counts[ftype]

        # Create unique placeholder e.g. [EMAIL_1], [EMAIL_2]
        # This lets us restore each one separately
        unique_placeholder = replace.replace("]", f"_{count}]")

        # Store in restore map — placeholder → real value
        restore_map[unique_placeholder] = value

        # Replace the real value with the placeholder in the text
        # Use re.sub with re.ESCAPE to handle special characters safely
        cleaned_text = re.sub(
            re.escape(value),       # Escape special chars in the value
            unique_placeholder,     # Replace with unique placeholder
            cleaned_text,
            flags=re.IGNORECASE     # Case-insensitive replacement
        )

        # Add to summary list for display
        summary.append({
            "type":        ftype,
            "original":    value,
            "replace":     unique_placeholder,
            "risk":        finding.get("risk", "LOW")
        })

    return cleaned_text, summary, restore_map


def restore_text(ai_response, restore_map):
    """
    Replace placeholders in the AI's response back with real values.

    This is the "come back and paste the AI response" feature.
    User pastes AI response → we put their real data back.

    ai_response  = text the AI tool returned (contains placeholders)
    restore_map  = dict of placeholder → real value (saved during redaction)

    Returns:
        restored_text = AI response with real values put back
        restore_summary = list of what was restored
    """

    restored_text    = ai_response  # Start with AI response
    restore_summary  = []           # Track what was restored

    # Replace each placeholder with its real value
    for placeholder, real_value in restore_map.items():
        if placeholder in restored_text:
            # Put the real value back
            restored_text = restored_text.replace(placeholder, real_value)

            # Add to summary
            restore_summary.append({
                "placeholder": placeholder,
                "real_value":  real_value
            })

    return restored_text, restore_summary


def get_redaction_stats(summary):
    """
    Get simple stats about what was redacted.
    Used to update the stats cards in the UI.

    Returns dict with counts by risk level.
    """

    stats = {"HIGH": 0, "MED": 0, "LOW": 0, "total": 0}

    for item in summary:
        risk = item.get("risk", "LOW")
        stats[risk] = stats.get(risk, 0) + 1
        stats["total"] += 1

    return stats