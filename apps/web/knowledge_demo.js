// 笔记本即工作区：切换笔记本会切换来源列表、对话记录与会话 id。
// 检索范围永远只包含当前笔记本，不再存在"上一次还勾着"的残留状态。

const $ = (id) => document.getElementById(id);
// Every browser request stays on this RAGnotebook HTTP origin.
const apiURL = (path) => new URL(path.replace(/^\//, ""), window.location.href);

async function readJSON(response) {
  const text = await response.text();
  try { return text ? JSON.parse(text) : {}; }
  catch { throw new Error(`服务响应异常（HTTP ${response.status}），请稍后重试。`); }
}

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
};

const state = {
  notebooks: [],
  defaultIds: [],
  activeId: null,
  sessions: new Map(),
  conversations: new Map(),
  conversationListLoaded: false,
  transcripts: new Map(),
  drafts: new Map(),
  supported: [],
  busy: false,
  chatController: null,
  uploading: false,
  sourceDocuments: [],
  principal: null,
  guestModelProvider: "",
  guestModelId: "",
  guestModels: [],
  guestModelLoading: false,
  guestModelsLoaded: false,
};

function permitted(permission) {
  const principal = state.principal;
  if (!principal || !["admin", "user", "guest"].includes(principal.role)) return false;
  if (["import_document", "write", "manage_members"].includes(permission)) {
    return activeNotebook()?.permissions?.includes(permission) === true;
  }
  return principal.permissions?.includes(permission) === true;
}

function applyPermissions() {
  const principal = state.principal;
  const administrator = principal?.role === "admin" && principal.administrator === true;
  if (principal?.role !== "guest") {
    state.guestModelProvider = "";
    state.guestModelId = "";
    state.guestModels = [];
    state.guestModelsLoaded = false;
  }
  $("workspace-mode-label").textContent = administrator ? "管理员" : principal?.role === "user" ? "已登录" : principal ? "游客 · 公开资料" : "身份未确认";
  $("admin-identity").textContent = principal?.role !== "guest" && principal ? Array.from(principal.user_id || "U")[0] : principal ? "客" : "…";
  $("admin-identity").title = principal?.role !== "guest" && principal ? `用户ID：${principal.user_id}` : "游客只能读取公开资料和提问";
  $("admin-logout").hidden = !principal || principal.role === "guest";
  $("auth-open").hidden = Boolean(principal && principal.role !== "guest");
  $("open-admin-users").hidden = !administrator;
  $("open-model-admin").hidden = !administrator;
  $("guest-model-picker").hidden = principal?.role !== "guest" || state.guestModels.length === 0;
  updateWebQuota(state.webQuota);
  if (principal?.role === "guest" && !state.guestModelsLoaded && !state.guestModelLoading) {
    loadGuestModels().catch(() => { $("server-model-status").textContent = "游客模型目录暂不可用"; });
  }
  dom.toggleCreate.hidden = !permitted("create_notebook");
  dom.toggleCreate.disabled = !permitted("create_notebook");
  if (!permitted("create_notebook")) dom.createForm.hidden = true;
  dom.openUpload.hidden = !permitted("import_document");
  $("open-members").hidden = !permitted("manage_members");
  dom.studioNotes.closest(".notes-card").hidden = !permitted("write");
  dom.message.disabled = !permitted("query");
  dom.form.querySelector('button[type="submit"]').disabled = !permitted("query");
  updateUploadState();
}

async function apiFetch(path, options = {}) {
  const response = await fetch(apiURL(path), { credentials: "same-origin", cache: "no-store", ...options });
  if (response.status === 401) {
    state.principal = null;
    applyPermissions();
    setStatus(dom.notebookStatus, "登录已失效，请重新登录。", "error");
  }
  return response;
}

function updateWebQuota(quota) {
  state.webQuota = quota;
  const label = $("web-quota");
  label.hidden = !quota;
  if (quota) label.textContent = state.principal?.role === "guest"
    ? `游客可用：全站今日剩余 ${quota.remaining}/${quota.limit} 次 · 北京时间零点恢复`
    : `全站今日剩余 ${quota.remaining}/${quota.limit} 次 · 北京时间零点恢复`;
}

async function loadGuestModels(force = false) {
  if (state.principal?.role !== "guest" || state.guestModelLoading) return;
  if (state.guestModelsLoaded && !force) return;
  state.guestModelLoading = true;
  try {
    const response = await apiFetch("/api/models/guest", { cache: "no-store" });
    const payload = await readJSON(response);
    if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "模型目录暂不可用");
    if (state.principal?.role !== "guest") return;
    const select = $("guest-model-choice");
    const previous = state.guestModelProvider === payload.provider_id ? state.guestModelId : "";
    state.guestModelProvider = payload.provider_id;
    state.guestModels = payload.models || [];
    select.replaceChildren();
    for (const model of state.guestModels) {
      const option = document.createElement("option");
      option.value = model.id || model.model_id;
      option.textContent = model.name || option.value;
      select.append(option);
    }
    const preferred = state.guestModels.some((item) => (item.id || item.model_id) === previous)
      ? previous : payload.default_model_id;
    if (preferred && state.guestModels.some((item) => (item.id || item.model_id) === preferred)) select.value = preferred;
    state.guestModelId = select.value || "";
    $("guest-model-picker").hidden = state.principal?.role !== "guest" || state.guestModels.length === 0;
    state.guestModelsLoaded = true;
  } finally {
    state.guestModelLoading = false;
  }
}

