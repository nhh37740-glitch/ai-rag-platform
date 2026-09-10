const log = document.getElementById("log");
const form = document.getElementById("f");
const message = document.getElementById("m");
const demoStatus = document.getElementById("demo-status");
const examples = document.getElementById("examples");

const fallbackQuestions = [
  { topic: "科学", title: "静电感应", question: "什么是静电感应？" },
  { topic: "历史", title: "王处直", question: "王处直的字是什么？" },
  { topic: "军事", title: "海军十字勋章", question: "海军十字勋章可以授予哪些人？" },
];

function show(text) {
  log.innerText += `${text}\n`;
}

function renderExamples(questions) {
  examples.replaceChildren();
  questions.forEach((item) => {
    const suggestion = typeof item === "string" ? { question: item, topic: "知识库", title: "" } : item;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "example-question";
    const source = document.createElement("span");
    source.className = "example-source";
    source.textContent = `${suggestion.topic} · ${suggestion.title}`;
    const question = document.createElement("span");
    question.textContent = suggestion.question;
    button.append(source, question);
    button.onclick = () => {
      message.value = suggestion.question;
      message.focus();
    };
    examples.appendChild(button);
  });
}

fetch("/api/demo")
  .then((response) => {
    if (!response.ok) throw new Error("demo status unavailable");
    return response.json();
  })
  .then((dataset) => {
    demoStatus.textContent = `${dataset.name} 已从 ${dataset.knowledge_base} 导入：${dataset.imported}/${dataset.documents} 篇文档，共 ${dataset.question_count} 个可用问题。`;
    renderExamples(dataset.suggested_questions?.length ? dataset.suggested_questions : fallbackQuestions);
  })
  .catch(() => {
    demoStatus.textContent = "演示知识库状态暂不可用";
    renderExamples(fallbackQuestions);
  });

form.onsubmit = (event) => {
  event.preventDefault();
  const question = message.value.trim();
  if (!question) return;
  show(`你: ${question}`);
  message.value = "";
  show("...");
  const url = `/api/chat/stream?message=${encodeURIComponent(question)}&session_id=s1&user_id=anon`;
  const events = new EventSource(url);
  events.onmessage = (eventMessage) => {
    const result = JSON.parse(eventMessage.data);
    show(`Agent: ${result.answer}\n[trace: ${result.trace_id || ""}]\n`);
    events.close();
  };
  events.onerror = () => {
    events.close();
    show("错误: 连接中断");
  };
};
