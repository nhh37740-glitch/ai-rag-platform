const log = document.getElementById("log");
const form = document.getElementById("f");
const message = document.getElementById("m");
const demoStatus = document.getElementById("demo-status");
const examples = document.getElementById("examples");

const fallbackQuestions = [
  "什么是静电感应？",
  "王处直的字是什么？",
  "海军十字勋章可以授予哪些人？",
];

function show(text) {
  log.innerText += `${text}\n`;
}

function renderExamples(questions) {
  examples.replaceChildren();
  questions.slice(0, 8).forEach((question) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = question;
    button.onclick = () => {
      message.value = question;
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
    demoStatus.textContent = `${dataset.name} 已导入知识库：${dataset.imported}/${dataset.documents} 篇，提供 ${dataset.question_count} 个示例问题（仅用于项目展示）`;
    renderExamples(dataset.questions || fallbackQuestions);
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