$("guest-model-choice").onchange = () => { state.guestModelId = $("guest-model-choice").value; };
$("guest-model-choice").onfocus = () => { loadGuestModels(true).catch(() => {}); };

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
  return typeof renderMarkdown === "function" ? renderMarkdown(text) : escapeHtml(text);
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
  if (!permitted("import_document") || !notebook || !notebook.writable) return;
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
  return `knowledge-studio-notes:${state.principal?.user_id || "guest"}:${notebookId || "none"}`;
}

function loadStudioNotes() {
  dom.studioNotes.value = state.activeId
    ? localStorage.getItem(notesKey(state.activeId)) || ""
    : "";
  dom.studioNotes.disabled = !state.activeId || !permitted("write");
  dom.notesStatus.textContent = "自动保存";
}

// ---------------------------------------------------------------- 渲染

function deleteButton(label, action) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "delete-resource";
  button.textContent = "删除";
  button.title = label;
  button.setAttribute("aria-label", label);
  button.onclick = async () => {
    if (state.busy || state.uploading) {
      setStatus(dom.notebookStatus, "请等待当前问答或导入完成后再删除。", "error");
      return;
    }
    button.disabled = true;
    try { await action(); }
    catch (error) { setStatus(dom.notebookStatus, error.message, "error"); }
    finally { button.disabled = false; }
  };
  return button;
}

async function removeNotebook(notebook) {
  if (!window.confirm(`删除笔记本“${notebook.name}”？其中所有来源、成员及关联对话会一起删除，无法恢复。`)) return;
  const response = await apiFetch(`/api/notebooks/${encodeURIComponent(notebook.id)}`, { method: "DELETE" });
  const result = await readJSON(response);
  if (!response.ok) throw new Error(result.detail || "删除失败");
  for (const map of [state.sessions, state.conversations, state.transcripts, state.drafts]) map.delete(notebook.id);
  localStorage.removeItem(notesKey(notebook.id));
  await loadNotebooks(notebook.id === state.activeId ? null : state.activeId);
  setStatus(dom.notebookStatus, "笔记本已删除。", "success");
}

