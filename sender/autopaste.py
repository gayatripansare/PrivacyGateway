import threading                          # Run browser in background thread
from playwright.sync_api import sync_playwright  # Browser automation library

# ─────────────────────────────────────────────────────────
# AUTO PASTE
# This file opens the selected AI tool in a browser,
# navigates to its chat page, and pastes the cleaned text
# into the input box automatically.
#
# The user then reads the pasted content and clicks
# Send themselves — we never auto-submit.
#
# Uses Playwright with Chromium browser (free, by Microsoft)
# ─────────────────────────────────────────────────────────


# URLs for each supported AI tool
AI_TOOL_URLS = {
    "Claude":     "https://claude.ai/new",
    "ChatGPT":    "https://chatgpt.com/",
    "Gemini":     "https://gemini.google.com/app",
    "Copilot":    "https://copilot.microsoft.com/",
    "Perplexity": "https://www.perplexity.ai/",
    "DeepSeek":   "https://chat.deepseek.com/",
}

# CSS selectors for the chat input box on each AI tool
# These are the selectors Playwright uses to find the text box
AI_INPUT_SELECTORS = {
    "Claude":     'div[contenteditable="true"]',
    "ChatGPT":    'div[contenteditable="true"]',
    "Gemini":     'div[contenteditable="true"]',
    "Copilot":    'textarea[placeholder]',
    "Perplexity": 'textarea[placeholder]',
    "DeepSeek":   'textarea[placeholder]',
}


def send_to_ai(tool_name, cleaned_text):
    """
    Open the selected AI tool in browser and paste cleaned text.

    tool_name    = name of AI tool e.g. "Claude"
    cleaned_text = the redacted message to paste

    Runs in a background thread so the app UI stays responsive.
    """

    # Run in background thread — browser opening takes a few seconds
    thread = threading.Thread(
        target=_open_and_paste,
        args=(tool_name, cleaned_text),
        daemon=True                     # Thread closes when app closes
    )
    thread.start()


def _open_and_paste(tool_name, cleaned_text):
    """
    Internal function that actually opens the browser and pastes.
    Runs in background thread.
    """

    # Get URL for the selected tool
    url = AI_TOOL_URLS.get(tool_name)

    if not url:
        # Unknown tool — try using tool name as URL directly
        url = f"https://{tool_name.lower()}.com"

    # Get the input box selector for this tool
    selector = AI_INPUT_SELECTORS.get(tool_name, 'div[contenteditable="true"]')

    try:
        with sync_playwright() as p:

            # Try to launch Google Chrome specifically
            # Chrome is usually at one of these paths on Windows
            chrome_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                r"C:\Users\{}\AppData\Local\Google\Chrome\Application\chrome.exe".format(
                    __import__('os').environ.get('USERNAME','')
                ),
            ]

            chrome_exe = None
            for path in chrome_paths:
                if __import__('os').path.exists(path):
                    chrome_exe = path
                    break

            # Launch Chrome if found, otherwise fall back to Chromium
            if chrome_exe:
                browser = p.chromium.launch(
                    headless=False,
                    slow_mo=100,
                    executable_path=chrome_exe,  # Use Chrome specifically
                    args=["--start-maximized"]
                )
            else:
                # Chrome not found — use Playwright's Chromium
                browser = p.chromium.launch(
                    headless=False,
                    slow_mo=100,
                    args=["--start-maximized"]
                )

            # Open a new browser page
            page = browser.new_page()

            # Navigate to the AI tool URL
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Wait for the page to fully load
            page.wait_for_timeout(2000)

            # Try to find the chat input box
            try:
                # Wait for input box to appear (max 15 seconds)
                page.wait_for_selector(selector, timeout=15000)

                # Click the input box to focus it
                page.click(selector)

                # Small pause after clicking
                page.wait_for_timeout(500)

                # Type the cleaned text into the input box
                # Using keyboard.insert_text for fast paste (no character-by-character delay)
                page.keyboard.insert_text(cleaned_text)

                # Small pause so user can see what was pasted
                page.wait_for_timeout(500)

                # ── We stop here ──
                # User reads the pasted content and clicks Send themselves
                # We never auto-click Send

            except Exception as e:
                # Could not find input box — user will see the page open
                # They can paste manually
                print(f"Could not find input box for {tool_name}: {e}")

            # Keep browser open — user interacts with it
            # Browser stays open until user closes it
            # We don't call browser.close() here intentionally

    except Exception as e:
        print(f"Browser error: {e}")


def get_supported_tools():
    """Return list of all supported AI tool names."""
    return list(AI_TOOL_URLS.keys())