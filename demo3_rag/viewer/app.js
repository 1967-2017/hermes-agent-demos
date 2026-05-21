const state = {
  scenarios: [],
  sessions: [],
  eventSource: null,
  running: false,
  currentTraceName: "",
  stats: {
    evidence: "-",
    chunks: "-",
    docs: "-",
    tools: 0,
    errors: 0,
  },
};

const MANUAL_TRACE_NAME = "demo3-manual.json";

const els = {
  refreshButton: document.getElementById("refreshButton"),
  scenarioList: document.getElementById("scenarioList"),
  sessionStatus: document.getElementById("sessionStatus"),
  traceList: document.getElementById("traceList"),
  traceTitle: document.getElementById("traceTitle"),
  traceSubtitle: document.getElementById("traceSubtitle"),
  statusBadge: document.getElementById("statusBadge"),
  askForm: document.getElementById("askForm"),
  questionInput: document.getElementById("questionInput"),
  scenarioSelect: document.getElementById("scenarioSelect"),
  runButton: document.getElementById("runButton"),
  statEvidence: document.getElementById("statEvidence"),
  statChunks: document.getElementById("statChunks"),
  statDocs: document.getElementById("statDocs"),
  statTools: document.getElementById("statTools"),
  statErrors: document.getElementById("statErrors"),
  answerMeta: document.getElementById("answerMeta"),
  answerView: document.getElementById("answerView"),
  eventMeta: document.getElementById("eventMeta"),
  eventStream: document.getElementById("eventStream"),
  chunkMeta: document.getElementById("chunkMeta"),
  chunkList: document.getElementById("chunkList"),
  docMeta: document.getElementById("docMeta"),
  docList: document.getElementById("docList"),
  rawMeta: document.getElementById("rawMeta"),
  rawTrace: document.getElementById("rawTrace"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDate(value) {
  if (!value) return "-";
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("zh-CN");
}

function setStatus(text, kind = "neutral") {
  els.statusBadge.className = `status-badge ${kind}`;
  els.statusBadge.textContent = text;
}

function renderStats() {
  els.statEvidence.textContent = state.stats.evidence || "-";
  els.statChunks.textContent = String(state.stats.chunks ?? "-");
  els.statDocs.textContent = String(state.stats.docs ?? "-");
  els.statTools.textContent = String(state.stats.tools);
  els.statErrors.textContent = String(state.stats.errors);
}

async function fetchJson(url) {
  const response = await fetch(`${url}${url.includes("?") ? "&" : "?"}_=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
  return response.json();
}

async function refreshAll() {
  try {
    const [scenarioPayload, tracePayload] = await Promise.all([
      fetchJson("/api/scenarios"),
      fetchJson("/api/traces"),
    ]);
    state.scenarios = scenarioPayload.scenarios || [];
    state.sessions = tracePayload.sessions || [];
    renderScenarios();
    renderTraces();
    els.sessionStatus.textContent = state.sessions.length ? `${state.sessions.length} 个 trace` : "暂无 trace";
    if (!state.currentTraceName) {
      const defaultTrace = state.sessions.find((item) => item.name === MANUAL_TRACE_NAME) || state.sessions[0];
      if (defaultTrace) {
        await loadTrace(defaultTrace.name);
      }
    }
  } catch (error) {
    setStatus("读取失败", "error");
    els.eventStream.innerHTML = `<div class="error-state">${escapeHtml(error.message || error)}</div>`;
  }
}

function renderScenarios() {
  els.scenarioSelect.innerHTML = '<option value="">自由输入</option>' + state.scenarios
    .map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.id)} · ${escapeHtml(item.name)}</option>`)
    .join("");
  els.scenarioList.innerHTML = state.scenarios.length ? state.scenarios
    .map((item) => `
      <button class="side-card" type="button" data-scenario="${escapeHtml(item.id)}">
        <strong>${escapeHtml(item.id)}</strong>
        <span>${escapeHtml(item.name)}</span>
        <small>${escapeHtml(item.category)} · ${escapeHtml(item.expected_behavior)}</small>
      </button>
    `)
    .join("") : '<div class="empty-state compact">暂无场景</div>';
  els.scenarioList.querySelectorAll("[data-scenario]").forEach((button) => {
    button.addEventListener("click", () => selectScenario(button.dataset.scenario));
  });
}

function renderTraces() {
  els.traceList.innerHTML = state.sessions.length ? state.sessions
    .map((session) => {
      const active = session.name === state.currentTraceName ? " active" : "";
      return `
        <button class="side-card${active}" type="button" data-trace="${escapeHtml(session.name)}">
          <strong>${escapeHtml(session.name)}</strong>
          <span>${escapeHtml(session.user_input || session.scenario_id || "-")}</span>
          <small>${escapeHtml(session.evidence_status || session.status)} · ${escapeHtml(formatDate(session.mtime))}</small>
        </button>
      `;
    })
    .join("") : '<div class="empty-state compact">暂无 trace</div>';
  els.traceList.querySelectorAll("[data-trace]").forEach((button) => {
    button.addEventListener("click", () => loadTrace(button.dataset.trace));
  });
}

function selectScenario(scenarioId) {
  const scenario = state.scenarios.find((item) => item.id === scenarioId);
  if (!scenario) return;
  els.scenarioSelect.value = scenario.id;
  els.questionInput.value = scenario.question;
  els.traceTitle.textContent = scenario.name;
  els.traceSubtitle.textContent = scenario.question;
}

async function loadTrace(name) {
  try {
    const payload = await fetchJson(`/api/traces/${encodeURIComponent(name)}`);
    state.currentTraceName = name;
    renderTrace(payload.trace, payload.session);
    renderTraces();
    setStatus("已读取", payload.session.status === "warning" ? "warning" : "final");
  } catch (error) {
    setStatus("读取失败", "error");
    els.eventStream.innerHTML = `<div class="error-state">${escapeHtml(error.message || error)}</div>`;
  }
}

function renderTrace(trace, session = {}) {
  const toolResult = lastToolResult(trace);
  const chunks = toolResult.chunks || [];
  const sourceDocuments = toolResult.source_documents || [];
  const parseErrors = (trace.steps || []).filter((step) => step.tool_call_parse_error).length;
  const toolCalls = (trace.steps || []).reduce((count, step) => count + (step.tool_calls || []).length, 0);
  state.stats = {
    evidence: toolResult.evidence_status || session.evidence_status || "-",
    chunks: chunks.length || session.returned || 0,
    docs: sourceDocuments.length || toolResult.returned_documents || 0,
    tools: toolCalls,
    errors: parseErrors,
  };
  renderStats();
  els.traceTitle.textContent = session.name || trace.scenario_id || "Demo3 文档问答";
  els.traceSubtitle.textContent = trace.user_input || "";
  els.answerMeta.textContent = trace.final_answer ? `完成于 ${formatDate(trace.timestamp)}` : "暂无最终回答";
  els.answerView.className = trace.final_answer ? "answer-view" : "answer-view empty-state";
  els.answerView.innerHTML = trace.final_answer ? renderAnswer(trace.final_answer) : "暂无回答";
  renderChunks(chunks);
  renderSourceDocuments(sourceDocuments);
  renderTraceEvents(trace);
  els.rawMeta.textContent = session.name || "当前运行 trace";
  els.rawTrace.textContent = JSON.stringify(trace, null, 2);
}

function lastToolResult(trace) {
  for (const step of [...(trace.steps || [])].reverse()) {
    const results = step.tool_results || [];
    if (results.length) return results[results.length - 1].content || {};
  }
  return {};
}

function renderTraceEvents(trace) {
  const events = [];
  (trace.steps || []).forEach((step, index) => {
    if (step.tool_call_parse_error) {
      events.push({
        kind: "warning",
        title: `Step ${index + 1} · tool_call 解析失败`,
        body: step.tool_call_parse_error.message,
        details: step.assistant_text,
      });
    }
    (step.tool_calls || []).forEach((call) => events.push({
      kind: "tool",
      title: `Step ${index + 1} · ${call.name}`,
      body: JSON.stringify(call.arguments, null, 2),
    }));
    (step.tool_results || []).forEach((result) => events.push({
      kind: "result",
      title: `Step ${index + 1} · 检索结果`,
      body: `${result.content?.evidence_status || "-"} · ${result.content?.returned || 0} chunks · ${result.content?.returned_documents || 0} docs`,
      details: JSON.stringify(result.content, null, 2),
    }));
  });
  if (trace.final_answer) {
    events.push({ kind: "final", title: "最终回答", body: trace.final_answer });
  }
  els.eventStream.innerHTML = events.length ? events.map(renderEvent).join("") : '<div class="empty-state compact">暂无事件</div>';
}

function renderAnswer(text) {
  const escaped = escapeHtml(text).replace(/\n/g, "<br>");
  return escaped.replace(/\[([^:\[\]]+:c\d{3})\]/g, '<span class="citation">[$1]</span>');
}

function renderChunks(chunks) {
  els.chunkMeta.textContent = chunks.length ? `${chunks.length} 个 chunks` : "暂无证据";
  els.chunkList.className = chunks.length ? "chunk-list" : "chunk-list empty-state";
  els.chunkList.innerHTML = chunks.length ? chunks.map((chunk, index) => `
    <article class="chunk-card">
      <div class="chunk-head">
        <strong>#${index + 1} ${escapeHtml(chunk.doc_id)}:${escapeHtml(chunk.chunk_id)}</strong>
        <span>${escapeHtml(scoreText(chunk.score))}</span>
      </div>
      <div class="chunk-meta">
        <span>${escapeHtml(chunk.title || "-")}</span>
        <span>${escapeHtml(chunk.section || "-")}</span>
        <span>${escapeHtml((chunk.retrieval_sources || []).join(", ") || "-")}</span>
      </div>
      <p>${escapeHtml(chunk.content || "")}</p>
    </article>
  `).join("") : "暂无证据";
}

function renderSourceDocuments(documents) {
  els.docMeta.textContent = documents.length ? `${documents.length} 篇文档` : "暂无文档";
  els.docList.className = documents.length ? "document-list" : "document-list empty-state";
  els.docList.innerHTML = documents.length ? documents.map((document, index) => `
    <article class="document-card">
      <div class="chunk-head">
        <strong>#${index + 1} ${escapeHtml(document.doc_id)}</strong>
        <span>${escapeHtml((document.matched_chunks || []).map((chunk) => chunk.chunk_id).join(", ") || "-")}</span>
      </div>
      <div class="chunk-meta">
        <span>${escapeHtml(document.title || "-")}</span>
        <span>${escapeHtml(document.category || "-")}</span>
        <span>${escapeHtml(document.source_path || "-")}</span>
      </div>
      <p>${escapeHtml(document.content || "")}</p>
    </article>
  `).join("") : "暂无文档";
}

function scoreText(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(4) : "-";
}

function renderEvent(item) {
  const details = item.details ? `
    <details>
      <summary>查看详情</summary>
      <pre>${escapeHtml(item.details)}</pre>
    </details>
  ` : "";
  return `
    <article class="event-card ${escapeHtml(item.kind)}">
      <div class="event-title">
        <strong>${escapeHtml(item.title)}</strong>
        <span>${escapeHtml(item.kind)}</span>
      </div>
      <p>${escapeHtml(item.body || "")}</p>
      ${details}
    </article>
  `;
}

function resetRunView() {
  state.stats = { evidence: "-", chunks: "-", docs: "-", tools: 0, errors: 0 };
  renderStats();
  els.eventStream.innerHTML = "";
  els.answerView.className = "answer-view empty-state";
  els.answerView.textContent = "运行中";
  els.answerMeta.textContent = "等待最终回答";
  els.chunkList.className = "chunk-list empty-state";
  els.chunkList.textContent = "等待检索结果";
  els.docList.className = "document-list empty-state";
  els.docList.textContent = "等待命中文档";
  els.rawTrace.textContent = "{}";
}

function appendLiveEvent(kind, title, body, details = "") {
  if (!els.eventStream.children.length) els.eventStream.innerHTML = "";
  els.eventStream.insertAdjacentHTML("beforeend", renderEvent({ kind, title, body, details }));
  els.eventStream.scrollTop = els.eventStream.scrollHeight;
}

function startRun() {
  if (state.running) return;
  const question = els.questionInput.value.trim();
  const selectedScenario = state.scenarios.find((item) => item.id === els.scenarioSelect.value);
  const scenario = selectedScenario && selectedScenario.question === question ? selectedScenario.id : "";
  if (!scenario && !question) {
    setStatus("请输入问题", "warning");
    return;
  }
  resetRunView();
  setRunning(true);
  setStatus("运行中", "partial");
  const params = new URLSearchParams();
  if (scenario) params.set("scenario", scenario);
  else params.set("input", question);
  const source = new EventSource(`/api/run-stream?${params.toString()}`);
  state.eventSource = source;

  source.addEventListener("session_start", (event) => {
    const payload = JSON.parse(event.data);
    els.traceTitle.textContent = payload.scenario_id === "manual" ? MANUAL_TRACE_NAME : (payload.scenario_id || "自由输入");
    els.traceSubtitle.textContent = payload.user_input;
  });
  source.addEventListener("assistant_text", (event) => {
    const payload = JSON.parse(event.data);
    appendLiveEvent("assistant", `Step ${payload.step_index + 1} · 模型输出`, payload.text);
  });
  source.addEventListener("tool_call_error", (event) => {
    const payload = JSON.parse(event.data);
    state.stats.errors += 1;
    renderStats();
    appendLiveEvent("warning", `Step ${payload.step_index + 1} · 解析失败`, payload.message, payload.assistant_text);
  });
  source.addEventListener("tool_call", (event) => {
    const payload = JSON.parse(event.data);
    state.stats.tools += 1;
    renderStats();
    appendLiveEvent("tool", `Step ${payload.step_index + 1} · ${payload.name}`, JSON.stringify(payload.arguments, null, 2));
  });
  source.addEventListener("tool_result", (event) => {
    const payload = JSON.parse(event.data);
    const content = payload.content || {};
    state.stats.evidence = content.evidence_status || "-";
    state.stats.chunks = content.returned ?? (content.chunks || []).length;
    state.stats.docs = content.returned_documents ?? (content.source_documents || []).length;
    renderStats();
    renderChunks(content.chunks || []);
    renderSourceDocuments(content.source_documents || []);
    appendLiveEvent("result", `Step ${payload.step_index + 1} · 检索结果`, `${state.stats.evidence} · ${state.stats.chunks} chunks · ${state.stats.docs} docs`, JSON.stringify(content, null, 2));
  });
  source.addEventListener("final_answer", (event) => {
    const payload = JSON.parse(event.data);
    els.answerView.className = "answer-view";
    els.answerView.innerHTML = renderAnswer(payload.answer || "");
    els.answerMeta.textContent = "已生成";
    appendLiveEvent("final", "最终回答", payload.answer);
    setStatus("已完成", "final");
  });
  source.addEventListener("trace_written", (event) => {
    const payload = JSON.parse(event.data);
    state.currentTraceName = payload.name;
    appendLiveEvent("trace", "Trace 已写入", payload.path);
    refreshAll();
    loadTrace(payload.name);
  });
  source.addEventListener("error", (event) => {
    const payload = event.data ? JSON.parse(event.data) : { message: "连接中断" };
    appendLiveEvent("error", payload.type || "Error", payload.message || "连接中断");
    setStatus("运行失败", "error");
  });
  source.addEventListener("done", () => {
    source.close();
    setRunning(false);
  });
}

function setRunning(running) {
  state.running = running;
  els.runButton.disabled = running;
  els.runButton.textContent = running ? "运行中" : "运行";
}

els.refreshButton.addEventListener("click", refreshAll);
els.askForm.addEventListener("submit", (event) => {
  event.preventDefault();
  startRun();
});
els.scenarioSelect.addEventListener("change", () => {
  if (els.scenarioSelect.value) selectScenario(els.scenarioSelect.value);
});
els.questionInput.addEventListener("input", () => {
  const selectedScenario = state.scenarios.find((item) => item.id === els.scenarioSelect.value);
  if (selectedScenario && els.questionInput.value.trim() !== selectedScenario.question) {
    els.scenarioSelect.value = "";
  }
});

refreshAll();
renderStats();