async function removeSource(document_) {
  const notebookId = state.activeId;
  if (!window.confirm(`删除来源“${document_.title}”？删除后此来源将不再参与检索，无法恢复。`)) return;
  const response = await apiFetch(`/api/notebooks/${encodeURIComponent(notebookId)}/documents?source_id=${encodeURIComponent(document_.source_id)}`, { method: "DELETE" });
  const result = await readJSON(response);
  if (!response.ok) throw new Error(result.detail || "删除失败");
  await loadNotebooks(notebookId);
  setStatus(dom.notebookStatus, "来源已删除。", "success");
}

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
    meta.textContent = `${notebook.document_count} 篇来源${notebook.writable ? "" : " · 只读"}`;

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
    const row = document.createElement("div");
    row.className = "notebook-row";
    row.append(button);
    if (notebook.permissions?.includes("manage_notebook") && notebook.id !== "cmrc2018-demo") {
      const remove = deleteButton("删除笔记本", () => removeNotebook(notebook));
      row.append(remove);
    }
    dom.notebookList.append(row);
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
    if (permitted("import_document") && state.activeId !== "cmrc2018-demo") {
      item.append(deleteButton(`删除来源 ${document_.title}`, () => removeSource(document_)));
    }
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
    trace.href = apiURL(`/api/trace/${encodeURIComponent(entry.traceId)}`).href;
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
  const writable = Boolean(permitted("import_document") && notebook && notebook.writable);
  dom.openUpload.disabled = !writable;
  dom.openUpload.title = writable ? `添加来源到「${notebook.name}」` : permitted("import_document") ? "内置知识库不能添加来源" : "当前笔记本没有导入权限";
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
    dom.uploadProgressText.textContent = `${record.file ? record.file + " · " : ""}${stage} ${done}/${total}${record.unit || ""}（${percent}%）${message}`;
  } else {
    dom.uploadPercent.textContent = "处理中";
    dom.uploadBar.dataset.indeterminate = "true";
    dom.uploadBar.style.removeProperty("width");
    dom.uploadBar.removeAttribute("aria-valuenow");
    dom.uploadProgressText.textContent = `${record.file ? record.file + " · " : ""}${stage}${message}`;
  }

  if (record.state === "error") dom.uploadProgressText.dataset.kind = "error";
  else delete dom.uploadProgressText.dataset.kind;
}

// ---------------------------------------------------------------- 数据

async function loadSources(notebookId) {
  const response = await apiFetch(`/api/notebooks/${encodeURIComponent(notebookId)}/documents`);
  if (!response.ok) throw new Error("来源列表加载失败");
  const payload = await readJSON(response);
  if (state.activeId !== notebookId) return; // 用户已经切走，丢弃过期响应
  renderSources(payload.documents || []);
}

async function loadSuggestions(notebookId) {
  try {
    const response = await apiFetch(
      `/api/notebooks/${encodeURIComponent(notebookId)}/suggestions`
    );
    if (!response.ok) throw new Error("示例问题加载失败");
    const payload = await readJSON(response);
    if (state.activeId !== notebookId) return;
    const questions = payload.questions || [];
    // 示例问题必须来自当前笔记本自己的内容；没有就留空，不要套用别的语料。
    renderExamples(questions);
  } catch (error) {
    if (state.activeId !== notebookId) return;
    renderExamples([]);
  }
}

async function restorePersistentConversation(notebookId) {
  if (!state.principal || state.principal.role === "guest") return;
  try {
    if (!state.conversationListLoaded) {
      const response = await apiFetch("/api/conversations");
      if (!response.ok) throw new Error("会话列表加载失败");
      const payload = await readJSON(response);
      state.savedConversations = payload.conversations || [];
      state.conversationListLoaded = true;
    }
    const match = (state.savedConversations || []).find((item) => {
      let scope = item.notebook_id;
      try { if (typeof scope === "string") scope = JSON.parse(scope); } catch { return false; }
      return Array.isArray(scope) && scope.length === 1 && scope[0] === notebookId;
    });
    if (!match) return;
    state.conversations.set(notebookId, match.id);
    const messages = Array.isArray(match.messages) ? match.messages : [];
    state.transcripts.set(notebookId, messages.map((message) => ({
      role: message.role === "assistant" ? "agent" : "user",
      text: message.content || "",
      traceId: message.trace_id || "",
    })));
  } catch (error) {
    setStatus(dom.notebookStatus, `历史会话加载失败：${error.message}`, "error");
  }
}

