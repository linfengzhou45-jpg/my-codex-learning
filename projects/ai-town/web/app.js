"use strict";

// The browser only displays the world. Python owns observations, decisions,
// actions and memory; advancing a round always goes through /api/step.
const $ = (id) => document.getElementById(id);
const ui = {
  step: $("step-button"), auto: $("auto-button"), reset: $("reset-button"),
  retry: $("retry-button"), error: $("error-banner"), dialog: $("reset-dialog"),
};
let state = null;
let selectedId = null;
let busy = false;
let autoRunning = false;
let autoTimer = null;
let hasError = false;
const AUTO_INTERVAL_MS = 1800;
const knownLocations = new Set(["square", "cafe", "library", "park", "homes"]);
const fallbackColors = ["#ba8167", "#809a86", "#bb9b59"];

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined && text !== null) element.textContent = String(text);
  return element;
}

function colorOf(npc, index = 0) {
  return /^#[0-9a-f]{6}$/i.test(npc.color || "") ? npc.color : fallbackColors[index % 3];
}

function avatar(npc, index = 0) {
  const element = node("span", "avatar");
  element.setAttribute("aria-hidden", "true");
  element.dataset.npc = npc.id;
  element.style.setProperty("--resident-color", colorOf(npc, index));
  return element;
}

function locationName(id) {
  return state.locations.find((place) => place.id === id)?.name || id || "未知地点";
}

function maxTicks() {
  return Math.max(1, Number(state?.max_ticks) || 24);
}

function finished() {
  return Boolean(state && (state.finished || state.tick >= maxTicks()));
}

function selectNpc(id) {
  selectedId = id;
  renderResidents();
  document.querySelectorAll(".npc-token").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.npcId === id));
  });
}

function renderLocations() {
  const fragment = document.createDocumentFragment();
  for (const place of state.locations) {
    const kind = knownLocations.has(place.id) ? place.id : "homes";
    const element = node("div", `location location-${kind}`);
    element.style.left = `${Math.min(87, Math.max(13, Number(place.x) || 50))}%`;
    element.style.top = `${Math.min(79, Math.max(17, Number(place.y) || 50))}%`;
    element.title = place.description || place.name;
    const building = node("div", "building");
    building.setAttribute("aria-hidden", "true");
    for (const part of ["body", "roof", "door", "window", "window"]) {
      building.append(node("span", `building-${part}`));
    }
    element.append(building, node("span", "location-label", place.name));
    fragment.append(element);
  }
  $("locations-layer").replaceChildren(fragment);
}

function renderMapResidents() {
  const fragment = document.createDocumentFragment();
  for (const place of state.locations) {
    const residents = state.npcs.filter((npc) => npc.location === place.id);
    if (!residents.length) continue;
    const group = node("div", "npc-group");
    group.style.left = `${Math.min(87, Math.max(13, Number(place.x) || 50))}%`;
    group.style.top = `${Math.min(88, Math.max(27, (Number(place.y) || 50) + 10))}%`;
    for (const npc of residents) {
      const button = node("button", "npc-token");
      button.type = "button";
      button.dataset.npcId = npc.id;
      button.setAttribute("aria-label", `查看${npc.name}：${place.name}，能量 ${npc.energy}`);
      button.setAttribute("aria-pressed", String(npc.id === selectedId));
      button.append(avatar(npc, state.npcs.indexOf(npc)), node("span", "npc-token-name", npc.name));
      button.addEventListener("click", () => selectNpc(npc.id));
      group.append(button);
    }
    fragment.append(group);
  }
  $("npcs-layer").replaceChildren(fragment);
}

function detailBlock(number, heading, text) {
  const block = node("section", "detail-block");
  const title = node("h4");
  title.append(node("span", "", number), document.createTextNode(heading));
  block.append(title);
  if (text !== undefined) block.append(node("p", "", text));
  return block;
}

