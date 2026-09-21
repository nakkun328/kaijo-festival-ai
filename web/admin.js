const operationLabels = {
  transcribing: "文字起こし",
  judging: "区切り判定",
  thinking: "AI回答生成",
  synthesizing: "VOICEVOX音声生成",
};

const operationOrder = ["transcribing", "judging", "thinking", "synthesizing"];
const connection = document.querySelector("#admin-connection");
let conversationActive = false;
let dashboardTimer = null;
let dashboardInFlight = false;

function formatDuration(milliseconds) {
  if (milliseconds === null || milliseconds === undefined) return "--";
  if (milliseconds < 1000) return `${Math.round(milliseconds)}ms`;
  return `${(milliseconds / 1000).toFixed(milliseconds < 10000 ? 1 : 0)}s`;
}

function formatUptime(seconds) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours) return `${hours}時間${minutes}分`;
  return `${minutes}分${seconds % 60}秒`;
}

function setMeter(id, value) {
  const meter = document.querySelector(id);
  const percent = Number(value) || 0;
  meter.style.width = `${Math.min(100, Math.max(0, percent))}%`;
  meter.classList.toggle("warn", percent >= 70 && percent < 90);
  meter.classList.toggle("danger", percent >= 90);
}

function renderLoad(data) {
  const load = data.load;
  document.querySelector("#cpu-value").textContent = load.cpuPercent === null ? "取得不可" : `${load.cpuPercent}%`;
  document.querySelector("#memory-value").textContent = load.memoryPercent === null ? "取得不可" : `${load.memoryPercent}%`;
  document.querySelector("#memory-detail").textContent = load.memoryUsedGb === null ? "psutilを確認してください" : `${load.memoryUsedGb} / ${load.memoryTotalGb} GB`;
  document.querySelector("#process-memory").textContent = load.processMemoryMb === null ? "取得不可" : `${load.processMemoryMb} MB`;
  document.querySelector("#process-cpu").textContent = load.processCpuPercent === null ? "CPU 取得不可" : `CPU ${load.processCpuPercent}%`;
  document.querySelector("#uptime-value").textContent = formatUptime(data.uptimeSeconds);
  document.querySelector("#request-count").textContent = `リクエスト ${data.requestCount}回 / 履歴 ${data.historyMessages}件`;
  setMeter("#cpu-meter", load.cpuPercent);
  setMeter("#memory-meter", load.memoryPercent);

  const gpu = data.gpus?.[0];
  document.querySelector("#gpu-value").textContent = gpu ? `${gpu.utilizationPercent}%` : "取得不可";
  document.querySelector("#gpu-name").textContent = gpu ? gpu.name : "対応するNVIDIA GPUが見つかりません";
  document.querySelector("#gpu-temperature").textContent = gpu ? `${gpu.temperatureC}°C` : "取得不可";
  document.querySelector("#gpu-temperature-state").textContent = gpu ? (gpu.temperatureC >= 85 ? "高温" : gpu.temperatureC >= 75 ? "やや高め" : "正常") : "--";
  document.querySelector("#vram-value").textContent = gpu ? `${(gpu.memoryUsedMb / 1024).toFixed(1)} GB` : "取得不可";
  document.querySelector("#vram-detail").textContent = gpu ? `${Math.round(gpu.memoryUsedMb)} / ${Math.round(gpu.memoryTotalMb)} MB（${gpu.memoryPercent}%）` : "--";
  setMeter("#gpu-meter", gpu?.utilizationPercent);
  setMeter("#gpu-temperature-meter", gpu?.temperatureC);
  setMeter("#vram-meter", gpu?.memoryPercent);
}

function renderServices(services) {
  const entries = Object.values(services);
  document.querySelector("#service-summary").textContent = `${entries.filter((item) => item.ready).length} / ${entries.length} 稼働`;
  const list = document.querySelector("#service-list");
  list.replaceChildren(...entries.map((service) => {
    const item = document.createElement("div");
    item.className = `service-item${service.ready ? " ready" : ""}`;
    const dot = document.createElement("i");
    dot.className = "service-dot";
    const label = document.createElement("b");
    label.textContent = service.label;
    const detail = document.createElement("small");
    detail.textContent = service.detail || (service.ready ? "稼働中" : "停止中");
    item.append(dot, label, detail);
    return item;
  }));
}

function renderOperations(operations) {
  const rows = document.querySelector("#operation-rows");
  rows.replaceChildren(...operationOrder.map((name) => {
    const operation = operations[name] || { count: 0, errors: 0, active: 0, latestMs: null, averageMs: null, maxMs: null };
    const row = document.createElement("tr");
    const state = operation.active ? '<span class="operation-state active"><i></i>処理中</span>' : '<span class="operation-state"><i></i>待機</span>';
    row.innerHTML = `<td>${operationLabels[name]}</td><td>${state}</td><td>${operation.count}</td><td>${formatDuration(operation.latestMs)}</td><td>${formatDuration(operation.averageMs)}</td><td>${formatDuration(operation.maxMs)}</td><td>${operation.errors}</td>`;
    return row;
  }));
}

async function updateDashboard() {
  if (dashboardInFlight) return;
  dashboardInFlight = true;
  try {
    const response = await fetch("/api/admin", { cache: "no-store" });
    if (!response.ok) throw new Error("管理情報を取得できません");
    const data = await response.json();
    renderLoad(data);
    renderServices(data.services);
    renderOperations(data.operations);
    conversationActive = Boolean(data.conversationActive);
    connection.classList.add("ready");
    connection.querySelector("span").textContent = conversationActive ? "会話中 / 1秒更新" : "待機 / 5秒更新";
  } catch {
    connection.classList.remove("ready");
    connection.querySelector("span").textContent = "接続停止";
  } finally {
    dashboardInFlight = false;
    clearTimeout(dashboardTimer);
    dashboardTimer = setTimeout(updateDashboard, conversationActive ? 1000 : 5000);
  }
}

async function detectConversationStart() {
  if (conversationActive || dashboardInFlight) return;
  try {
    const response = await fetch("/api/admin/activity", { cache: "no-store" });
    if (!response.ok) return;
    const data = await response.json();
    if (data.conversationActive) {
      conversationActive = true;
      clearTimeout(dashboardTimer);
      updateDashboard();
    }
  } catch {}
}

updateDashboard();
setInterval(detectConversationStart, 1000);