async function setActiveNotebook(notebookId) {
  const previous = state.activeId;
  if (previous && previous !== notebookId) {
    state.drafts.set(previous, dom.message.value);
  }

  state.activeId = notebookId;
  if (notebookId) await restorePersistentConversation(notebookId);
  applyPermissions();
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
  const response = await apiFetch("/api/notebooks");
  if (!response.ok) throw new Error("笔记本列表加载失败");
  const payload = await readJSON(response);

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
  if (!text || !state.activeId || state.busy || !permitted("query")) return;
  if (state.principal.role === "guest" && Array.from(text).length > 1024) {
    setStatus(dom.notebookStatus, "公开问题最多 1024 字。", "error");
    return;
  }

  const notebookId = state.activeId;
  const sessionId = sessionFor(notebookId);
  const entries = transcriptFor(notebookId);

  state.busy = true;
  const controller = new AbortController();
  state.chatController = controller;
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, 130000);
  $("cancel-chat").hidden = false;
  entries.push({ role: "user", text });
  const pending = { role: "agent", text: "正在检索并组织回答…", pending: true };
  entries.push(pending);
  renderTranscript();
  scrollToBottom();

  dom.message.value = "";
  state.drafts.set(notebookId, "");

  try {
    const headers = { "Content-Type": "application/json" };
    const authenticated = ["admin", "user"].includes(state.principal.role);
    const response = await apiFetch("/api/chat", {
      signal: controller.signal,
      method: "POST",
      headers,
      cache: "no-store",
      body: JSON.stringify({
        message: text,
        session_id: sessionId,
        conversation_id: authenticated ? state.conversations.get(notebookId) || "" : "",
        knowledge_base_ids: [notebookId],
        ...(state.principal.role === "guest" && state.guestModelId
          ? { model_id: state.guestModelId, catalog_provider_id: state.guestModelProvider }
          : {}),
      }),
    });
    const result = await readJSON(response);
    if (response.status === 409 && state.principal?.role === "guest") {
      state.guestModelsLoaded = false;
      await loadGuestModels(true);
    }
    if (result.quota || result.detail?.quota) updateWebQuota(result.quota || result.detail.quota);
    if (!response.ok) {
      const message = result.detail?.message || (typeof result.detail === "string" ? result.detail : `请求失败（${response.status}）`);
      throw new Error(message + (result.trace_id ? ` 记录编号：${result.trace_id}` : ""));
    }
    if (result.conversation_id) state.conversations.set(notebookId, result.conversation_id);
    pending.pending = false;
    pending.text = result.answer || "(空回答)";
    pending.traceId = result.trace_id || "";
    renderTranscript();
    scrollToBottom();
    if (authenticated) state.conversationListLoaded = false;
    loadNotebooks(notebookId).catch(() => {});
  } catch (error) {
    pending.pending = false;
    pending.text = error.name === "AbortError" ? (timedOut ? "等待超时，请重试或选择其他模型。" : "已取消等待。") : error.message || "连接中断，没有收到回答。";
    renderTranscript();
  } finally {
    clearTimeout(timer);
    state.chatController = null;
    $("cancel-chat").hidden = true;
    state.busy = false;
  }
}

$("cancel-chat").onclick = () => state.chatController?.abort();

// ---------------------------------------------------------------- 事件绑定

dom.form.onsubmit = (event) => {
  event.preventDefault();
  send(dom.message.value);
};

function refreshPublicStatus() {
  return apiFetch("/api/llm/config", { cache: "no-store" })
  .then((response) => response.ok ? readJSON(response) : Promise.reject())
  .then((config) => {
    state.modelProvider = config.provider;
    updateWebQuota(config.quota);
    $("server-model-status").textContent = `模型：${config.provider || "Mock"} · ${config.model || "默认"}`;
  })
  .catch(() => { $("server-model-status").textContent = "模型配置暂不可用"; });
}

refreshPublicStatus();
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  refreshPublicStatus();
  loadGuestModels(true).catch(() => {});
});

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
  if (!permitted("create_notebook")) return;
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
  if (!state.activeId || !permitted("write")) return;
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
  if (!permitted("create_notebook")) return;
  const name = dom.notebookName.value.trim();
  if (!name) return;

  setStatus(dom.notebookStatus, "正在创建笔记本…");
  try {
    const response = await apiFetch("/api/notebooks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
      }),
    });
    const result = await readJSON(response);
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

