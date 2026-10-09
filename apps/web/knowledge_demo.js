// 笔记本即工作区：切换笔记本会切换来源列表、对话记录与会话 id。
// 检索范围永远只包含当前笔记本，不再存在"上一次还勾着"的残留状态。

const $ = (id) => document.getElementById(id);

const dom = {
  workspace: $("workspace"),
  notebookMenuToggle: $("notebook-menu-toggle"),
  notebookMenu: $("notebook-menu"),
  notebookList: $("notebook-list"),
  sourceList: $("source-list"),
  sourceCount: $("source-count"),
  sourceSearch: $("source-search"),
  sourcesPanel: $("sources-panel"),
  studioPanel: $("studio-panel"),
  collapseSources: $("collapse-sources"),
  collapseStudio: $("collapse-studio"),
  showSources: $("show-sources"),
  showStudio: $("show-studio"),
  currentNotebook: $("current-notebook"),
  currentSummary: $("current-summary"),
  emptyTitle: $("empty-title"),
  demoStatus: $("demo-status"),
  notebookStatus: $("notebook-status"),
  toggleCreate: $("toggle-create"),
  createForm: $("create-notebook-form"),
  notebookName: $("notebook-name"),
  notebookDescription: $("notebook-description"),
  uploadForm: $("upload-form"),
  openUpload: $("open-upload"),
  closeUpload: $("close-upload"),
  uploadDialog: $("upload-dialog"),
  uploadFiles: $("upload-files"),
  uploadLabel: $("upload-label"),
  uploadSubmit: $("upload-submit"),
  uploadProgress: $("upload-progress"),
  uploadBar: $("upload-bar"),
  uploadProgressText: $("upload-progress-text"),
  uploadPercent: $("upload-percent"),
  studioNotes: $("studio-notes"),
  notesStatus: $("notes-status"),
  log: $("log"),
  emptyState: $("empty-state"),
  emptyHint: $("empty-hint"),
  examples: $("examples"),
  form: $("f"),
  message: $("m"),
  openKeyConfig: $("open-key-config"),
  keyConfigDialog: $("key-config-dialog"),
  keyConfigForm: $("key-config-form"),
  keyConfigInput: $("key-config-input"),
  keyConfigStatus: $("key-config-status"),
  removeKeyConfig: $("remove-key-config"),
  closeKeyConfig: $("close-key-config"),
};

const state = {
  notebooks: [],
  defaultIds: [],
  activeId: null,
  sessions: new Map(),
  transcripts: new Map(),
  drafts: new Map(),
  supported: [],
  busy: false,
  uploading: false,
  sourceDocuments: [],
  deepseekKey: "",
  serverKeyConfigured: false,
};

function canEnterWebKey() {
  const host = window.location.hostname.toLowerCase();
  const loopback = host === "localhost" || host.endsWith(".localhost") || host === "[::1]" ||
    /^127(?:\.[0-9]{1,3}){3}$/.test(host);
  return window.location.protocol === "https:" || (window.location.protocol === "http:" && loopback);
}

function updateKeyStatus() {
  if (!canEnterWebKey()) {
    dom.keyConfigStatus.textContent = "当前地址未使用 HTTPS；个人密钥输入已禁用。";
    dom.openKeyConfig.textContent = "DeepSeek 设置 · 需 HTTPS";
    dom.openKeyConfig.disabled = true;
    return;
  }
  const status = state.deepseekKey
    ? "已配置本页密钥（内容隐藏，刷新后清除）"
    : state.serverKeyConfigured
      ? "本页未设置密钥；正在使用服务器配置"
      : "未配置密钥；使用离线演示模型";
  dom.keyConfigStatus.textContent = status;
  dom.openKeyConfig.textContent = state.deepseekKey ? "DeepSeek · 已配置" : "DeepSeek 设置";
}

// ---------------------------------------------------------------- 小工具

function setStatus(node, text, kind) {
  node.textContent = text || "";
  if (kind) node.dataset.kind = kind;
  else delete node.dataset.kind;
}

