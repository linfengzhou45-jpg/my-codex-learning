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
let activePath = null;
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

function modelMode() {
  return state?.mode === "mixed";
}

function modelBudgetExhausted() {
  const runtime = state?.model_runtime;
  return modelMode() && runtime && Number.isFinite(runtime.max_calls)
    && runtime.calls_used >= runtime.max_calls;
}

function controllerLabel(npc) {
  return npc.controller === "model" ? "模型决策" : "规则决策";
}

function renderMode() {
  const runtime = state.model_runtime;
  const modelResident = state.npcs.find((npc) => npc.controller === "model");
  $("stage-label").textContent = modelMode() ? "模型 + 规则对照" : "阶段 1 · 规则演示";
  const summary = $("mode-summary");
  if (modelMode()) {
    const modelName = runtime?.model || modelResident?.model || "待确认模型";
    summary.replaceChildren(
      document.createTextNode(`${modelResident?.name || "指定居民"}使用 ${modelName}，其他居民按规则行动。`),
      node("br"),
      node("strong", "", runtime
        ? `本次启动已发起 ${runtime.calls_used} / ${runtime.max_calls} 次模型请求（含失败）`
        : "仅手动推进，逐轮观察模型决策。")
    );
    $("lesson-label").textContent = "一次真实模型决策";
    $("lesson-heading").textContent = "模型选择了什么，世界实际发生了什么？";
    $("lesson-copy").textContent = "手动推进一轮，选中使用模型的居民，展开观察室里的模型输入和返回动作，再核对位置、精力与交谈记录。";
    $("lesson-prompt").textContent = "观察返回动作是否真正执行；调用失败会明确显示，不会改用规则冒充模型成功。";
    $("lesson-footnote").textContent = "观察输入 → 查看决策 → 核对结果";
    $("reset-description").textContent = "将清空当前行动记录和居民记忆，并重新读取 world.json。小镇时间回到起点；本次启动已使用的模型请求次数不会清零。";
  } else {
    summary.replaceChildren(document.createTextNode("当前居民按预设规则行动"), node("br"),
      node("strong", "", "尚未启用大语言模型"));
    $("lesson-label").textContent = "你的第一堂实验课";
    $("lesson-heading").textContent = "一点小改动，会带来什么变化？";
    $("lesson-copy").textContent = "修改 world.json 里一位居民的 energy（能量），再点「重置小镇」并推进一轮。";
    $("lesson-prompt").textContent = "它的下一步行动变了吗？到观察室寻找原因。";
    $("lesson-footnote").textContent = "先预测 → 再运行 → 对照结果";
    $("reset-description").textContent = "将清空当前行动记录和居民记忆，并重新读取 world.json。小镇时间回到起点。";
  }
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

function traceDisclosure(title, value) {
  const disclosure = node("details", "trace-disclosure");
  disclosure.append(node("summary", "", title));
  const content = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  disclosure.append(node("pre", "trace-content", content));
  return disclosure;
}

function modelTrace(npc) {
  const block = detailBlock("05", "模型决策记录");
  block.classList.add("model-trace");
  const decision = npc.last_decision;
  if (decision?.source !== "model") {
    block.append(node("p", "", "还没有成功执行的模型决策。手动推进一轮后，这里会显示发送内容和返回动作。"));
    return block;
  }
  block.append(node("p", "trace-model", `本次决策来源：${decision.model || npc.model || "模型"}`));
  block.append(traceDisclosure("发给模型的内容", decision.input));
  block.append(traceDisclosure("模型返回的动作", decision.action));
  const usage = decision.usage || {};
  const tokenValue = (key) => Number.isFinite(usage[key]) ? String(usage[key]) : "未提供";
  block.append(node("p", "trace-usage", `本次用量：输入 ${tokenValue("prompt_tokens")} · 输出 ${tokenValue("completion_tokens")} · 合计 ${tokenValue("total_tokens")} token`));
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
    button.setAttribute("aria-label", `查看居民${npc.name}，${controllerLabel(npc)}`);
    button.append(avatar(npc, index), node("span", "", npc.name));
    button.append(node("small", "resident-controller", npc.controller === "model" ? "模型" : "规则"));
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
  identityText.append(node("span", `controller-badge${npc.controller === "model" ? " controller-model" : ""}`,
    npc.controller === "model" ? `模型决策 · ${npc.model || state.model_runtime?.model || "待确认模型"}` : "规则决策"));
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
  const pendingDecision = npc.controller === "model"
    ? "等待第一次模型决策。模型将根据角色、目标、观察和记忆选择下一步。"
    : "等待第一次决定。规则会根据时间、地点和能量选择下一步。";
  const decided = detailBlock("02", "为什么这样行动", npc.last_action?.reason || pendingDecision);
  const acted = detailBlock("03", "刚刚执行的行动", npc.last_action ? npc.status : "还没有执行行动。");
  const memories = detailBlock("04", "最近的记忆");
  memories.classList.add("memory-block");
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
  if (npc.controller === "model") $("resident-detail").append(modelTrace(npc));
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
  ui.step.disabled = busy || unavailable || autoRunning || modelBudgetExhausted();
  ui.auto.disabled = modelMode() || (!autoRunning && (busy || unavailable));
  ui.reset.disabled = busy || !state;
  ui.retry.disabled = busy;
  $("auto-label").textContent = modelMode() ? "模型模式仅手动" : autoRunning ? "暂停运行" : "自动运行";
  $("step-label").textContent = busy && modelMode() && activePath === "/api/step" ? "等待模型决策…" : "推进一轮";
  ui.auto.title = modelMode() ? "本次练习逐轮观察模型输入和执行结果。" : "";
  $("auto-icon").textContent = autoRunning ? "Ⅱ" : "▷";
  ui.auto.setAttribute("aria-pressed", String(autoRunning));
  let text = `每轮 30 分钟 · 最多 ${maxTicks()} 轮`;
  if (finished()) text = "本轮演示结束 · 重置可重新开始";
  else if (busy) text = modelMode() && activePath === "/api/step" ? "正在等待模型回复并执行本轮行动…" : "正在同步小镇状态…";
  else if (autoRunning) text = "自动运行中 · 每轮 30 分钟";
  else if (hasError) text = "操作已暂停 · 重新连接可读取当前状态";
  else if (modelBudgetExhausted()) text = "本次启动的模型请求额度已用完 · 重置不会清零";
  else if (modelMode()) text = "每轮 30 分钟 · 每次手动推进最多发起一次模型请求";
  $("playback-status").textContent = text;
}

function render() {
  if (!state.npcs.some((npc) => npc.id === selectedId)) selectedId = state.npcs[0]?.id;
  $("time-label").textContent = state.time_label;
  $("round-label").textContent = `第 ${state.tick} / ${maxTicks()} 轮`;
  $("map-caption").textContent = finished() ? "今天的故事，先到这里" : state.tick === 0 ? "晨光正好，准备开始" : "平凡的一天，也有新的发现";
  $("town-map").setAttribute("aria-busy", "false");
  $("map-loading").hidden = true;
  renderMode();
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
  activePath = path;
  updateControls();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), modelMode() && path === "/api/step" ? 65000 : 10000);
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
    if (finished() || modelMode()) pause();
    render();
    return true;
  } catch (error) {
    hasError = true;
    pause();
    ui.error.hidden = false;
    const detail = error.name === "AbortError"
      ? "连接超时。重新连接会读取小镇的最新状态。"
      : error.message || "无法连接小镇服务。";
    $("error-message").textContent = modelMode() ? detail : `${detail} 自动运行已停止。`;
    // A rejected model request may still consume a request allowance. Refresh
    // only the state; never retry POST automatically or hide the original error.
    if (modelMode() && path === "/api/step") {
      const refreshController = new AbortController();
      const refreshTimeout = setTimeout(() => refreshController.abort(), 10000);
      try {
        const response = await fetch("/api/state", { cache: "no-store", signal: refreshController.signal });
        if (response.ok) {
          const latest = await response.json();
          if (Array.isArray(latest.locations) && Array.isArray(latest.npcs) && Number.isInteger(latest.tick)) {
            state = latest;
            render();
          }
        }
      } catch {
        // Keep the original, actionable failure message visible.
      } finally {
        clearTimeout(refreshTimeout);
      }
    }
    $("town-map").setAttribute("aria-busy", "false");
    if (!state) $("map-loading").textContent = "小镇暂未连接，请点击上方「重新连接」。";
    return false;
  } finally {
    clearTimeout(timeout);
    busy = false;
    activePath = null;
    updateControls();
  }
}

async function automaticStep() {
  if (!autoRunning || finished() || modelMode()) return;
  const success = await requestState("/api/step", "POST");
  // Schedule only after the previous request settles: slow requests never overlap.
  if (success && autoRunning && !finished()) autoTimer = setTimeout(automaticStep, AUTO_INTERVAL_MS);
}

ui.step.addEventListener("click", () => requestState("/api/step", "POST"));
ui.auto.addEventListener("click", () => {
  if (autoRunning) return pause();
  if (busy || !state || finished() || hasError || modelMode()) return;
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