function uploadWithProgress(path, formData) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", apiURL(path));
    xhr.withCredentials = true;
    xhr.upload.onprogress = (event) => renderProgress({
      stage: "上传文件", done: event.loaded, total: event.lengthComputable ? event.total : 0, unit: "字节",
    });
    xhr.upload.onload = () => renderProgress({ stage: "上传完成，等待解析", done: 0, total: 0 });
    xhr.onerror = () => reject(new Error("上传连接中断，请重试。"));
    xhr.ontimeout = () => reject(new Error("文件传输超时，请检查连接后重试。"));
    // 这个请求只负责传输/暂存；长时间的推理由后台任务完成。
    xhr.timeout = 20 * 60 * 1000;
    xhr.onload = () => resolve(new Response(xhr.responseText, { status: xhr.status, headers: { "Content-Type": xhr.getResponseHeader("Content-Type") || "text/plain" } }));
    xhr.send(formData);
  });
}

function pendingUploadKey(userId) {
  return `ragnotebook:pending-upload:${userId}`;
}

function rememberUpload(userId, notebookId, uploadId) {
  try { localStorage.setItem(pendingUploadKey(userId), JSON.stringify({ notebookId, uploadId })); }
  catch { /* 禁用本地存储时，当前页面仍可完成导入。 */ }
}

function forgetUpload(userId) {
  try { localStorage.removeItem(pendingUploadKey(userId)); } catch {}
}

async function pollUpload(uploadId, control) {
    let failures = 0;
    while (!control.settled) {
      await new Promise((resolve) => setTimeout(resolve, 700));
      if (control.settled) break;
      try {
        const response = await apiFetch(`/api/uploads/${encodeURIComponent(uploadId)}`, { signal: AbortSignal.timeout(15000) });
        if (response.ok) {
          const progress = await readJSON(response);
          failures = 0;
          renderProgress(progress);
          if (progress.state === "error") return { error: progress.message || "导入失败", terminal: true };
          if (progress.state === "done" && progress.result) return { result: progress.result };
        } else if (control.accepted && response.status === 404) {
          return { error: "导入任务记录已失效，请刷新后检查来源，再决定是否重新上传。", terminal: true };
        } else if (response.status === 401 || response.status === 403) {
          return { error: "当前登录或笔记本权限已失效，请重新登录后检查来源。" };
        } else if (control.accepted && ++failures >= 10) {
          return { error: "暂时无法取得导入进度，请刷新后查看来源，避免重复上传。" };
        }
      } catch (error) {
        if (control.accepted && ++failures >= 10) return { error: "连接暂时中断，请刷新后查看来源，避免重复上传。" };
      }
    }

}

async function showUploadSuccess(result, notebookId) {
  dom.uploadForm.reset();
  await loadNotebooks(notebookId);
  setStatus(dom.notebookStatus, `已导入 ${result.imported.length} 篇 Markdown 来源。`, "success");
  setUploading(false);
  closeUploadDialog();
  dom.uploadProgress.hidden = true;
}

function showUploadError(error) {
  setStatus(dom.notebookStatus, `导入失败：${error.message}`, "error");
  dom.uploadProgressText.dataset.kind = "error";
  dom.uploadProgressText.textContent = error.message;
  dom.uploadBar.dataset.indeterminate = "false";
  dom.uploadBar.style.width = "0";
}

async function restorePendingUpload() {
  const userId = state.principal?.user_id;
  if (!userId || state.principal?.guest || state.uploading) return;
  let pending;
  try { pending = JSON.parse(localStorage.getItem(pendingUploadKey(userId)) || "null"); }
  catch { forgetUpload(userId); return; }
  if (!pending) return;
  if (typeof pending.uploadId !== "string" || typeof pending.notebookId !== "string" ||
      !state.notebooks.some(book => book.id === pending.notebookId && book.writable)) {
    forgetUpload(userId); return;
  }
  try {
    await setActiveNotebook(pending.notebookId);
    openUploadDialog();
    setUploading(true);
    renderProgress({ stage: "恢复后台导入进度", state: "running" });
    const outcome = await pollUpload(pending.uploadId, { settled: false, accepted: true });
    if (outcome?.terminal) forgetUpload(userId);
    if (outcome?.error) throw new Error(outcome.error);
    if (!outcome?.result) throw new Error("没有取得完整导入结果，请检查来源。");
    forgetUpload(userId);
    await showUploadSuccess(outcome.result, pending.notebookId);
  } catch (error) {
    showUploadError(error);
  } finally {
    setUploading(false);
  }
}

