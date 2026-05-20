const POLL_INTERVAL_MS = 2000;

const state = {
  sessions: [],
  markdown: "",
};

const els = {
  refreshButton: document.getElementById("refreshButton"),
  sessionStatus: document.getElementById("sessionStatus"),
  sessionsList: document.getElementById("sessionsList"),
  traceSubtitle: document.getElementById("traceSubtitle"),
  statusBadge: document.getElementById("statusBadge"),
  statPlans: document.getElementById("statPlans"),
  statActions: document.getElementById("statActions"),
  statObservations: document.getElementById("statObservations"),
  statUserEvents: document.getElementById("statUserEvents"),
  statFinals: document.getElementById("statFinals"),
  statSections: document.getElementById("statSections"),
  markdownMeta: document.getElementById("markdownMeta"),
  markdownView: document.getElementById("markdownView"),
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

function statusLabel(status) {
  const labels = {
    final: "已完成",
    awaiting_user: "等待用户补充",
    warning: "有警告",
    error: "读取失败",
    partial: "进行中",
  };
  return labels[status] || status || "未知";
}

async function fetchJson(url) {
  const response = await fetch(`${url}${url.includes("?") ? "&" : "?"}_=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
  return response.json();
}

async function fetchText(url) {
  const response = await fetch(`${url}${url.includes("?") ? "&" : "?"}_=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
  return response.text();
}

async function refreshAll() {
  try {
    const [sessionsPayload, markdown] = await Promise.all([
      fetchJson("/api/sessions"),
      fetchText("/api/trace-md"),
    ]);
    state.sessions = sessionsPayload.sessions || [];
    state.markdown = markdown;
    renderSessions();
    renderMarkdown(markdown);
    els.sessionStatus.textContent = state.sessions.length
      ? `${state.sessions.length} 个 JSON 会话；主视图展示 trace.md`
      : "未找到 JSON 会话；主视图仍会尝试展示 trace.md";
  } catch (error) {
    renderError(error);
  }
}

function renderSessions() {
  if (!state.sessions.length) {
    els.sessionsList.innerHTML = '<div class="empty-state">暂无会话</div>';
    return;
  }
  els.sessionsList.innerHTML = state.sessions
    .map((session, index) => {
      const active = index === 0 ? " active" : "";
      return `
        <div class="session-card${active}">
          <strong>${escapeHtml(session.name)}</strong>
          <div class="session-meta">
            <span class="pill ${escapeHtml(session.status)}">${escapeHtml(statusLabel(session.status))}</span>
            <span>${escapeHtml(session.event_count)} 个事件</span>
            <span>${escapeHtml(formatDate(session.mtime))}</span>
          </div>
        </div>
      `;
    })
    .join("");
}

function renderMarkdown(markdown) {
  const stats = markdownStats(markdown);
  els.statPlans.textContent = String(stats.plans);
  els.statActions.textContent = String(stats.actions);
  els.statObservations.textContent = String(stats.observations);
  els.statUserEvents.textContent = String(stats.userEvents);
  els.statFinals.textContent = String(stats.finals);
  els.statSections.textContent = String(stats.sections);
  els.traceSubtitle.textContent = "按 trace.md 原始顺序展示完整链路：plan -> action -> observation -> replan。";
  els.statusBadge.className = "status-badge final";
  els.statusBadge.textContent = "已读取";
  els.markdownMeta.textContent = `最后刷新：${formatDate(new Date())}`;
  els.markdownView.innerHTML = markdownToHtml(markdown);
}

function markdownStats(markdown) {
  const headings = markdown.match(/^###\s+.+$/gm) || [];
  return {
    sections: headings.length,
    plans: headings.filter((line) => /^###\s+Plan\b/i.test(line)).length,
    actions: headings.filter((line) => /^###\s+Action\b/i.test(line)).length,
    observations: headings.filter((line) => /^###\s+Observation\b/i.test(line)).length,
    userEvents: headings.filter((line) => /^###\s+(User Decision Required|User Reply)\b/i.test(line)).length,
    finals: headings.filter((line) => /^###\s+Final\b/i.test(line)).length,
  };
}

function markdownToHtml(markdown) {
  if (!markdown.trim()) return '<div class="empty-state">trace.md 为空</div>';
  const lines = markdown.split(/\r?\n/);
  const html = [];
  let inList = false;
  let paragraph = [];

  const closeParagraph = () => {
    if (paragraph.length) {
      html.push(`<p>${renderInline(paragraph.join(" "))}</p>`);
      paragraph = [];
    }
  };
  const closeList = () => {
    if (inList) {
      html.push("</ul>");
      inList = false;
    }
  };

  lines.forEach((line) => {
    if (!line.trim()) {
      closeParagraph();
      closeList();
      return;
    }
    if (line.startsWith("# ")) {
      closeParagraph();
      closeList();
      html.push(`<h1>${renderInline(line.slice(2))}</h1>`);
      return;
    }
    if (line.startsWith("## ")) {
      closeParagraph();
      closeList();
      html.push(`<h2>${renderInline(line.slice(3))}</h2>`);
      return;
    }
    if (line.startsWith("### ")) {
      closeParagraph();
      closeList();
      html.push(`<h3>${renderInline(line.slice(4))}</h3>`);
      return;
    }
    if (line.startsWith("- ")) {
      closeParagraph();
      if (!inList) {
        html.push("<ul>");
        inList = true;
      }
      html.push(`<li>${renderInline(line.slice(2))}</li>`);
      return;
    }
    paragraph.push(line);
  });

  closeParagraph();
  closeList();
  return html.join("\n");
}

function renderInline(value) {
  return escapeHtml(value).replace(/`([^`]+)`/g, "<code>$1</code>");
}

function renderError(error) {
  els.statusBadge.className = "status-badge error";
  els.statusBadge.textContent = "读取失败";
  els.markdownView.innerHTML = `<div class="error-state">${escapeHtml(error.message || error)}</div>`;
}

els.refreshButton.addEventListener("click", refreshAll);
refreshAll();
setInterval(refreshAll, POLL_INTERVAL_MS);
