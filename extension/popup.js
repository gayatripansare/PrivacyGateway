const STORAGE_KEY = "privacygate_enabled";

document.addEventListener("DOMContentLoaded", () => {
  loadToggleState();
  checkService();
  loadStats();
  loadHistory();

  document.getElementById("main-toggle").addEventListener("change", (e) => {
    const enabled = e.target.checked;
    document.getElementById("toggle-label").textContent = enabled ? "ON" : "OFF";
    chrome.runtime.sendMessage({ type: "TOGGLE_ENABLED", enabled });
  });

  // Tab clicks — moved from inline onclick to here (CSP fix)
  document.getElementById("tab-history").addEventListener("click", () => showTab("history"));
  document.getElementById("tab-types").addEventListener("click",   () => showTab("types"));
});

function loadToggleState() {
  chrome.storage.local.get([STORAGE_KEY], (res) => {
    const enabled = res[STORAGE_KEY] !== false;
    document.getElementById("main-toggle").checked = enabled;
    document.getElementById("toggle-label").textContent = enabled ? "ON" : "OFF";
  });
}

function checkService() {
  const dot  = document.getElementById("status-dot");
  const text = document.getElementById("status-text");
  chrome.runtime.sendMessage({ type: "CHECK_SERVICE" }, (res) => {
    if (res && res.running) {
      dot.className    = "status-dot online";
      text.textContent = "Service running — file scanning active";
      text.style.color = "#00cc88";
    } else {
      dot.className    = "status-dot offline";
      text.textContent = "Service offline — text scanning only";
      text.style.color = "#ff9900";
    }
  });
}

function loadStats() {
  chrome.runtime.sendMessage({ type: "GET_STATS" }, (res) => {
    if (!res || !res.ok || !res.stats) { setStats(null); return; }
    setStats(res.stats);
  });
}

function setStats(stats) {
  if (!stats) {
    ["stat-total-scans","stat-total-pii","stat-today-scans","stat-today-pii"]
      .forEach(id => { document.getElementById(id).textContent = "0"; });
    return;
  }
  document.getElementById("stat-total-scans").textContent = fmt(stats.total_scans);
  document.getElementById("stat-total-pii").textContent   = fmt(stats.total_pii_blocked);
  document.getElementById("stat-today-scans").textContent = fmt(stats.scans_today);
  document.getElementById("stat-today-pii").textContent   = fmt(stats.pii_today);

  const total = (stats.total_high||0) + (stats.total_med||0) + (stats.total_low||0);
  setBar("high", stats.total_high||0, total);
  setBar("med",  stats.total_med ||0, total);
  setBar("low",  stats.total_low ||0, total);

  if (stats.type_breakdown) renderTypeList(stats.type_breakdown);
}

function setBar(name, count, total) {
  const pct = total > 0 ? Math.round((count/total)*100) : 0;
  document.getElementById(`bar-${name}`).style.width     = `${pct}%`;
  document.getElementById(`count-${name}`).textContent   = fmt(count);
}

function loadHistory() {
  chrome.runtime.sendMessage({ type: "GET_HISTORY" }, (res) => {
    const list = document.getElementById("history-list");
    if (!res || !res.ok || !res.records || res.records.length === 0) {
      list.innerHTML = `<div class="empty">No scans yet.<br>Paste text or upload a file to get started.</div>`;
      return;
    }
    list.innerHTML = res.records.map(r => {
      const source = r.file_name || (r.source === "text" ? "Text paste" : "Unknown");
      const time   = formatTime(r.timestamp);
      const count  = r.findings_count;
      const color  = r.high_count>0 ? "#ff4444" : r.med_count>0 ? "#ff9900" : "#00cc88";
      return `
        <div class="history-item">
          <div class="history-left">
            <div class="history-source" title="${escHtml(source)}">
              ${r.source==="file"?"📄 ":"📝 "}${escHtml(source)}
            </div>
            <div class="history-time">${time}</div>
          </div>
          <div class="history-count" style="color:${count>0?color:"#333"}">
            ${count>0?`${count} PII`:"✓ Clean"}
          </div>
        </div>`;
    }).join("");
  });
}

function renderTypeList(typeBreakdown) {
  const list    = document.getElementById("type-list");
  const entries = Object.entries(typeBreakdown).sort((a,b) => b[1]-a[1]);
  if (entries.length === 0) {
    list.innerHTML = `<div class="empty">No PII types detected yet.</div>`;
    return;
  }
  list.innerHTML = entries.map(([type, count]) => `
    <div class="type-item">
      <span class="type-name">${escHtml(type)}</span>
      <span class="type-count">${fmt(count)}</span>
    </div>`).join("");
}

function showTab(tab) {
  document.getElementById("panel-history").style.display = tab==="history" ? "block" : "none";
  document.getElementById("panel-types").style.display   = tab==="types"   ? "block" : "none";
  document.getElementById("tab-history").className = "tab" + (tab==="history" ? " active" : "");
  document.getElementById("tab-types").className   = "tab" + (tab==="types"   ? " active" : "");
}

function fmt(n) {
  if (!n && n!==0) return "0";
  if (n>=1000000) return (n/1000000).toFixed(1)+"M";
  if (n>=1000)    return (n/1000).toFixed(1)+"K";
  return String(n);
}

function formatTime(ts) {
  if (!ts) return "";
  try {
    const d    = new Date(ts);
    const diff = Math.floor((new Date()-d)/1000);
    if (diff<60)    return "just now";
    if (diff<3600)  return `${Math.floor(diff/60)}m ago`;
    if (diff<86400) return `${Math.floor(diff/3600)}h ago`;
    return d.toLocaleDateString();
  } catch { return ts; }
}

function escHtml(str) {
  return String(str)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}