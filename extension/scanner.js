/**
 * scanner.js
 * PrivacyGate — Complete PII Scanner (JavaScript)
 * Runs 100% locally in browser. No network call for text scanning.
 * Must stay in sync with Python scanner/regex_scanner.py
 */

const PrivacyGateScanner = (() => {
  "use strict";

  // ─────────────────────────────────────────────────────
  // ALL PII PATTERNS
  // Format: [type, placeholder, risk, regex]
  // ─────────────────────────────────────────────────────

  const PATTERNS = [

    // ── CONTACT ──────────────────────────────────────────
    ["EMAIL",         "[EMAIL]",         "HIGH", /\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b/g],

    // Indian mobile — all formats
    ["PHONE",         "[PHONE]",         "HIGH", /(\+91|0091)[\s\-]?[6-9]\d{4}[\s\-]?\d{5}/g],
    ["PHONE",         "[PHONE]",         "HIGH", /\b(0)?[6-9]\d{4}[\s]?\d{5}\b/g],
    // International
    ["PHONE",         "[PHONE]",         "HIGH", /\+[1-9]\d{1,3}[\s\-]\d{2,5}[\s\-]\d{3,5}([\s\-]\d{2,4})?/g],
    // US format
    ["PHONE",         "[PHONE]",         "HIGH", /\b\d{3}[\s\-\.]\d{3}[\s\-\.]\d{4}\b/g],

    // ── INDIAN GOVERNMENT IDs ─────────────────────────────
    ["AADHAAR",       "[AADHAAR]",       "HIGH", /\b\d{4}\s\d{4}\s\d{4}\b/g],
    ["AADHAAR",       "[AADHAAR]",       "HIGH", /\b\d{12}\b/g],
    ["PAN",           "[PAN]",           "HIGH", /\b[A-Z]{5}[0-9]{4}[A-Z]\b/g],
    ["VOTER_ID",      "[VOTER_ID]",      "HIGH", /\b[A-Z]{3}[0-9]{7}\b/g],
    ["PASSPORT",      "[PASSPORT]",      "HIGH", /\b[A-Z]{1}[0-9]{7}\b/g],
    ["DRIVING_LIC",   "[DL]",            "HIGH", /\b[A-Z]{2}[0-9]{2}[A-Z]{1,2}[0-9]{4,7}\b/g],
    ["GST",           "[GST]",           "HIGH", /\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}\b/g],
    ["CIN",           "[CIN]",           "HIGH", /\b[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}\b/g],

    // ── GLOBAL GOVERNMENT IDs ─────────────────────────────
    ["SSN",           "[SSN]",           "HIGH", /\b\d{3}-\d{2}-\d{4}\b/g],
    ["NI_NUMBER",     "[NI]",            "HIGH", /\b[A-Z]{2}[\s]?\d{2}[\s]?\d{2}[\s]?\d{2}[\s]?[A-Z]\b/g],
    ["TAX_ID",        "[TAX_ID]",        "HIGH", /\b\d{2}-\d{7}\b/g],

    // ── FINANCIAL ────────────────────────────────────────
    ["CREDIT_CARD",   "[CARD]",          "HIGH", /\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b/g],
    ["BANK_ACCOUNT",  "[BANK_ACCT]",     "HIGH", /\b[0-9]{9,18}\b/g],
    ["IFSC",          "[IFSC]",          "HIGH", /\b[A-Z]{4}0[A-Z0-9]{6}\b/g],
    ["UPI",           "[UPI]",           "HIGH", /\b[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{2,64}\b/g],
    ["SWIFT",         "[SWIFT]",         "HIGH", /\b[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?\b/g],
    ["IBAN",          "[IBAN]",          "HIGH", /\b[A-Z]{2}[0-9]{2}[A-Z0-9]{4}[0-9]{7}([A-Z0-9]{0,16})\b/g],

    // ── CRYPTO ───────────────────────────────────────────
    ["CRYPTO_BTC",    "[CRYPTO]",        "HIGH", /\b(1|3)[a-km-zA-HJ-NP-Z1-9]{25,34}\b/g],
    ["CRYPTO_ETH",    "[ETH]",           "HIGH", /\b0x[a-fA-F0-9]{40}\b/g],

    // ── API KEYS & SECRETS ────────────────────────────────
    ["OPENAI_KEY",    "[API_KEY]",       "HIGH", /\bsk-[a-zA-Z0-9]{20,}\b/g],
    ["AWS_KEY",       "[AWS_KEY]",       "HIGH", /\bAKIA[0-9A-Z]{16}\b/g],
    ["AWS_SECRET",    "[AWS_SECRET]",    "HIGH", /\b[a-zA-Z0-9/+=]{40}\b/g],
    ["GITHUB_TOKEN",  "[GITHUB_TOKEN]",  "HIGH", /\bghp_[a-zA-Z0-9]{36}\b/g],
    ["GITHUB_OAUTH",  "[GITHUB_TOKEN]",  "HIGH", /\bgho_[a-zA-Z0-9]{36}\b/g],
    ["STRIPE_KEY",    "[STRIPE_KEY]",    "HIGH", /\bsk_live_[a-zA-Z0-9]{24,}\b/g],
    ["STRIPE_TEST",   "[STRIPE_TEST]",   "HIGH", /\bsk_test_[a-zA-Z0-9]{24,}\b/g],
    ["SLACK_TOKEN",   "[SLACK_TOKEN]",   "HIGH", /\bxox[baprs]-[a-zA-Z0-9\-]{10,}\b/g],
    ["GOOGLE_API",    "[GOOGLE_KEY]",    "HIGH", /\bAIza[0-9A-Za-z\-_]{35}\b/g],
    ["JWT",           "[JWT]",           "HIGH", /\beyJ[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+/g],
    ["PRIVATE_KEY",   "[PRIVATE_KEY]",   "HIGH", /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g],
    ["PASSWORD",      "[PASSWORD]",      "HIGH", /(?:password|passwd|pwd|pass|secret|token)\s*[=:]\s*\S+/gi],
    ["DATABASE_URL",  "[DB_URL]",        "HIGH", /(?:mongodb|postgres|mysql|redis|postgresql):\/\/[^\s"']+/gi],
    ["IP_PRIVATE",    "[IP]",            "MED",  /\b(192\.168|10\.|172\.(1[6-9]|2[0-9]|3[01]))\.\d{1,3}\.\d{1,3}\b/g],
    ["IP_ADDRESS",    "[IP]",            "MED",  /\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b/g],

    // ── SOCIAL MEDIA — ALL PLATFORMS ──────────────────────
    ["LINKEDIN",      "[LINKEDIN]",      "MED",  /(?:https?:\/\/)?(?:www\.)?linkedin\.com\/in\/[A-Za-z0-9\-_%]+\/?/gi],
    ["GITHUB",        "[GITHUB]",        "MED",  /(?:https?:\/\/)?(?:www\.)?github\.com\/[A-Za-z0-9\-_]+\/?/gi],
    ["TWITTER",       "[TWITTER]",       "MED",  /(?:https?:\/\/)?(?:www\.)?(?:twitter|x)\.com\/[A-Za-z0-9_]+\/?/gi],
    ["INSTAGRAM",     "[INSTAGRAM]",     "MED",  /(?:https?:\/\/)?(?:www\.)?instagram\.com\/[A-Za-z0-9_\.]+\/?/gi],
    ["FACEBOOK",      "[FACEBOOK]",      "MED",  /(?:https?:\/\/)?(?:www\.)?facebook\.com\/[A-Za-z0-9\.\-_]+\/?/gi],
    ["YOUTUBE",       "[YOUTUBE]",       "MED",  /(?:https?:\/\/)?(?:www\.)?youtube\.com\/(?:c\/|channel\/|user\/|@)[A-Za-z0-9\-_]+\/?/gi],
    ["TIKTOK",        "[TIKTOK]",        "MED",  /(?:https?:\/\/)?(?:www\.)?tiktok\.com\/@[A-Za-z0-9\-_.]+\/?/gi],
    ["SNAPCHAT",      "[SNAPCHAT]",      "MED",  /(?:https?:\/\/)?(?:www\.)?snapchat\.com\/add\/[A-Za-z0-9\-_.]+\/?/gi],
    ["REDDIT",        "[REDDIT]",        "MED",  /(?:https?:\/\/)?(?:www\.)?reddit\.com\/u(?:ser)?\/[A-Za-z0-9\-_]+\/?/gi],
    ["DISCORD",       "[DISCORD]",       "MED",  /(?:https?:\/\/)?(?:www\.)?discord\.(?:com|gg)\/(?:invite\/)?[A-Za-z0-9\-_]+\/?/gi],
    ["TELEGRAM",      "[TELEGRAM]",      "MED",  /(?:https?:\/\/)?(?:www\.)?t\.me\/[A-Za-z0-9_]+\/?/gi],
    ["WHATSAPP",      "[WHATSAPP]",      "MED",  /(?:https?:\/\/)?(?:www\.)?wa\.me\/[0-9]+\/?/gi],
    ["PINTEREST",     "[PINTEREST]",     "MED",  /(?:https?:\/\/)?(?:www\.)?pinterest\.com\/[A-Za-z0-9_]+\/?/gi],

    // @username mentions (Twitter, Instagram style)
    ["USERNAME",      "[USERNAME]",      "MED",  /(?<![a-zA-Z0-9])@[A-Za-z0-9_]{3,30}\b/g],

    // ── LOCATION ─────────────────────────────────────────
    ["PINCODE",       "[PINCODE]",       "MED",  /\b[1-9][0-9]{5}\b/g],
    ["ZIPCODE",       "[ZIPCODE]",       "MED",  /\b\d{5}(?:-\d{4})?\b/g],

    // ── GENERAL URL ──────────────────────────────────────
    ["URL",           "[URL]",           "LOW",  /https?:\/\/[^\s<>"]{10,}/g],
  ];

  const MIN_LEN = 4;

  // Words that are never PII
  const SAFE_WORDS = new Set([
    "i","me","my","we","us","he","she","it","they","you",
    "hi","hello","hey","thanks","okay","ok","yes","no","please",
    "the","and","for","are","was","were","this","that","with",
    "from","have","been","will","what","when","where","who","how",
    "india","usa","uk","google","microsoft","apple","amazon",
    "monday","tuesday","wednesday","thursday","friday","saturday","sunday",
  ]);

  // ─────────────────────────────────────────────────────
  // SCAN TEXT
  // ─────────────────────────────────────────────────────

  function scanText(text) {
    if (!text || text.trim().length < MIN_LEN) return [];

    const findings = [];
    const seen     = new Set();

    for (const [type, replace, risk, regex] of PATTERNS) {
      regex.lastIndex = 0;
      let match;

      while ((match = regex.exec(text)) !== null) {
        const value = match[0].trim();

        if (value.length < MIN_LEN)             continue;
        if (SAFE_WORDS.has(value.toLowerCase())) continue;
        if (seen.has(value.toLowerCase()))       continue;

        // Skip pure numbers under 6 digits (too many false positives)
        if (/^\d+$/.test(value) && value.length < 6) continue;

        seen.add(value.toLowerCase());
        findings.push({ type, value, replace, risk,
          start: match.index, end: match.index + match[0].length });
      }

      regex.lastIndex = 0;
    }

    findings.sort((a, b) => a.start - b.start);
    return findings;
  }

  // ─────────────────────────────────────────────────────
  // CLEAN TEXT
  // ─────────────────────────────────────────────────────

  function cleanText(text, findings) {
    if (!findings || findings.length === 0) return text;

    const typeCounts = {};
    const sorted = [...findings].sort((a, b) => b.start - a.start);
    let cleaned  = text;

    for (const f of sorted) {
      typeCounts[f.type] = (typeCounts[f.type] || 0) + 1;
      const placeholder  = f.replace.replace("]", `_${typeCounts[f.type]}]`);
      const escaped      = f.value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
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

  return { scanText, cleanText, riskColor };

})();