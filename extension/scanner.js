/**
 * scanner.js
 * PrivacyGate — Client-side PII scanner (JavaScript)
 *
 * Runs 100% locally inside the browser extension.
 * No network call needed for text scanning.
 * Loaded before content.js on every page.
 */

const PrivacyGateScanner = (() => {

  // ─────────────────────────────────────────────────────
  // PII PATTERNS
  // Each pattern: [type, placeholder, risk, regex]
  // ─────────────────────────────────────────────────────

  const PATTERNS = [
    // High risk — structured identifiers
    ["EMAIL",        "[EMAIL]",        "HIGH", /\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b/g],

    // Indian mobile: +91 98765 43210 / +91-9876543210 / 09876543210 / 9876543210
    ["PHONE",        "[PHONE]",        "HIGH", /(\+91|0091|0)[\s\-]?[6-9]\d{4}[\s\-]?\d{5}/g],
    // Indian without country code: 9876543210 or 98765 43210
    ["PHONE",        "[PHONE]",        "HIGH", /\b[6-9]\d{4}[\s]?\d{5}\b/g],
    // International: +1 800 555 1234 / +44 7911 123456
    ["PHONE",        "[PHONE]",        "HIGH", /\+[1-9]\d{1,3}[\s\-]\d{3,5}[\s\-]\d{3,5}([\s\-]\d{2,4})?/g],
    ["AADHAAR",      "[AADHAAR]",      "HIGH", /\b\d{4}\s\d{4}\s\d{4}\b/g],
    ["PAN",          "[PAN]",          "HIGH", /\b[A-Z]{5}[0-9]{4}[A-Z]\b/g],
    ["SSN",          "[SSN]",          "HIGH", /\b\d{3}-\d{2}-\d{4}\b/g],
    ["CREDIT_CARD",  "[CARD]",         "HIGH", /\b(?:\d[ \-]?){15,16}\b/g],
    ["PASSPORT",     "[PASSPORT]",     "HIGH", /\b[A-Z]{1,2}[0-9]{6,9}\b/g],
    ["API_KEY",      "[API_KEY]",      "HIGH", /\bsk-[a-zA-Z0-9]{20,}\b/g],
    ["AWS_KEY",      "[AWS_KEY]",      "HIGH", /\bAKIA[0-9A-Z]{16}\b/g],
    ["GITHUB_TOKEN", "[GITHUB_TOKEN]", "HIGH", /\bghp_[a-zA-Z0-9]{36}\b/g],
    ["CRYPTO",       "[CRYPTO]",       "HIGH", /\b(1|3)[a-km-zA-HJ-NP-Z1-9]{25,34}\b/g],
    ["ETH_WALLET",   "[ETH]",          "HIGH", /\b0x[a-fA-F0-9]{40}\b/g],
    ["PASSWORD",     "[PASSWORD]",     "HIGH", /(?:password|passwd|pwd)\s*[=:]\s*\S+/gi],
    ["PRIVATE_KEY",  "[PRIVATE_KEY]",  "HIGH", /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g],

    // Medium risk
    ["IP_ADDRESS",   "[IP]",           "MED",  /\b(?:\d{1,3}\.){3}\d{1,3}\b/g],
    ["LINKEDIN",     "[LINKEDIN]",     "MED",  /(?:https?:\/\/)?(?:www\.)?linkedin\.com\/in\/[A-Za-z0-9\-_%]+\/?/gi],
    ["GITHUB",       "[GITHUB]",       "MED",  /(?:https?:\/\/)?(?:www\.)?github\.com\/[A-Za-z0-9\-_]+\/?/gi],

    // Low risk
    ["URL",          "[URL]",          "LOW",  /https?:\/\/[^\s]{10,}/g],
  ];

  const MIN_VALUE_LENGTH = 5;

  // ─────────────────────────────────────────────────────
  // SCAN TEXT
  // Returns array of finding objects
  // ─────────────────────────────────────────────────────

  function scanText(text) {
    if (!text || text.trim().length < MIN_VALUE_LENGTH) return [];

    const findings = [];
    const seen     = new Set();

    for (const [type, replace, risk, regex] of PATTERNS) {
      // Reset lastIndex for global regexes
      regex.lastIndex = 0;
      let match;

      while ((match = regex.exec(text)) !== null) {
        const value = match[0].trim();

        if (value.length < MIN_VALUE_LENGTH) continue;
        if (seen.has(value.toLowerCase()))    continue;

        seen.add(value.toLowerCase());
        findings.push({
          type,
          value,
          replace,
          risk,
          start: match.index,
          end:   match.index + match[0].length,
        });
      }

      // Reset after use
      regex.lastIndex = 0;
    }

    // Sort by position in text
    findings.sort((a, b) => a.start - b.start);
    return findings;
  }

  // ─────────────────────────────────────────────────────
  // CLEAN TEXT
  // Applies findings to text, returns cleaned string
  // ─────────────────────────────────────────────────────

  function cleanText(text, findings) {
    if (!findings || findings.length === 0) return text;

    // Count by type for unique placeholders
    const typeCounts = {};
    let cleaned = text;

    // Replace from end to start so positions don't shift
    const sorted = [...findings].sort((a, b) => b.start - a.start);

    for (const f of sorted) {
      typeCounts[f.type] = (typeCounts[f.type] || 0) + 1;
      const placeholder = f.replace.replace("]", `_${typeCounts[f.type]}]`);
      const escaped = f.value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      cleaned = cleaned.replace(new RegExp(escaped, "gi"), placeholder);
    }

    return cleaned;
  }

  // ─────────────────────────────────────────────────────
  // RISK COLOR
  // ─────────────────────────────────────────────────────

  function riskColor(risk) {
    if (risk === "HIGH") return "#ff4444";
    if (risk === "MED")  return "#ff9900";
    return "#00cc88";
  }

  // ─────────────────────────────────────────────────────
  // PUBLIC API
  // ─────────────────────────────────────────────────────

  return { scanText, cleanText, riskColor, PATTERNS };

})();