dom.uploadForm.onsubmit = async (event) => {
  event.preventDefault();
  if (state.uploading || !permitted("import_document") || !activeNotebook()?.writable) return;

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

  const control = { settled: false, accepted: false };
  const userId = state.principal?.user_id;
  const poller = pollUpload(uploadId, control);

  try {
    const response = await uploadWithProgress(
      `/api/notebooks/${encodeURIComponent(notebookId)}/files?upload_id=${encodeURIComponent(uploadId)}&background=true`,
      formData
    );
    let result = await readJSON(response);
    if (!response.ok) throw new Error(result.detail || "导入失败");
    if (response.status === 202) {
      control.accepted = true;
      rememberUpload(userId, notebookId, uploadId);
      const outcome = await poller;
      if (outcome?.terminal) forgetUpload(userId);
      if (outcome?.error) throw new Error(outcome.error);
      if (!outcome?.result) throw new Error("没有取得完整导入结果，请刷新后检查来源。");
      result = outcome.result;
    }

    forgetUpload(userId);
    await showUploadSuccess(result, notebookId);
  } catch (error) {
    showUploadError(error);
  } finally {
    control.settled = true;
    await poller;
    setUploading(false);
  }
};

$("admin-identity").onclick = async () => {
  if (!state.principal || state.principal.role === "guest") return;
  const userId = state.principal.user_id;
  setStatus(dom.notebookStatus, `用户ID：${userId}`);
  try { await navigator.clipboard.writeText(userId); setStatus(dom.notebookStatus, `用户ID已复制：${userId}`, "success"); } catch {}
};

// 笔记本成员以已登录账号的用户 ID 识别。
async function loadMembers(notebookId) {
  const [response, targetResponse] = await Promise.all([apiFetch(`/api/notebooks/${encodeURIComponent(notebookId)}/members`), apiFetch(`/api/notebooks/${encodeURIComponent(notebookId)}/share-targets`)]);
  const payload = await readJSON(response);
  const targetsPayload = await readJSON(targetResponse);
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "成员加载失败");
  if (!targetResponse.ok) throw new Error(typeof targetsPayload.detail === "string" ? targetsPayload.detail : "可分享账号加载失败");
  const targetSelect = $("member-user-id");
  targetSelect.replaceChildren();
  for (const target of (targetsPayload.users || [])) { const option = document.createElement("option"); option.value = target.id; option.textContent = target.username || target.id; targetSelect.append(option); }
  const list = $("members-list");
  list.replaceChildren();
  const labels = {viewer: "查看者", editor: "编辑者"};
  for (const member of payload.members) {
    const row = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = `${member.user_id} · ${labels[member.role] || member.role} `;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "移除";
    remove.onclick = async () => {
      remove.disabled = true;
      try {
        const result = await apiFetch(`/api/notebooks/${encodeURIComponent(notebookId)}/members/${encodeURIComponent(member.user_id)}`, {method: "DELETE"});
        if (!result.ok) throw new Error("移除失败或权限已变更");
        await loadNotebooks();
        if (permitted("manage_members") && state.activeId === notebookId) await loadMembers(notebookId);
        else $("members-dialog").close();
      } catch (error) { $("members-status").textContent = error.message; }
      finally { remove.disabled = false; }
    };
    row.append(label, remove);
    list.append(row);
  }
  if (!payload.members.length) {
    const row = document.createElement("li");
    row.textContent = "尚未添加成员，仅管理员可访问。";
    list.append(row);
  }
}
$("open-members").onclick = async () => {
  if (!permitted("manage_members")) return;
  const notebookId = state.activeId;
  $("members-dialog").dataset.notebookId = notebookId;
  $("members-status").textContent = "选择账号并设置其在本笔记本中的权限。";
  $("members-dialog").showModal();
  try { await loadMembers(notebookId); }
  catch (error) { $("members-status").textContent = error.message; }
};
$("close-members").onclick = () => $("members-dialog").close();
$("member-form").onsubmit = async (event) => {
  event.preventDefault();
  const notebookId = $("members-dialog").dataset.notebookId;
  if (notebookId !== state.activeId || !permitted("manage_members")) return;
  const button = event.submitter;
  if (button) button.disabled = true;
  try {
    const userId = $("member-user-id").value;
    const response = await apiFetch(`/api/notebooks/${encodeURIComponent(notebookId)}/members/${encodeURIComponent(userId)}`, {
      method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify({role: $("member-role").value}),
    });
    const payload = await readJSON(response);
    if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "成员设置失败");
    $("members-status").textContent = "笔记本访问权限已保存。";
    await loadMembers(notebookId);
  } catch (error) { $("members-status").textContent = error.message; }
  finally { if (button) button.disabled = false; }
};

