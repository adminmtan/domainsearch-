// 智能域名生成器 - 前端逻辑

const STORAGE_KEY = "yuming_config";

// DOM refs
const $ = (id) => document.getElementById(id);
const $description = $("description");
const $tldList = $("tld-list");
const $minLen = $("min-len");
const $maxLen = $("max-len");
const $count = $("count");
const $generateBtn = $("generate-btn");
const $status = $("status");
const $results = $("results");
const $settingsBtn = $("settings-btn");
const $settingsModal = $("settings-modal");
const $settingsSave = $("settings-save");
const $settingsCancel = $("settings-cancel");
const $apiKey = $("api-key");
const $baseUrl = $("base-url");
const $model = $("model");

let availableTlds = [];
const selectedTlds = new Set();

// ---- Config persistence ----
function loadConfig() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const cfg = JSON.parse(raw);
    if (cfg.api_key) $apiKey.value = cfg.api_key;
    if (cfg.base_url) $baseUrl.value = cfg.base_url;
    if (cfg.model) $model.value = cfg.model;
  } catch (e) {
    console.warn("load config failed", e);
  }
}

function saveConfig() {
  const cfg = {
    api_key: $apiKey.value.trim(),
    base_url: $baseUrl.value.trim(),
    model: $model.value.trim(),
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg));
}

function getConfig() {
  return {
    api_key: $apiKey.value.trim(),
    base_url: $baseUrl.value.trim() || "https://api.openai.com/v1",
    model: $model.value.trim() || "gpt-4o-mini",
  };
}

function hasConfig() {
  return $apiKey.value.trim().length > 0;
}

// ---- TLD loading ----
async function loadTlds() {
  try {
    const resp = await fetch("/api/tlds");
    const data = await resp.json();
    availableTlds = data.tlds || [];
    // Default: select first 5
    availableTlds.slice(0, 5).forEach((t) => selectedTlds.add(t));
    renderTlds();
  } catch (e) {
    $status.textContent = "TLD 列表加载失败，请刷新页面";
    $status.classList.add("error");
  }
}

function renderTlds() {
  $tldList.innerHTML = "";
  availableTlds.forEach((tld) => {
    const chip = document.createElement("span");
    chip.className = "tld-chip" + (selectedTlds.has(tld) ? " selected" : "");
    chip.textContent = "." + tld;
    chip.addEventListener("click", () => {
      if (selectedTlds.has(tld)) selectedTlds.delete(tld);
      else selectedTlds.add(tld);
      chip.classList.toggle("selected");
    });
    $tldList.appendChild(chip);
  });
}

// ---- Generation flow ----
function setStatus(msg, type) {
  $status.textContent = msg || "";
  $status.classList.remove("error", "success");
  if (type) $status.classList.add(type);
}

async function generate() {
  const description = $description.value.trim();
  if (!description) {
    setStatus("请输入描述", "error");
    return;
  }
  if (!hasConfig()) {
    setStatus("请先在设置中填入 OpenAI API Key", "error");
    openSettings();
    return;
  }
  if (selectedTlds.size === 0) {
    setStatus("请至少选择一个 TLD 后缀", "error");
    return;
  }

  const minLen = parseInt($minLen.value, 10);
  const maxLen = parseInt($maxLen.value, 10);
  const count = parseInt($count.value, 10);

  if (isNaN(minLen) || isNaN(maxLen) || minLen > maxLen) {
    setStatus("长度范围非法", "error");
    return;
  }
  if (isNaN(count) || count < 1) {
    setStatus("数量非法", "error");
    return;
  }

  const cfg = getConfig();
  $generateBtn.disabled = true;
  $results.innerHTML = "";
  setStatus("生成中…");

  try {
    const resp = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        description,
        min_len: minLen,
        max_len: maxLen,
        tlds: Array.from(selectedTlds),
        count,
        api_key: cfg.api_key,
        base_url: cfg.base_url,
        model: cfg.model,
      }),
    });
    const data = await resp.json();
    if (!data.success) {
      setStatus(data.error || "生成失败", "error");
      return;
    }
    renderResults(data.domains, data.stats, data.warning);
    const found = data.domains.length;
    const requested = data.stats.requested || count;
    if (found < requested) {
      setStatus(`已找到 ${found} 个可注册域名（请求 ${requested} 个）。${data.warning || ""}`, "success");
    } else {
      setStatus(`已生成 ${found} 个可注册域名`, "success");
    }
  } catch (e) {
    setStatus("网络错误：" + e.message, "error");
  } finally {
    $generateBtn.disabled = false;
  }
}

function renderResults(domains, stats) {
  $results.innerHTML = "";
  if (!domains.length) {
    const empty = document.createElement("div");
    empty.className = "status";
    empty.textContent = "未找到符合要求且可注册的域名。可尝试增加 TLD 选项、放宽长度范围或调整措辞。";
    $results.appendChild(empty);
    return;
  }

  const header = document.createElement("h2");
  header.textContent = `结果（共 ${domains.length} 个）`;
  header.style.fontSize = "16px";
  header.style.margin = "0 0 12px";
  $results.appendChild(header);

  domains.forEach((d) => {
    const card = document.createElement("div");
    card.className = "domain-card";

    const head = document.createElement("div");
    head.className = "domain-card-head";
    const name = document.createElement("div");
    name.className = "domain-name";
    name.textContent = d.domain;
    const badge = document.createElement("span");
    badge.className = "badge " + (d.status === "available" ? "available" : "unknown");
    badge.textContent = d.status === "available" ? "✓ 可注册" : "? 状态未知";
    head.appendChild(name);
    head.appendChild(badge);

    const reason = document.createElement("p");
    reason.className = "domain-reason";
    reason.textContent = d.reason;

    const meta = document.createElement("div");
    meta.className = "domain-meta";
    meta.textContent = `长度：${d.length} | TLD：${d.tld}`;

    card.appendChild(head);
    card.appendChild(reason);
    card.appendChild(meta);
    $results.appendChild(card);
  });
}

// ---- Modal ----
function openSettings() {
  $settingsModal.classList.remove("hidden");
}
function hideSettings() {
  $settingsModal.classList.add("hidden");
}

// ---- Init ----
function init() {
  loadConfig();
  $settingsBtn.addEventListener("click", openSettings);
  $settingsCancel.addEventListener("click", hideSettings);
  $settingsSave.addEventListener("click", () => {
    saveConfig();
    hideSettings();
    setStatus("设置已保存", "success");
  });
  $settingsModal.addEventListener("click", (e) => {
    if (e.target === $settingsModal) hideSettings();
  });
  $generateBtn.addEventListener("click", generate);
  loadTlds();
}

init();