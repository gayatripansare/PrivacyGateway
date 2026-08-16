/**
 * background.js
 * PrivacyGate — Service Worker (Background Script)
 *
 * Handles:
 *   - Extension install/update events
 *   - Badge counter (shows PII blocked count on icon)
 *   - Communication between popup and content scripts
 */

const STORAGE_KEY    = "privacygate_enabled";
const STATS_KEY      = "privacygate_stats";
const API_BASE       = "http://127.0.0.1:8000";

// ─────────────────────────────────────────────────────
// INSTALL / UPDATE
// ─────────────────────────────────────────────────────

chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    // Set defaults on first install
    chrome.storage.local.set({
      [STORAGE_KEY]: true,
      [STATS_KEY]: {
        total_scans:       0,
        total_pii_blocked: 0,
        scans_today:       0,
        pii_today:         0,
      }
    });

    // Set badge
    chrome.action.setBadgeBackgroundColor({ color: "#00f2ff" });
    chrome.action.setBadgeText({ text: "ON" });
  }
});

// ─────────────────────────────────────────────────────
// BADGE UPDATER
// Shows total PII blocked count on extension icon
// ─────────────────────────────────────────────────────

async function updateBadge() {
  try {
    // Check if enabled
    const stored = await chrome.storage.local.get([STORAGE_KEY]);
    const enabled = stored[STORAGE_KEY] !== false;

    if (!enabled) {
      chrome.action.setBadgeBackgroundColor({ color: "#333333" });
      chrome.action.setBadgeText({ text: "OFF" });
      return;
    }

    // Try to get stats from API
    const res = await fetch(`${API_BASE}/stats`, {
      signal: AbortSignal.timeout(2000),
    });

    if (res.ok) {
      const stats = await res.json();
      const count = stats.total_pii_blocked || 0;
      const label = count > 999 ? "999+" : count > 0 ? String(count) : "ON";
      chrome.action.setBadgeBackgroundColor({ color: "#00f2ff" });
      chrome.action.setBadgeText({ text: label });
    } else {
      chrome.action.setBadgeText({ text: "ON" });
    }
  } catch {
    // Service offline — show ON (text scanning still works)
    chrome.action.setBadgeBackgroundColor({ color: "#00f2ff" });
    chrome.action.setBadgeText({ text: "ON" });
  }
}

// Update badge every 60 seconds
updateBadge();
setInterval(updateBadge, 60000);

// ─────────────────────────────────────────────────────
// MESSAGE HANDLER
// Receives messages from content.js and popup.js
// ─────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {

  if (message.type === "GET_STATS") {
    fetch(`${API_BASE}/stats`, { signal: AbortSignal.timeout(3000) })
      .then(r => r.json())
      .then(stats => sendResponse({ ok: true, stats }))
      .catch(() => sendResponse({ ok: false, stats: null }));
    return true; // async response
  }

  if (message.type === "GET_HISTORY") {
    fetch(`${API_BASE}/history?limit=20`, { signal: AbortSignal.timeout(3000) })
      .then(r => r.json())
      .then(data => sendResponse({ ok: true, records: data.records }))
      .catch(() => sendResponse({ ok: false, records: [] }));
    return true;
  }

  if (message.type === "TOGGLE_ENABLED") {
    const enabled = message.enabled;
    chrome.storage.local.set({ [STORAGE_KEY]: enabled });
    updateBadge();
    sendResponse({ ok: true });
    return true;
  }

  if (message.type === "PII_FOUND") {
    // Content script reports a scan result — update badge
    updateBadge();
    sendResponse({ ok: true });
    return true;
  }

  if (message.type === "CHECK_SERVICE") {
    fetch(`${API_BASE}/status`, { signal: AbortSignal.timeout(2000) })
      .then(r => r.json())
      .then(data => sendResponse({ ok: true, running: data.status === "running" }))
      .catch(() => sendResponse({ ok: false, running: false }));
    return true;
  }

});