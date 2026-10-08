"use strict";

(() => {
  const byId = (id) => document.getElementById(id);
  const state = { questions: [], selected: "", busy: false, traceId: "", metadata: null, retry: "metadata" };
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
    byId("ask-button").disabled = busy || !state.selected;
    byId("retry-button").disabled = busy;
    byId("trace-retry-button").disabled = busy;
    byId("ask-button").textContent = busy ? "正在等待服务器…" : "开始问答 ↗";
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
      422: "精选问题校验失败。请重新加载页面，选择服务器提供的问题后重试。",
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
    const response = await fetch(apiURL(path), { credentials: "omit", cache: "no-store", ...options });
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
      const data = await request("api/demo");
      if (data.public_demo !== true || data.read_only !== true) throw new Error("服务器未启用公开只读演示，无法在此页面发起请求。");
      const questions = Array.isArray(data.suggested_questions) ? data.suggested_questions.filter((item) => item && typeof item.question === "string" && item.question.trim()) : [];
      if (!questions.length) throw new Error("服务器没有提供精选问题，请稍后重新加载。");
      state.metadata = data;
      state.questions = questions;
      state.selected = questions[0].question;
      showModes(data);
      byId("dataset").textContent = `${data.name || "CMRC2018 公开中文资料"} · 已导入 ${data.imported ?? "未知"}/${data.documents ?? "未知"} 篇 · ${questions.length} 个精选问题`;
      const fieldset = byId("question-options");
      fieldset.replaceChildren(node("legend", "选择精选问题", "visually-hidden"));
      questions.forEach((item, index) => {
        const label = node("label", undefined, "question-option");
        const radio = node("input");
        radio.type = "radio";
        radio.name = "question";
        radio.value = item.question;
        radio.checked = index === 0;
        radio.addEventListener("change", () => { state.selected = item.question; });
        const text = node("span");
        text.append(node("span", item.topic || "公开资料", "topic"), node("span", item.question, "question-text"));
        label.append(radio, text);
        fieldset.append(label);
      });
      status("已就绪。选择问题并点击「开始问答」。");
    } catch (error) {
      status("演示配置加载失败。");
      byId("dataset").textContent = "服务器知识库状态暂不可用";
      showError(error.message || "连接失败，请重试。", "metadata");
    } finally { setBusy(false); }
  }
  function resetResult(question) {
    state.traceId = "";
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
    byId("source-count").textContent = "等待检索";
    byId("span-count").textContent = "等待执行";
    byId("trace-note").textContent = "";
    byId("trace-retry-button").hidden = true;
    byId("trace-details").hidden = true;
    byId("trace-json").textContent = "";
  }
  function renderAnswer(data) {
    showModes(data);
    byId("cache-badge").textContent = data.cache_hit === true ? "缓存命中 · 复用原结果" : data.cache_hit === false ? "本次新执行 · 未命中缓存" : "缓存状态未提供";
    byId("answer-note").textContent = data.provider === "mock" ? "Mock 离线流程输出：可核对工具返回的检索数据，不代表真实模型回答质量。" : "DeepSeek 本次输出；请结合下方实际来源核对内容。";
    byId("answer-content").className = "answer-content";
    byId("answer-content").textContent = typeof data.answer === "string" ? data.answer : JSON.stringify(data.answer, null, 2);
    if (data.provider === "mock" && typeof data.answer === "string") {
      try {
        const parsed = JSON.parse(data.answer);
        byId("answer-content").textContent = JSON.stringify(parsed, null, 2);
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
    byId("source-count").textContent = `${sources.length} 条实际命中`;
    sources.forEach(({ hit, span }, index) => {
      const article = node("article", undefined, "source-card");
      article.append(node("h3", `${index + 1}. ${hit.title || "未提供标题"}`), node("p", hit.source_id || "未提供 source_id", "source-id"), node("p", hit.text_preview || "此记录没有提供原文片段。", "source-preview"));
      const score = typeof hit.score === "number" && Number.isFinite(hit.score) ? hit.score.toFixed(4) : "未提供";
      article.append(node("p", `工具：${span.meta?.tool || "rag"} · 检索分数：${score} · 非置信度`, "source-meta"));
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
      byId("source-count").textContent = "记录暂不可用";
      byId("span-count").textContent = "记录暂不可用";
      byId("trace-retry-button").hidden = false;
      return false;
    } finally { byId("trace-retry-button").disabled = false; }
  }
  async function ask() {
    if (state.busy || !state.selected || !state.questions.some((item) => item.question === state.selected)) return;
    const question = state.selected;
    byId("error-box").hidden = true;
    setBusy(true);
    resetResult(question);
    status("请求已发送。正在等待服务器完成，真实模型调用可能需要一段时间。", "loading");
    try {
      const data = await request("api/demo/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }) });
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
      byId("source-count").textContent = "未取得记录";
      byId("span-count").textContent = "未取得记录";
      status("本次请求失败。");
      showError(error.message || "网络连接失败，请检查连接后重试。", "question");
    } finally { setBusy(false); }
  }
  byId("question-form").addEventListener("submit", (event) => { event.preventDefault(); ask(); });
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
  loadMetadata();
})();