function renderResidents() {
  // Preserve keyboard focus when clicking a resident tab replaces the list.
  const focusedNpc = document.activeElement?.closest(".resident-tab")?.dataset.npcId;
  const tabs = document.createDocumentFragment();
  state.npcs.forEach((npc, index) => {
    const button = node("button", "resident-tab");
    button.type = "button";
    button.dataset.npcId = npc.id;
    button.setAttribute("aria-pressed", String(npc.id === selectedId));
    button.setAttribute("aria-label", `查看居民${npc.name}`);
    button.append(avatar(npc, index), node("span", "", npc.name));
    button.addEventListener("click", () => selectNpc(npc.id));
    tabs.append(button);
  });
  $("resident-tabs").replaceChildren(tabs);
  if (focusedNpc) {
    [...$("resident-tabs").children].find((button) => button.dataset.npcId === focusedNpc)?.focus({ preventScroll: true });
  }
  const npc = state.npcs.find((resident) => resident.id === selectedId);
  if (!npc) return;
  const identity = node("div", "resident-identity");
  const portrait = node("div", "portrait");
  portrait.append(avatar(npc, state.npcs.indexOf(npc)));
  const identityText = node("div", "identity-text");
  identityText.append(node("h3", "", npc.name), node("p", "", npc.role));
  identityText.append(node("span", "status-pill", `${locationName(npc.location)} · ${npc.status || "等待行动"}`));
  identity.append(portrait, identityText);

  const goal = node("div", "goal-box");
  goal.append(node("span", "detail-label", "小目标"), node("p", "", npc.goal));
  const energy = Math.min(100, Math.max(0, Number(npc.energy) || 0));
  const energySection = node("div", "energy-section");
  const energyHeading = node("div", "energy-heading");
  energyHeading.append(node("span", "", "当前能量"), node("strong", "", `${energy} / 100`));
  const meter = node("div", "energy-meter");
  meter.setAttribute("role", "meter");
  meter.setAttribute("aria-label", `${npc.name}的能量`);
  meter.setAttribute("aria-valuenow", String(energy));
  meter.setAttribute("aria-valuemin", "0");
  meter.setAttribute("aria-valuemax", "100");
  const fill = node("div", `energy-fill${energy < 35 ? " low" : ""}`);
  fill.style.width = `${energy}%`;
  meter.append(fill);
  energySection.append(energyHeading, meter);

  const observation = npc.last_observation;
  const nearby = observation?.nearby?.length ? `身边有${observation.nearby.join("、")}` : "周围暂时没有其他居民";
  const observationText = observation
    ? `${observation.time}，在${locationName(observation.location)}，能量 ${observation.energy}。${nearby}。`
    : "还没有观察记录。推进一轮，看看它注意到了什么。";
  const observed = detailBlock("01", "行动前的观察", observationText);
  const decided = detailBlock("02", "为什么这样行动", npc.last_action?.reason || "等待第一次决定。规则会根据时间、地点和能量选择下一步。" );
  const acted = detailBlock("03", "刚刚执行的行动", npc.last_action ? npc.status : "还没有执行行动。");
  const memories = detailBlock("04", "最近的记忆");
  if (npc.memory?.length) {
    const list = node("ul", "memory-list");
    npc.memory.slice(-3).reverse().forEach((memory) => {
      const item = node("li");
      item.append(node("time", "", `第 ${memory.tick} 轮`), document.createTextNode(memory.text));
      list.append(item);
    });
    memories.append(list);
  } else {
    memories.append(node("p", "", "记忆还是空白的。每次行动后，这里都会留下记录。"));
  }
  $("resident-detail").replaceChildren(identity, goal, energySection, observed, decided, acted, memories);
}

function renderEvents() {
  const events = state.events || [];
  $("event-count").textContent = events.length ? `${events.length} 条记录 · 最新在上` : "等待第一段故事";
  const fragment = document.createDocumentFragment();
  if (!events.length) {
    const empty = node("div", "journal-empty");
    const pencil = node("span", "", "✎");
    pencil.setAttribute("aria-hidden", "true");
    const text = node("p", "", "新的一天，故事还没开始。");
    text.append(node("br"), node("small", "", "推进一轮，看看居民们会去哪里。"));
    empty.append(pencil, text);
    fragment.append(empty);
  }
  events.slice(-18).reverse().forEach((event) => {
    const row = node("div", "event-row");
    row.setAttribute("role", "listitem");
    const time = node("time", "event-time", event.time);
    time.title = `第 ${event.tick} 轮`;
    const dot = node("span", "event-dot");
    dot.setAttribute("aria-hidden", "true");
    const npc = state.npcs.find((resident) => resident.id === event.npc_id);
    if (npc) dot.style.setProperty("--resident-color", colorOf(npc, state.npcs.indexOf(npc)));
    const text = node("p", "event-text");
    // Server text may already include the name; keep each story readable once.
    const eventText = String(event.text || "");
    const name = String(event.npc_name || "");
    if (name && !eventText.startsWith(name)) text.append(node("strong", "", name));
    text.append(document.createTextNode(eventText));
    row.append(time, dot, text);
    fragment.append(row);
  });
  $("event-list").replaceChildren(fragment);
  if (events.length > 18) $("event-count").textContent = `${events.length} 条记录 · 显示最近 18 条`;
}