// ---------------------------------------------------------------- 启动

apiFetch("/api/auth/session")
  .then(async (response) => {
    if (!response.ok) throw new Error("管理员会话已失效，请重新登录。");
    const session = await readJSON(response);
    state.principal = session;
    applyPermissions();
    await loadNotebooks();
    restorePendingUpload();
  })
  .catch((error) => {
    state.principal = null;
    applyPermissions();
    setStatus(dom.notebookStatus, error.message, "error");
  });

$("auth-open").onclick = () => { $("auth-status").textContent = ""; $("auth-dialog").showModal(); };
$("auth-close").onclick = () => $("auth-dialog").close();
let registerMode = false;
$("auth-mode-toggle").onclick = () => {
  registerMode = !registerMode;
  $("auth-title").textContent = registerMode ? "创建 RAGnotebook 账号" : "登录 RAGnotebook";
  $("auth-submit").textContent = registerMode ? "注册并登录" : "登录";
  $("auth-mode-toggle").textContent = registerMode ? "返回登录" : "创建账号";
  $("auth-password").autocomplete = registerMode ? "new-password" : "current-password";
};
$("auth-form").onsubmit = async (event) => {
  event.preventDefault();
  const username = $("auth-username").value.trim();
  const password = $("auth-password").value;
  const button = $("auth-submit"); button.disabled = true;
  try {
    if (registerMode) {
      const registered = await apiFetch("/api/auth/register", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username,password})});
      const registration = await registered.json();
      if (!registered.ok) throw new Error(typeof registration.detail === "string" ? registration.detail : "注册失败");
    }
    const response = await apiFetch("/api/auth/login", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username,password})});
    const payload = await readJSON(response);
    if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "登录失败");
    $("auth-dialog").close(); $("auth-password").value = "";
    state.principal = null; state.conversationListLoaded = false; state.conversations.clear(); state.savedConversations = [];
    state.transcripts.clear(); state.sessions.clear(); state.drafts.clear();
    const sessionResponse = await apiFetch("/api/auth/session");
    state.principal = await readJSON(sessionResponse); applyPermissions(); refreshPublicStatus(); await loadNotebooks(state.activeId || "");
    restorePendingUpload();
  } catch (error) { $("auth-status").textContent = error.message; }
  finally { button.disabled = false; }
};
$("admin-logout").onclick = async () => {
  const button = $("admin-logout"); button.disabled = true;
  try {
    const response = await apiFetch("/api/auth/logout", {method:"POST"});
    if (!response.ok) throw new Error("退出登录失败，请稍后重试。");
    state.principal = null; state.conversationListLoaded = false; state.conversations.clear(); state.savedConversations = [];
    state.transcripts.clear(); state.sessions.clear(); state.drafts.clear();
    const session = await apiFetch("/api/auth/session"); state.principal = await session.json();
    applyPermissions(); refreshPublicStatus(); await loadNotebooks(state.defaultIds[0] || "cmrc2018-demo");
  } catch (error) { setStatus(dom.notebookStatus, error.message, "error"); }
  finally { button.disabled = false; }
};

