import json      # For reading and writing JSON data
import os        # For file path operations
import datetime  # For timestamps

# ─────────────────────────────────────────────────────────
# AUDIT LOG
# Stores a local history of every scan the user does.
# Never sent anywhere — stays on the user's machine only.
#
# Each log entry contains:
# - date and time of scan
# - what types of sensitive info were found
# - which AI tool it was sent to
# - how many items were redacted
# Does NOT store the original sensitive values themselves.
# ─────────────────────────────────────────────────────────

# Path to the audit log file — stored in same folder as the app
LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "audit_log.json")


def write_log(data):
    """
    Write one scan entry to the audit log.

    data = {
        "findings": list of findings that were redacted,
        "tool":     name of AI tool used e.g. "Claude"
    }
    """

    # Load existing log entries
    entries = _load_log()

    # Build new log entry
    entry = {
        # Timestamp of this scan
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),

        # Which AI tool was used
        "tool": data.get("tool", "Unknown"),

        # How many items were redacted
        "total_redacted": len(data.get("findings", [])),

        # What types were found (not the actual values — just types)
        # e.g. ["EMAIL", "PHONE", "NAME"]
        "types_found": list(set(
            f.get("type", "") for f in data.get("findings", [])
        )),

        # Risk breakdown
        "high_count": sum(1 for f in data.get("findings", []) if f.get("risk") == "HIGH"),
        "med_count":  sum(1 for f in data.get("findings", []) if f.get("risk") == "MED"),
        "low_count":  sum(1 for f in data.get("findings", []) if f.get("risk") == "LOW"),
    }

    # Add new entry to the top of the list (newest first)
    entries.insert(0, entry)

    # Keep only last 100 entries — avoid log growing too large
    entries = entries[:100]

    # Save back to file
    _save_log(entries)

    return entry


def read_log():
    """
    Read all audit log entries.
    Returns list of entries, newest first.
    """
    return _load_log()


def clear_log():
    """
    Clear all audit log entries.
    Called from Settings panel when user clicks Clear Log.
    """
    _save_log([])


def _load_log():
    """Load log entries from the JSON file. Returns empty list if file doesn't exist."""
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError):
        # If file is corrupted or unreadable — start fresh
        pass
    return []


def _save_log(entries):
    """Save log entries to the JSON file."""
    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
    except IOError as e:
        # If we can't write — just skip silently
        print(f"Could not save audit log: {e}")