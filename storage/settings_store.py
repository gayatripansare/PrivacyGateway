import json  # For reading and writing JSON
import os    # For file path operations

# ─────────────────────────────────────────────────────────
# SETTINGS STORE
# Saves user preferences locally on their machine.
# No cloud sync — everything stays local.
#
# Settings include:
# - sensitivity level (low/medium/high)
# - hard block government IDs toggle
# - show cleaning summary toggle
# - whitelist (words never to flag)
# - theme preference (dark/light)
# ─────────────────────────────────────────────────────────

# Path to settings file — stored in same folder as the app
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "..", "settings.json")

# Default settings — used when app runs for first time
DEFAULT_SETTINGS = {
    "sensitivity":        "medium",   # low / medium / high
    "hard_block_ids":     True,       # Always block govt IDs — no Send Anyway
    "show_summary":       True,       # Show cleaning summary before sending
    "theme":              "dark",     # dark / light
    "whitelist":          [],         # Words that should never be flagged
    "default_ai_tool":    "Claude",   # Default selected AI tool
    "restore_enabled":    True,       # Enable the restore AI response feature
}


def load_settings():
    """
    Load user settings from local file.
    If file doesn't exist, returns default settings.
    """
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)

                # Merge saved settings with defaults
                # This handles new settings added in future versions
                merged = DEFAULT_SETTINGS.copy()
                merged.update(saved)
                return merged

    except (json.JSONDecodeError, IOError):
        # File corrupted or unreadable — use defaults
        pass

    return DEFAULT_SETTINGS.copy()


def save_settings(settings):
    """
    Save user settings to local file.

    settings = dict of setting key-value pairs
    """
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        return True

    except IOError as e:
        print(f"Could not save settings: {e}")
        return False


def get_setting(key):
    """
    Get a single setting value by key.
    Returns default value if key not found.
    """
    settings = load_settings()
    return settings.get(key, DEFAULT_SETTINGS.get(key))


def update_setting(key, value):
    """
    Update a single setting value and save.

    key   = setting name e.g. "theme"
    value = new value e.g. "light"
    """
    settings = load_settings()
    settings[key] = value
    return save_settings(settings)


def add_to_whitelist(word):
    """
    Add a word to the whitelist.
    Whitelisted words are never flagged as sensitive.
    """
    settings = load_settings()
    whitelist = settings.get("whitelist", [])

    # Only add if not already in whitelist
    if word.lower() not in [w.lower() for w in whitelist]:
        whitelist.append(word)
        settings["whitelist"] = whitelist
        save_settings(settings)
        return True
    return False


def remove_from_whitelist(word):
    """Remove a word from the whitelist."""
    settings = load_settings()
    whitelist = settings.get("whitelist", [])
    whitelist = [w for w in whitelist if w.lower() != word.lower()]
    settings["whitelist"] = whitelist
    save_settings(settings)


def get_whitelist():
    """Get the full whitelist."""
    return get_setting("whitelist") or []