function updateControls() {
  const unavailable = !state || finished() || hasError;
  ui.step.disabled = busy || unavailable || autoRunning;
  ui.auto.disabled = !autoRunning && (busy || unavailable);
  ui.reset.disabled = busy || !state;
  ui.retry.disabled = busy;
  $("auto-label").textContent = autoRunning ? "暂停运行" : "自动运行";
  $("auto-icon").textContent = autoRunning ? "Ⅱ" : "▷";
  ui.auto.setAttribute("aria-pressed", String(autoRunning));
  let text = `每轮 30 分钟 · 最多 ${maxTicks()} 轮`;
  if (finished()) text = "本轮演示结束 · 重置可重新开始";
  else if (busy) text = "正在同步小镇状态…";
  else if (autoRunning) text = "自动运行中 · 每轮 30 分钟";
  else if (hasError) text = "连接已暂停 · 请重新连接";
  $("playback-status").textContent = text;
}

function render() {
  if (!state.npcs.some((npc) => npc.id === selectedId)) selectedId = state.npcs[0]?.id;
  $("time-label").textContent = state.time_label;
  $("round-label").textContent = `第 ${state.tick} / ${maxTicks()} 轮`;
  $("map-caption").textContent = finished() ? "今天的故事，先到这里" : state.tick === 0 ? "晨光正好，准备开始" : "平凡的一天，也有新的发现";
  $("town-map").setAttribute("aria-busy", "false");
  $("map-loading").hidden = true;
  // Keep focus on a map resident after the DOM is refreshed by a round.
  const focusedNpc = document.activeElement?.closest(".npc-token")?.dataset.npcId;
  renderLocations();
  renderMapResidents();
  renderResidents();
  renderEvents();
  if (focusedNpc) {
    [...document.querySelectorAll(".npc-token")].find((button) => button.dataset.npcId === focusedNpc)?.focus({ preventScroll: true });
  }
  $("live-status").textContent = `小镇时间 ${state.time_label}，第 ${state.tick} 轮${finished() ? "，演示已结束" : ""}。`;
}

function pause() {
  autoRunning = false;
  clearTimeout(autoTimer);
  autoTimer = null;
  updateControls();
}

async function requestState(path, method = "GET") {
  if (busy) return false;
  busy = true;
  updateControls();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const options = { method, signal: controller.signal, cache: "no-store" };
    if (method === "POST") {
      options.headers = { "Content-Type": "application/json" };
      options.body = "{}";
    }
    const response = await fetch(path, options);
    let result;
    try { result = await response.json(); }
    catch { throw new Error("服务器返回了无法读取的内容，请检查小镇服务是否正常运行。"); }
    if (!response.ok) throw new Error(result.error || `连接失败（${response.status}）`);
    if (!Array.isArray(result.locations) || !Array.isArray(result.npcs) || !Number.isInteger(result.tick)) {
      throw new Error("小镇状态格式不完整，请检查服务器输出。");
    }
    state = result;
    hasError = false;
    ui.error.hidden = true;
    if (finished()) pause();
    render();
    return true;
  } catch (error) {
    hasError = true;
    pause();
    ui.error.hidden = false;
    const detail = error.name === "AbortError"
      ? "连接超时。重新连接会读取小镇的最新状态。"
      : error.message || "无法连接小镇服务。";
    $("error-message").textContent = `${detail} 自动运行已停止。`;
    $("town-map").setAttribute("aria-busy", "false");
    if (!state) $("map-loading").textContent = "小镇暂未连接，请点击上方「重新连接」。";
    return false;
  } finally {
    clearTimeout(timeout);
    busy = false;
    updateControls();
  }
}

async function automaticStep() {
  if (!autoRunning || finished()) return;
  const success = await requestState("/api/step", "POST");
  // Schedule only after the previous request settles: slow requests never overlap.
  if (success && autoRunning && !finished()) autoTimer = setTimeout(automaticStep, AUTO_INTERVAL_MS);
}

ui.step.addEventListener("click", () => requestState("/api/step", "POST"));
ui.auto.addEventListener("click", () => {
  if (autoRunning) return pause();
  if (busy || !state || finished() || hasError) return;
  autoRunning = true;
  updateControls();
  automaticStep();
});
ui.reset.addEventListener("click", () => {
  pause();
  ui.dialog.showModal();
  $("cancel-reset").focus();
});
$("cancel-reset").addEventListener("click", () => ui.dialog.close());
$("confirm-reset").addEventListener("click", async () => {
  ui.dialog.close();
  await requestState("/api/reset", "POST");
});
ui.retry.addEventListener("click", () => requestState("/api/state"));
document.addEventListener("visibilitychange", () => {
  // A hidden tab should not silently consume the remaining learning rounds.
  if (document.hidden) pause();
});
window.addEventListener("pagehide", pause);
requestState("/api/state");
