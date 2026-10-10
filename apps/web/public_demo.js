"use strict";

(() => {
  const byId = (id) => document.getElementById(id);
  const state = { questions: [], selected: "", busy: false, traceId: "", metadata: null, retry: "metadata", temporaryKey: "", principal: null, documents: [], documentId: "", documentOffset: 0, documentNext: null, documentHistory: [], documentBusy: false, documentVersion: 0 };
  const secureKeyPage = location.protocol === "https:" || (window.isSecureContext && ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname));
  // Relative URLs work at both / and /projects/apps/rag/; nginx need not rewrite HTML.
  const apiURL = (path) => new URL(path, document.baseURI);
  const node = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = String(text);
    if (className) element.className = className;
    return element;
  };
  function status(text, kind = "") {
    byId("request-status").textContent = text;
    byId("request-status").dataset.kind = kind;
  }
  function showError(message, retry) {
    state.retry = retry;
    byId("error-message").textContent = message;
    byId("error-box").hidden = false;
    byId("retry-button").textContent = retry === "metadata" ? "重新加载问题" : "重试这个问题";
  }
  function setBusy(busy) {
    state.busy = busy;
    byId("question-options").disabled = busy || !state.questions.length;
    byId("ask-button").disabled = busy || !state.metadata || !byId("question-input").value.trim();
    byId("question-input").disabled = busy || !state.metadata;
    byId("retry-button").disabled = busy;
    byId("trace-retry-button").disabled = busy;
    byId("apply-key").disabled = busy || !secureKeyPage;
    byId("clear-key").disabled = busy;
    byId("ask-button").setAttribute("aria-label", busy ? "正在等待服务器" : "开始问答");
    byId("ask-button").title = busy ? "正在等待服务器" : "开始问答";
    byId("answer").setAttribute("aria-busy", String(busy));
  }
  function showModes(data) {
    const provider = byId("provider-badge");
    const embedding = byId("embedding-badge");
    provider.textContent = data.provider === "deepseek" ? "模型：DeepSeek · 真实调用" : data.provider === "mock" ? "模型：Mock · 离线流程" : `模型：${data.provider || "未提供"}`;
    provider.dataset.kind = data.provider === "deepseek" ? "" : "warning";
    embedding.textContent = data.embedding === "hash" ? "检索：hash · 离线向量" : `检索：${data.embedding || "未提供"}`;
    embedding.dataset.kind = data.embedding === "hash" ? "warning" : "";
    byId("readonly-badge").textContent = data.read_only === true ? "公开只读" : "只读状态未确认";
  }
  function errorMessage(response, payload) {
    const messages = {
      422: "请检查问题或分页参数；问题须为 1 到 1024 字。",
      429: "服务器正在处理另一个请求，请稍后重试。",
      502: "本次模型或检索未能提供有效结果，请重试；失败结果不会缓存。",
      504: "本次执行超时，请稍后重试；此处没有生成可用答案。",
      403: "请求被公开演示边界拒绝，请重新加载页面。",
      404: "演示接口暂不可用，请稍后重试。",
    };
    const detail = typeof payload?.detail === "string" ? payload.detail : "";
    return `${messages[response.status] || "服务器返回错误，请稍后重试。"}（HTTP ${response.status}）${detail ? ` ${detail}` : ""}`;
  }
  async function request(path, options = {}) {
    const response = await fetch(apiURL(path), { credentials: "same-origin", cache: "no-store", ...options });
    let payload;
    try { payload = await response.json(); } catch {
      throw new Error(response.ok ? "服务器响应无法读取，请重试。" : errorMessage(response));
    }
    if (!response.ok) throw new Error(errorMessage(response, payload));
    return payload;
  }
  async function loadMetadata() {
    byId("error-box").hidden = true;
    setBusy(true);
    status("正在读取服务器配置与精选问题…", "loading");
    try {
      const [data, notebooks, documents] = await Promise.all([
        request("api/demo"), request("api/notebooks"), request("api/notebooks/cmrc2018-demo/documents"),
      ]);
      if (data.public_demo !== true || data.read_only !== true) throw new Error("服务器未启用公开只读演示，无法在此页面发起请求。");
      const questions = Array.isArray(data.suggested_questions) ? data.suggested_questions.filter((item) => item && typeof item.question === "string" && item.question.trim()) : [];
      state.metadata = data;
      state.questions = questions;
      state.selected = byId("question-input").value.trim();
      state.documents = Array.isArray(documents.documents) ? documents.documents : [];
      renderDocuments();
      showModes(data);
      const publicNotebook = (notebooks.notebooks || []).find((item) => item.id === "cmrc2018-demo");
      byId("dataset").textContent = `${publicNotebook?.name || data.name || "CMRC2018 公开中文资料"} · ${state.documents.length} 篇 · ${questions.length} 个精选问题`;
      const fieldset = byId("question-options");
      fieldset.replaceChildren(node("legend", "选择精选问题", "visually-hidden"));
      questions.forEach((item, index) => {
        const label = node("label", undefined, "question-option");
        const radio = node("input");
        radio.type = "radio";
        radio.name = "question";
        radio.value = item.question;
        radio.checked = item.question === state.selected;
        radio.addEventListener("change", () => { state.selected = item.question; byId("question-input").value = item.question; setBusy(state.busy); byId("question-input").focus(); });
        const text = node("span");
        text.append(node("span", item.topic || "公开资料", "topic"), node("span", item.question, "question-text"));
        label.append(radio, text);
        fieldset.append(label);
      });
      status("已就绪。输入问题或选择精选题，点击发送。");
    } catch (error) {
      status("演示配置加载失败。");
      byId("dataset").textContent = "服务器知识库状态暂不可用";
      showError(error.message || "连接失败，请重试。", "metadata");
    } finally { setBusy(false); }
  }
  async function loadIdentity() {
    try {
      const principal = await request("api/auth/session");
      state.principal = principal;
      byId("identity-badge").textContent = principal.role === "admin" && principal.administrator === true ? "管理员 · 公开浏览" : "游客 · 可阅读与提问";
      if (principal.role === "admin" && principal.administrator === true) {
        byId("admin-login-link").textContent = "管理员工作区";
        byId("admin-login-link").href = "admin/";
      }
    } catch {
      byId("identity-badge").textContent = "身份暂不可确认";
    }
  }
  function documentId(sourceId) {
    if (typeof sourceId !== "string" || !sourceId.startsWith("cmrc2018-demo/")) return "";
    const id = sourceId.slice("cmrc2018-demo/".length);
    return id && !/[\/\\]/.test(id) && id !== "." && id !== ".." ? id : "";
  }
  function documentButton(sourceId, text) {
    const id = documentId(sourceId);
    if (!id) return null;
    const button = node("button", text, "public-secondary");
    button.type = "button";
    button.addEventListener("click", () => openDocument(id));
    return button;
  }
  function renderDocuments() {
    const list = byId("document-list");
    list.replaceChildren();
    for (const item of state.documents) {
      const button = documentButton(item.source_id, `${item.title || "公开文档"} · ${item.chunks ?? item.chunk_count ?? 0} 块`);
      if (button) { button.classList.add("document-list-button"); list.append(button); }
    }
    byId("source-count").textContent = String(list.children.length);
    if (!list.children.length) list.append(node("p", "暂无可阅读的公开文档。", "source-empty"));
  }
  async function openDocument(id) {
    state.documentId = id;
    state.documentHistory = [];
    byId("document-title").textContent = "文档原文";
    if (!byId("document-dialog").open) byId("document-dialog").showModal();
    await loadDocumentPage(0);
  }
  async function loadDocumentPage(offset) {
    const version = ++state.documentVersion;
    state.documentBusy = true;
    byId("previous-document-page").disabled = true;
    byId("next-document-page").disabled = true;
    byId("document-page-status").textContent = "正在读取原文…";
    byId("document-content").replaceChildren();
    try {
      const page = await request(`api/demo/documents/${encodeURIComponent(state.documentId)}?offset=${offset}`);
      if (version !== state.documentVersion) return;
      if (!Array.isArray(page.contexts) || !Number.isInteger(page.offset) || !Number.isInteger(page.total_chunks)) throw new Error("原文响应不完整，请重新打开文档。");
      state.documentOffset = page.offset;
      state.documentNext = page.truncated === true && Number.isInteger(page.next_offset) && page.next_offset > page.offset ? page.next_offset : null;
      byId("document-title").textContent = page.title || state.documentId;
      for (const text of page.contexts) byId("document-content").append(node("p", text));
      byId("document-page-status").textContent = page.contexts.length ? `第 ${page.offset + 1}–${page.offset + page.contexts.length} 块，共 ${page.total_chunks} 块` : `暂无原文，共 ${page.total_chunks} 块`;
    } catch (error) {
      if (version !== state.documentVersion) return;
      state.documentNext = null;
      byId("document-page-status").textContent = error.message || "原文读取失败，请重新打开。";
    } finally {
      if (version === state.documentVersion) {
        state.documentBusy = false;
        byId("previous-document-page").disabled = !state.documentHistory.length;
        byId("next-document-page").disabled = state.documentNext === null;
      }
    }
  }
  function resetResult(question) {
    state.traceId = "";
    byId("empty-state").hidden = true;
    byId("log").hidden = false;
    byId("user-message").hidden = false;
    byId("question-picker").open = false;
    byId("answered-question").hidden = false;
    byId("answered-question").textContent = question;
    byId("answer-note").textContent = "正在等待实际模型与检索返回；当前接口完成后一次性显示答案。";
    byId("answer-content").className = "answer-content empty";
    byId("answer-content").textContent = "服务器正在执行本次问答…";
    byId("cache-badge").textContent = "等待响应";
    byId("raw-answer-details").hidden = true;
    byId("raw-answer").textContent = "";
    byId("source-list").replaceChildren(node("p", "等待本次实际检索记录。", "empty"));
    byId("execution-list").replaceChildren(node("p", "等待本次真实执行记录。", "empty"));
    byId("evidence-count").textContent = "…";
    byId("span-count").textContent = "等待执行";
    byId("trace-note").textContent = "";
    byId("trace-retry-button").hidden = true;
    byId("trace-details").hidden = true;
    byId("trace-json").textContent = "";
  }
  function renderAnswer(data) {
    showModes(data);
    byId("cache-badge").textContent = data.cache_hit === true ? "缓存命中 · 复用原结果" : data.cache_hit === false ? "本次新执行 · 未命中缓存" : "缓存状态未提供";
    byId("answer-note").textContent = data.provider === "mock" ? "Mock 离线流程输出：可核对工具返回的检索数据，不代表真实模型回答质量。" : (data.cache_hit ? "复用原请求的 DeepSeek 输出；请结合下方原始来源核对内容。" : "DeepSeek 本次输出；请结合下方实际来源核对内容。");
    byId("answer-content").className = "answer-content";
    byId("answer-content").textContent = typeof data.answer === "string" ? data.answer : JSON.stringify(data.answer, null, 2);
    if (data.provider === "mock" && typeof data.answer === "string") {
      try {
        const parsed = JSON.parse(data.answer);
        const hitCount = parsed && Number.isInteger(parsed.hit_count) && parsed.hit_count >= 0 ? parsed.hit_count : null;
        byId("answer-content").textContent = `${hitCount === null ? "本次工具流程已完成。" : `本次检索返回 ${hitCount} 个片段。`}请在左侧核对原文，在右侧查看执行记录。当前离线演示尚未生成自然语言答案。`;
        byId("raw-answer").textContent = data.answer;
        byId("raw-answer-details").hidden = false;
      } catch { /* Plain Mock text is displayed verbatim. */ }
    }
  }
  function elapsed(span) {
    if (typeof span.start_ns !== "number" || typeof span.end_ns !== "number" || span.end_ns < span.start_ns) return "耗时未提供";
    return `${((span.end_ns - span.start_ns) / 1000000).toFixed(1)} ms`;
  }
  function renderTrace(spans) {
    const valid = spans.filter((span) => span && typeof span === "object");
    const ragSpans = valid.filter((span) => span.span === "rag");
    const sources = [];
    for (const span of ragSpans) {
      for (const hit of Array.isArray(span.meta?.hits) ? span.meta.hits : []) {
        if (!hit || typeof hit !== "object") continue;
        sources.push({ hit, span });
      }
    }
    const list = byId("source-list");
    list.replaceChildren();
    byId("evidence-count").textContent = String(sources.length);
    sources.forEach(({ hit, span }, index) => {
      const article = node("article", undefined, "source-card");
      article.append(node("h3", `${index + 1}. ${hit.title || "未提供标题"}`), node("p", hit.source_id || "未提供 source_id", "source-id"), node("p", hit.text_preview || "此记录没有提供原文片段。", "source-preview"));
      const score = typeof hit.score === "number" && Number.isFinite(hit.score) ? hit.score.toFixed(4) : "未提供";
      article.append(node("p", `工具：${span.meta?.tool || "rag"} · 检索分数：${score} · 非置信度`, "source-meta"));
      const open = documentButton(hit.source_id, "打开文档原文");
      if (open) article.append(open);
      list.append(article);
    });
    if (!sources.length) list.append(node("p", "本次 trace 没有提供命中片段；此处不补填来源。", "empty"));
    const stages = valid.filter((span) => ["agent", "llm", "tool", "rag", "retrieval_guard"].includes(span.span));
    const names = { agent: "Agent · 编排请求", llm: "LLM · 模型调用", tool: "Tool · 工具执行", rag: "RAG · 知识库检索", retrieval_guard: "Guard · 检索提醒" };
    const execution = byId("execution-list");
    execution.replaceChildren();
    stages.forEach((span) => {
      const row = node("div", undefined, "span-row");
      row.dataset.status = String(span.status || "unknown");
      row.append(node("span", names[span.span], "span-label"), node("span", elapsed(span), "span-duration"));
      const details = [`状态：${span.status || "未提供"}`];
      if (span.meta?.tool) details.push(`工具：${span.meta.tool}`);
      if (span.meta?.query) details.push(`查询：${span.meta.query}`);
      if (span.meta?.hit_count !== undefined) details.push(`命中：${span.meta.hit_count}`);
      if (span.error) details.push(`错误：${typeof span.error === "string" ? span.error : JSON.stringify(span.error)}`);
      row.append(node("div", details.join(" · "), "span-description"));
      execution.append(row);
    });
    if (!stages.length) execution.append(node("p", "trace 未提供可展示的执行阶段。", "empty"));
    const guards = valid.filter((span) => span.span === "retrieval_guard").length;
    byId("span-count").textContent = `${stages.length} 个阶段${guards ? ` · ${guards} 次提醒` : ""}`;
    byId("trace-note").textContent = `trace_id：${state.traceId}。阶段可能嵌套，耗时不相加。`;
    byId("trace-note").className = "muted trace-id";
    byId("trace-json").textContent = JSON.stringify(spans, null, 2);
    byId("trace-details").hidden = false;
  }
  async function loadTrace() {
    byId("trace-retry-button").disabled = true;
    try {
      const spans = await request(`api/trace/${encodeURIComponent(state.traceId)}`);
      if (!Array.isArray(spans) || !spans.length) throw new Error("本次 trace 尚不可读取或已不在当前进程中。");
      renderTrace(spans);
      byId("trace-retry-button").hidden = true;
      return true;
    } catch (error) {
      byId("trace-note").textContent = `回答已返回，但执行记录读取失败：${error.message || "连接失败"}`;
      byId("evidence-count").textContent = "—";
      byId("span-count").textContent = "记录暂不可用";
      byId("trace-retry-button").hidden = false;
      return false;
    } finally { byId("trace-retry-button").disabled = false; }
  }
  async function ask() {
    if (state.busy || !state.metadata) return;
    const question = byId("question-input").value.trim();
    if (!question || Array.from(question).length > 1024) { status("请输入 1 到 1024 字的问题。", "error"); return; }
    state.selected = question;
    byId("error-box").hidden = true;
    setBusy(true);
    resetResult(question);
    status("请求已发送。正在等待服务器完成，真实模型调用可能需要一段时间。", "loading");
    try {
      const headers = { "Content-Type": "application/json" };
      if (secureKeyPage && state.temporaryKey) headers["x-deepseek-api-key"] = state.temporaryKey;
      const data = await request("api/demo/chat", { method: "POST", headers, body: JSON.stringify({ question }) });
      if (typeof data.answer !== "string" || typeof data.trace_id !== "string" || !data.trace_id || data.read_only !== true) throw new Error("服务器返回的演示结果不完整，请重试。");
      state.traceId = data.trace_id;
      renderAnswer(data);
      status("回答已返回，正在读取实际来源与执行记录…", "loading");
      const complete = await loadTrace();
      status(complete ? (data.cache_hit === true ? "已展示缓存答案及原请求的来源与执行记录。" : "本次执行完成。可以核对回答、来源和各阶段耗时。") : "回答已返回；来源与执行记录暂不可用，可单独重试读取。");
    } catch (error) {
      byId("answer-content").textContent = "本次没有取得可用答案。";
      byId("answer-note").textContent = "请查看请求错误并重试。";
      byId("cache-badge").textContent = "请求失败";
      byId("evidence-count").textContent = "0";
      byId("span-count").textContent = "未取得记录";
      status("本次请求失败。");
      showError(error.message || "网络连接失败，请检查连接后重试。", "question");
    } finally { setBusy(false); }
  }
  byId("temporary-key").disabled = !secureKeyPage;
  if (!secureKeyPage) byId("key-status").textContent = "此 HTTP 页面无法使用临时 key，请从 HTTPS 主页进入。";
  byId("apply-key").addEventListener("click", () => {
    if (!secureKeyPage || state.busy) return;
    state.temporaryKey = byId("temporary-key").value.trim();
    byId("temporary-key").value = "";
    byId("key-status").textContent = state.temporaryKey ? "临时 key 已应用；下次问答使用 DeepSeek，每次执行均不复用共享缓存。" : "未配置，使用 Mock 离线流程。";
    if (state.metadata) showModes({ ...state.metadata, provider: state.temporaryKey ? "deepseek" : state.metadata.provider });
  });
  byId("clear-key").addEventListener("click", () => {
    state.temporaryKey = "";
    byId("temporary-key").value = "";
    byId("key-status").textContent = secureKeyPage ? "已清除，使用 Mock 离线流程。" : "此 HTTP 页面无法使用临时 key，请从 HTTPS 主页进入。";
    if (state.metadata) showModes(state.metadata);
  });
  byId("question-form").addEventListener("submit", (event) => { event.preventDefault(); ask(); });
  byId("question-input").addEventListener("input", () => {
    state.selected = byId("question-input").value.trim();
    document.querySelectorAll('#question-options input[type="radio"]').forEach((radio) => { radio.checked = radio.value === state.selected; });
    setBusy(state.busy);
  });
  byId("question-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); ask(); }
  });
  byId("close-document").addEventListener("click", () => byId("document-dialog").close());
  byId("document-dialog").addEventListener("close", () => { state.documentVersion++; state.documentBusy = false; });
  byId("next-document-page").addEventListener("click", () => {
    if (state.documentBusy || state.documentNext === null) return;
    state.documentHistory.push(state.documentOffset);
    loadDocumentPage(state.documentNext);
  });
  byId("previous-document-page").addEventListener("click", () => {
    if (state.documentBusy || !state.documentHistory.length) return;
    loadDocumentPage(state.documentHistory.pop());
  });
  window.addEventListener("pagehide", () => {
    state.temporaryKey = "";
    byId("temporary-key").value = "";
    byId("key-status").textContent = secureKeyPage ? "未配置，使用 Mock 离线流程。" : "此 HTTP 页面无法使用临时 key，请从 HTTPS 主页进入。";
    if (state.metadata) showModes(state.metadata);
  });
  byId("retry-button").addEventListener("click", () => { state.retry === "metadata" ? loadMetadata() : ask(); });
  byId("trace-retry-button").addEventListener("click", async () => {
    if (!state.busy && state.traceId) {
      setBusy(true);
      status("正在重新读取执行记录…", "loading");
      const complete = await loadTrace();
      status(complete ? "执行记录已读取，可核对本次来源与耗时。" : "执行记录仍不可用，可稍后重试。");
      setBusy(false);
    }
  });
  for (const name of ["sources", "studio"]) {
    const panel = byId(`${name}-panel`);
    const collapse = byId(`collapse-${name}`);
    collapse.addEventListener("click", () => {
      if (window.matchMedia("(max-width: 900px)").matches) {
        panel.classList.remove("mobile-open");
      } else {
        const collapsed = panel.classList.toggle("is-collapsed");
        collapse.setAttribute("aria-expanded", String(!collapsed));
      }
    });
    byId(`show-${name}`).addEventListener("click", () => {
      byId(name === "sources" ? "studio-panel" : "sources-panel").classList.remove("mobile-open");
      panel.classList.add("mobile-open");
    });
  }
  loadMetadata();
  loadIdentity();
})();