function sessionFor(notebookId) {
  if (!state.sessions.has(notebookId)) {
    const generated =
      typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : `s-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    state.sessions.set(notebookId, generated);
  }
  return state.sessions.get(notebookId);
}

function transcriptFor(notebookId) {
  if (!state.transcripts.has(notebookId)) state.transcripts.set(notebookId, []);
  return state.transcripts.get(notebookId);
}

function activeNotebook() {
  return state.notebooks.find((notebook) => notebook.id === state.activeId) || null;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

function formatAnswer(text) {
  return escapeHtml(text).replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
}

function scrollToBottom() {
  dom.log.scrollTop = dom.log.scrollHeight;
}

function closeNotebookMenu() {
  dom.notebookMenu.hidden = true;
  dom.notebookMenuToggle.setAttribute("aria-expanded", "false");
}

function openUploadDialog() {
  const notebook = activeNotebook();
  if (!notebook || !notebook.writable) return;
  dom.uploadDialog.hidden = false;
  document.body.classList.add("dialog-open");
  dom.uploadFiles.focus();
}

function closeUploadDialog() {
  if (state.uploading) return;
  dom.uploadDialog.hidden = true;
  document.body.classList.remove("dialog-open");
}

function notesKey(notebookId) {
  return `knowledge-studio-notes:${notebookId || "none"}`;
}

function loadStudioNotes() {
  dom.studioNotes.value = state.activeId
    ? localStorage.getItem(notesKey(state.activeId)) || ""
    : "";
  dom.studioNotes.disabled = !state.activeId;
  dom.notesStatus.textContent = "自动保存";
}

// ---------------------------------------------------------------- 渲染

function renderNotebookList() {
  dom.notebookList.replaceChildren();
  state.notebooks.forEach((notebook) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "notebook-item";
    button.setAttribute("aria-current", String(notebook.id === state.activeId));

    const icon = document.createElement("span");
    icon.className = "notebook-icon";
    icon.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 4h12v16H6zM9 8h6M9 12h6"/></svg>';

    const copy = document.createElement("span");
    copy.className = "notebook-copy";

    const name = document.createElement("span");
    name.className = "notebook-name";
    name.textContent = notebook.name;

    const meta = document.createElement("span");
    meta.className = "notebook-meta";
    meta.textContent = `${notebook.document_count} 篇来源${notebook.writable ? "" : " · 内置"}`;

    copy.append(name, meta);
    const check = document.createElement("span");
    check.className = "notebook-check";
    check.textContent = notebook.id === state.activeId ? "✓" : "";
    button.append(icon, copy, check);
    button.onclick = () => {
      closeNotebookMenu();
      setActiveNotebook(notebook.id).catch((error) =>
        setStatus(dom.notebookStatus, error.message, "error")
      );
    };
    dom.notebookList.append(button);
  });
}

function renderHeader() {
  const notebook = activeNotebook();
  dom.currentNotebook.textContent = notebook ? notebook.name : "未选择笔记本";
  dom.currentSummary.textContent = notebook ? `${notebook.document_count} 篇来源` : "";
  dom.emptyTitle.textContent = notebook ? `探索「${notebook.name}」` : "和你的来源对话";
}

function renderSources(documents = state.sourceDocuments) {
  state.sourceDocuments = documents;
  dom.sourceList.replaceChildren();
  dom.sourceCount.textContent = documents.length ? String(documents.length) : "";

  const query = dom.sourceSearch.value.trim().toLocaleLowerCase();
  const visibleDocuments = query
    ? documents.filter((item) => item.title.toLocaleLowerCase().includes(query))
    : documents;

  if (!documents.length) {
    const empty = document.createElement("li");
    empty.className = "source-empty";
    empty.textContent = "这个笔记本还没有来源。";
    dom.sourceList.append(empty);
    return;
  }

  if (!visibleDocuments.length) {
    const empty = document.createElement("li");
    empty.className = "source-empty";
    empty.textContent = `没有找到“${dom.sourceSearch.value.trim()}”`;
    dom.sourceList.append(empty);
    return;
  }

  visibleDocuments.forEach((document_) => {
    const item = document.createElement("li");
    item.className = "source-item";

    const icon = document.createElement("span");
    icon.className = "source-doc-icon";
    icon.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h9l4 4v14H6zM14 3v5h5M9 13h7M9 17h5"/></svg>';

    const copy = document.createElement("span");
    copy.className = "source-copy";

    const title = document.createElement("span");
    title.className = "source-title";
    title.textContent = document_.title;
    title.title = document_.source_id;

    const chunks = document.createElement("span");
    chunks.className = "source-chunks";
    chunks.textContent = `${document_.chunks} 块`;

    copy.append(title, chunks);
    item.append(icon, copy);
    dom.sourceList.append(item);
  });
}

function messageNode(entry) {
  const article = document.createElement("article");
  article.className = `message message-${entry.role}`;
  if (entry.pending) article.classList.add("message-pending");

  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.textContent = entry.role === "user" ? "你" : "AI";

  const content = document.createElement("div");
  content.className = "message-content";

  const role = document.createElement("div");
  role.className = "message-role";
  role.textContent = entry.role === "user" ? "你" : "Agent";

  const body = document.createElement("div");
  body.className = "message-body";
  if (entry.role === "user") body.textContent = entry.text;
  else body.innerHTML = formatAnswer(entry.text);

  content.append(role, body);

  if (entry.traceId) {
    const trace = document.createElement("a");
    trace.className = "trace";
    trace.href = `/api/trace/${entry.traceId}`;
    trace.target = "_blank";
    trace.rel = "noreferrer";
    trace.textContent = `trace ${entry.traceId}`;
    content.append(trace);
  }
  article.append(avatar, content);
  return article;
}

function renderTranscript() {
  const entries = state.activeId ? transcriptFor(state.activeId) : [];
  dom.log.replaceChildren();
  entries.forEach((entry) => dom.log.append(messageNode(entry)));
  dom.emptyState.hidden = entries.length > 0;

  const notebook = activeNotebook();
  dom.emptyHint.textContent = notebook
    ? `当前只检索「${notebook.name}」。左栏切换笔记本会切换到独立的工作区与会话。`
    : "先在左栏选择一个笔记本。";
}

function renderExamples(questions) {
  dom.examples.replaceChildren();
  (questions || []).forEach((item) => {
    const suggestion =
      typeof item === "string" ? { question: item, topic: "知识库", title: "" } : item;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "example-question";

    const label = [suggestion.topic, suggestion.title].filter(Boolean).join(" · ");
    if (label) {
      const source = document.createElement("span");
      source.className = "example-source";
      source.textContent = label;
      button.append(source);
    }

    const text = document.createElement("span");
    text.className = "example-text";
    text.textContent = suggestion.question;
    button.append(text);

    button.onclick = () => {
      dom.message.value = suggestion.question;
      dom.message.focus();
    };
    dom.examples.append(button);
  });
}

function updateUploadState() {
  const notebook = activeNotebook();
  const writable = Boolean(notebook && notebook.writable);
  dom.openUpload.disabled = !writable;
  dom.openUpload.title = writable ? `添加来源到「${notebook.name}」` : "内置知识库不能添加来源";
  dom.uploadLabel.textContent = writable ? `添加到「${notebook.name}」` : "选择本地文件";
  if (state.supported.length) dom.uploadFiles.accept = state.supported.join(",");
  if (!writable) closeUploadDialog();
}

function setUploading(active) {
  state.uploading = active;
  dom.uploadSubmit.disabled = active;
  dom.uploadFiles.disabled = active;
  dom.uploadSubmit.textContent = active ? "正在处理来源…" : "转换并添加到笔记本";
  if (active) dom.uploadProgress.hidden = false;
}

function renderProgress(record) {
  if (!record) return;
  const total = Number(record.total) || 0;
  const done = Number(record.done) || 0;
  const stage = record.stage || "处理中";
  const message = record.message ? ` · ${record.message}` : "";

  if (total > 0) {
    const percent = Math.min(100, Math.round((done / total) * 100));
    dom.uploadPercent.textContent = `${percent}%`;
    dom.uploadBar.dataset.indeterminate = "false";
    dom.uploadBar.style.width = `${percent}%`;
    dom.uploadBar.setAttribute("aria-valuenow", String(percent));
    dom.uploadProgressText.textContent = `${stage} ${done}/${total}（${percent}%）${message}`;
  } else {
    dom.uploadPercent.textContent = "处理中";
    dom.uploadBar.dataset.indeterminate = "true";
    dom.uploadBar.removeAttribute("aria-valuenow");
    dom.uploadProgressText.textContent = `${stage}${message}`;
  }

  if (record.state === "error") dom.uploadProgressText.dataset.kind = "error";
  else delete dom.uploadProgressText.dataset.kind;
}

// ---------------------------------------------------------------- 数据

async function loadSources(notebookId) {
  const response = await fetch(`/api/notebooks/${encodeURIComponent(notebookId)}/documents`);
  if (!response.ok) throw new Error("来源列表加载失败");
  const payload = await response.json();
  if (state.activeId !== notebookId) return; // 用户已经切走，丢弃过期响应
  renderSources(payload.documents || []);
}

async function loadSuggestions(notebookId) {
  try {
    const response = await fetch(
      `/api/notebooks/${encodeURIComponent(notebookId)}/suggestions`
    );
    if (!response.ok) throw new Error("示例问题加载失败");
    const payload = await response.json();
    if (state.activeId !== notebookId) return;
    const questions = payload.questions || [];
    // 示例问题必须来自当前笔记本自己的内容；没有就留空，不要套用别的语料。
    renderExamples(questions);
  } catch (error) {
    if (state.activeId !== notebookId) return;
    renderExamples([]);
  }
}

async function setActiveNotebook(notebookId) {
  const previous = state.activeId;
  if (previous && previous !== notebookId) {
    state.drafts.set(previous, dom.message.value);
  }

  state.activeId = notebookId;
  state.sourceDocuments = [];
  dom.sourceSearch.value = "";
  if (notebookId) sessionFor(notebookId);

  renderNotebookList();
  renderHeader();
  renderTranscript();
  dom.message.value = notebookId ? state.drafts.get(notebookId) || "" : "";
  updateUploadState();
  loadStudioNotes();

  if (!notebookId) return;
  try {
    await loadSources(notebookId);
  } catch (error) {
    setStatus(dom.notebookStatus, `来源加载失败：${error.message}`, "error");
  }
  await loadSuggestions(notebookId);
}

async function loadNotebooks(preferredId = "") {
  const response = await fetch("/api/notebooks");
  if (!response.ok) throw new Error("笔记本列表加载失败");
  const payload = await response.json();

  state.notebooks = payload.notebooks || [];
  state.defaultIds = payload.default_ids || [];
  state.supported = payload.supported_extensions || [];

  const currentStillExists = state.notebooks.some(
    (notebook) => notebook.id === state.activeId
  );
  const nextId =
    preferredId ||
    (currentStillExists ? state.activeId : "") ||
    state.defaultIds[0] ||
    (state.notebooks[0] ? state.notebooks[0].id : "");

  if (nextId) {
    await setActiveNotebook(nextId);
  } else {
    renderNotebookList();
    renderHeader();
    renderTranscript();
    updateUploadState();
  }
}

// ---------------------------------------------------------------- 对话

async function send(question) {
  const text = question.trim();
  if (!text || !state.activeId || state.busy) return;

  const notebookId = state.activeId;
  const sessionId = sessionFor(notebookId);
  const entries = transcriptFor(notebookId);

  state.busy = true;
  entries.push({ role: "user", text });
  const pending = { role: "agent", text: "正在检索并组织回答…", pending: true };
  entries.push(pending);
  renderTranscript();
  scrollToBottom();

  dom.message.value = "";
  state.drafts.set(notebookId, "");

  // 密钥只进入此 POST 请求头；不放入 URL、浏览器持久存储或聊天正文。
  try {
    const headers = { "Content-Type": "application/json" };
    if (canEnterWebKey() && state.deepseekKey) headers["X-DeepSeek-Api-Key"] = state.deepseekKey;
    const response = await fetch("/api/chat", {
      method: "POST",
      headers,
      cache: "no-store",
      body: JSON.stringify({
        message: text,
        session_id: sessionId,
        user_id: "anon",
        knowledge_base_ids: [notebookId],
      }),
    });
    if (!response.ok) throw new Error(`请求失败（${response.status}）`);
    const result = await response.json();
    pending.pending = false;
    pending.text = result.answer || "(空回答)";
    pending.traceId = result.trace_id || "";
    renderTranscript();
    scrollToBottom();
    loadNotebooks(notebookId).catch(() => {});
  } catch (error) {
    pending.pending = false;
    pending.text = error.message || "连接中断，没有收到回答。";
    renderTranscript();
  } finally {
    state.busy = false;
  }
}

// ---------------------------------------------------------------- 事件绑定

dom.form.onsubmit = (event) => {
  event.preventDefault();
  send(dom.message.value);
};

dom.openKeyConfig.onclick = () => {
  if (!canEnterWebKey()) return;
  updateKeyStatus();
  dom.keyConfigDialog.showModal();
};
dom.closeKeyConfig.onclick = () => dom.keyConfigDialog.close();
dom.keyConfigForm.onsubmit = (event) => {
  event.preventDefault();
  if (!canEnterWebKey()) return;
  const key = dom.keyConfigInput.value.trim();
  if (!key || key.length > 512) {
    dom.keyConfigStatus.textContent = "请输入有效的密钥（最多 512 个字符）";
    return;
  }
  state.deepseekKey = key;
  dom.keyConfigInput.value = "";
  updateKeyStatus();
  dom.keyConfigDialog.close();
};
dom.removeKeyConfig.onclick = () => {
  state.deepseekKey = "";
  dom.keyConfigInput.value = "";
  updateKeyStatus();
};
fetch("/api/llm/config", { cache: "no-store" })
  .then((response) => response.ok ? response.json() : Promise.reject())
  .then((config) => {
    state.serverKeyConfigured = Boolean(config.server_key_configured);
    updateKeyStatus();
  })
  .catch(() => {});
updateKeyStatus();

dom.message.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    send(dom.message.value);
  }
});

dom.message.addEventListener("input", () => {
  if (state.activeId) state.drafts.set(state.activeId, dom.message.value);
  dom.message.style.height = "auto";
  dom.message.style.height = `${Math.min(dom.message.scrollHeight, 168)}px`;
});

dom.notebookMenuToggle.onclick = () => {
  const opening = dom.notebookMenu.hidden;
  dom.notebookMenu.hidden = !opening;
  dom.notebookMenuToggle.setAttribute("aria-expanded", String(opening));
};

dom.toggleCreate.onclick = () => {
  const nextHidden = !dom.createForm.hidden;
  dom.createForm.hidden = nextHidden;
  dom.toggleCreate.setAttribute("aria-expanded", String(!nextHidden));
  if (!nextHidden) dom.notebookName.focus();
};

dom.sourceSearch.addEventListener("input", () => renderSources());

dom.openUpload.onclick = openUploadDialog;
dom.closeUpload.onclick = closeUploadDialog;
dom.uploadDialog.addEventListener("click", (event) => {
  if (event.target === dom.uploadDialog) closeUploadDialog();
});

function toggleDesktopPanel(panel, button, labels) {
  const collapsed = panel.classList.toggle("is-collapsed");
  button.setAttribute("aria-expanded", String(!collapsed));
  button.title = collapsed ? labels.open : labels.close;
  button.setAttribute("aria-label", button.title);
}

dom.collapseSources.onclick = () => {
  if (window.matchMedia("(max-width: 900px)").matches) {
    dom.sourcesPanel.classList.remove("mobile-open");
  } else {
    toggleDesktopPanel(dom.sourcesPanel, dom.collapseSources, {
      open: "展开来源栏",
      close: "收起来源栏",
    });
  }
};

dom.collapseStudio.onclick = () => {
  if (window.matchMedia("(max-width: 900px)").matches) {
    dom.studioPanel.classList.remove("mobile-open");
  } else {
    toggleDesktopPanel(dom.studioPanel, dom.collapseStudio, {
      open: "展开工作室",
      close: "收起工作室",
    });
  }
};

dom.showSources.onclick = () => {
  dom.studioPanel.classList.remove("mobile-open");
  dom.sourcesPanel.classList.add("mobile-open");
};

dom.showStudio.onclick = () => {
  dom.sourcesPanel.classList.remove("mobile-open");
  dom.studioPanel.classList.add("mobile-open");
};

document.querySelectorAll("[data-studio-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    if (!state.activeId || state.busy) return;
    dom.message.value = button.dataset.studioPrompt || "";
    dom.message.dispatchEvent(new Event("input"));
    dom.message.focus();
    if (window.matchMedia("(max-width: 900px)").matches) {
      dom.studioPanel.classList.remove("mobile-open");
    }
  });
});

let notesTimer;
dom.studioNotes.addEventListener("input", () => {
  if (!state.activeId) return;
  localStorage.setItem(notesKey(state.activeId), dom.studioNotes.value);
  dom.notesStatus.textContent = "已保存";
  clearTimeout(notesTimer);
  notesTimer = setTimeout(() => { dom.notesStatus.textContent = "自动保存"; }, 1400);
});

document.addEventListener("click", (event) => {
  if (
    !dom.notebookMenu.hidden &&
    !dom.notebookMenu.contains(event.target) &&
    !dom.notebookMenuToggle.contains(event.target)
  ) closeNotebookMenu();
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  closeNotebookMenu();
  closeUploadDialog();
  dom.sourcesPanel.classList.remove("mobile-open");
  dom.studioPanel.classList.remove("mobile-open");
});

dom.createForm.onsubmit = async (event) => {
  event.preventDefault();
  const name = dom.notebookName.value.trim();
  if (!name) return;

  setStatus(dom.notebookStatus, "正在创建笔记本…");
  try {
    const response = await fetch("/api/notebooks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        description: dom.notebookDescription.value.trim(),
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "创建失败");

    dom.createForm.reset();
    dom.createForm.hidden = true;
    dom.toggleCreate.setAttribute("aria-expanded", "false");
    await loadNotebooks(result.id);
    closeNotebookMenu();
    setStatus(dom.notebookStatus, `已创建「${result.name}」，现在可以添加来源。`, "success");
  } catch (error) {
    setStatus(dom.notebookStatus, `创建失败：${error.message}`, "error");
  }
};

dom.uploadForm.onsubmit = async (event) => {
  event.preventDefault();
  if (state.uploading) return;

  const files = [...dom.uploadFiles.files];
  const notebookId = state.activeId;
  if (!files.length || !notebookId) return;

  const uploadId =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `u-${Date.now()}`;
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));

  setStatus(dom.notebookStatus, "");
  dom.uploadBar.style.width = "0";
  dom.uploadBar.dataset.indeterminate = "true";
  renderProgress({
    state: "running",
    stage: "上传中",
    done: 0,
    total: 0,
    message: `${files.length} 个文件`,
  });
  setUploading(true);

  let settled = false;
  const poller = (async () => {
    while (!settled) {
      await new Promise((resolve) => setTimeout(resolve, 700));
      if (settled) break;
      try {
        const response = await fetch(`/api/uploads/${encodeURIComponent(uploadId)}`);
        if (response.ok) renderProgress(await response.json());
      } catch (error) {
        // 单次轮询失败无所谓，下一次继续。
      }
    }
  })();

  try {
    const response = await fetch(
      `/api/notebooks/${encodeURIComponent(notebookId)}/files?upload_id=${encodeURIComponent(uploadId)}`,
      { method: "POST", body: formData }
    );
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "导入失败");

    dom.uploadForm.reset();
    await loadNotebooks(notebookId);
    setStatus(dom.notebookStatus, `已导入 ${result.imported.length} 篇 Markdown 来源。`, "success");
    setUploading(false);
    closeUploadDialog();
    dom.uploadProgress.hidden = true;
  } catch (error) {
    setStatus(dom.notebookStatus, `导入失败：${error.message}`, "error");
    dom.uploadProgressText.dataset.kind = "error";
    dom.uploadProgressText.textContent = error.message;
    dom.uploadBar.dataset.indeterminate = "false";
    dom.uploadBar.style.width = "0";
  } finally {
    settled = true;
    await poller;
    setUploading(false);
  }
};

// ---------------------------------------------------------------- 启动

fetch("/api/admin/session")
  .then(async (response) => {
    if (!response.ok) throw new Error("管理员会话已失效，请重新登录。");
    const session = await response.json();
    $("workspace-mode-label").textContent = session.administrator ? "管理员工作区" : "本地工作区";
    $("admin-identity").title = session.administrator ? "已通过拥有者管理员认证" : "本地工作区";
    $("admin-logout").hidden = !session.administrator;
  })
  .catch((error) => {
    $("workspace-mode-label").textContent = "会话已失效";
    dom.toggleCreate.disabled = true;
    dom.openUpload.disabled = true;
    setStatus(dom.notebookStatus, error.message, "error");
  });

$("admin-logout").onclick = async () => {
  const button = $("admin-logout");
  button.disabled = true;
  try {
    const auth = new URL("./auth/", window.location.href);
    const csrfResponse = await fetch(new URL("csrf", auth), { cache: "no-store" });
    const csrf = await csrfResponse.json();
    if (!csrfResponse.ok) throw new Error(csrf.detail || "退出登录失败。");
    const response = await fetch(new URL("logout", auth), {
      method: "POST", headers: { [csrf.headerName]: csrf.token },
    });
    if (!response.ok) throw new Error("退出登录失败，请稍后重试。");
    state.deepseekKey = "";
    window.location.assign(new URL("./login", window.location.href));
  } catch (error) {
    setStatus(dom.notebookStatus, error.message, "error");
    button.disabled = false;
  }
};

fetch("/api/demo")
  .then((response) => {
    if (!response.ok) throw new Error("demo unavailable");
    return response.json();
  })
  .then((dataset) => {
    dom.demoStatus.textContent = `${dataset.name}：${dataset.imported}/${dataset.documents} 篇 · ${dataset.question_count} 个问题`;
  })
  .catch(() => {
    dom.demoStatus.textContent = "演示知识库状态不可用";
  });

loadNotebooks().catch((error) =>
  setStatus(dom.notebookStatus, error.message, "error")
);