apiFetch("/api/demo")
  .then((response) => {
    if (!response.ok) throw new Error("demo unavailable");
    return readJSON(response);
  })
  .then((dataset) => {
    dom.demoStatus.textContent = `${dataset.name}：${dataset.imported}/${dataset.documents} 篇 · ${dataset.question_count} 个问题`;
  })
  .catch(() => {
    dom.demoStatus.textContent = "演示知识库状态不可用";
  });

applyPermissions();


async function loadAdminUsers() {
  const response = await apiFetch("/api/admin/users");
  const payload = await readJSON(response);
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "账号列表加载失败");
  const list = $("admin-users-list"); list.replaceChildren();
  for (const user of (payload.users || [])) {
    const row = document.createElement("li");
    const label = document.createElement("span"); label.textContent = `${user.username || user.user_id} · ${user.is_active === false || user.active === false ? "已停用" : "正常"}`;
    const button = document.createElement("button"); button.type = "button"; button.textContent = user.is_active === false || user.active === false ? "启用" : "停用";
    button.onclick = async () => {
      button.disabled = true;
      try {
        const response = await apiFetch(`/api/admin/users/${encodeURIComponent(user.user_id || user.id)}`, {method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({active:user.is_active === false || user.active === false})});
        if (!response.ok) throw new Error("账号状态更新失败");
        await loadAdminUsers();
      } catch (error) { $("admin-users-status").textContent = error.message; }
      finally { button.disabled = false; }
    };
    row.append(label,button); list.append(row);
  }
}
$("open-admin-users").onclick = async () => {
  if (state.principal?.role !== "admin") return;
  $("admin-users-status").textContent = ""; $("admin-users-dialog").showModal();
  try { await loadAdminUsers(); } catch (error) { $("admin-users-status").textContent = error.message; }
};
$("close-admin-users").onclick = () => $("admin-users-dialog").close();
async function loadModels(providerId = "") {
  const providerSelect = $("model-provider");
  if (!providerSelect.options.length) {
    const response = await apiFetch("/api/models/providers"); const payload = await readJSON(response);
    if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "Provider 列表加载失败");
    for (const provider of payload.providers || []) {
      const option = document.createElement("option"); option.value = provider.id || provider.provider_id; option.textContent = provider.name || option.value; providerSelect.append(option);
    }
  }
  if (providerId) providerSelect.value = providerId;
  const current = providerSelect.value;
  const response = await apiFetch(`/api/models/${encodeURIComponent(current)}`); const payload = await readJSON(response);
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "Model 列表加载失败");
  const modelSelect = $("model-choice"); modelSelect.replaceChildren();
  for (const model of payload.models || []) { const option = document.createElement("option"); option.value = model.id || model.model_id; option.textContent = model.name || option.value; modelSelect.append(option); }
  const settingsResponse = await apiFetch("/api/models/settings");
  if (settingsResponse.ok) { const settings = await readJSON(settingsResponse); if (settings.provider_id === current) modelSelect.value = settings.model_id; }
}
$("open-model-admin").onclick = async () => {
  if (state.principal?.role !== "admin") return;
  $("model-admin-status").textContent = ""; $("model-admin-dialog").showModal();
  try { await loadModels(); } catch (error) { $("model-admin-status").textContent = error.message; }
};
$("model-provider").onchange = () => loadModels().catch((error) => { $("model-admin-status").textContent = error.message; });
$("close-model-admin").onclick = () => $("model-admin-dialog").close();
$("model-admin-form").onsubmit = async (event) => {
  event.preventDefault(); const button = event.submitter; if (button) button.disabled = true;
  try {
    const response = await apiFetch("/api/models/settings", {method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({provider_id:$("model-provider").value,model_id:$("model-choice").value})});
    const payload = await readJSON(response); if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "模型设置未保存");
    $("model-admin-status").textContent = "已应用，后续问答将使用此模型。";
    const configResponse = await apiFetch("/api/llm/config"); if (configResponse.ok) { const config = await readJSON(configResponse); state.modelProvider = config.provider; $("server-model-status").textContent = `模型：${config.provider || "Mock"} · ${config.model || "默认"}`; }
  } catch (error) { $("model-admin-status").textContent = error.message; }
  finally { if (button) button.disabled = false; }
};
