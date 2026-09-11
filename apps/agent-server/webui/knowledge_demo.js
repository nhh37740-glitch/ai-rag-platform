const log = document.getElementById("log");
const form = document.getElementById("f");
const message = document.getElementById("m");
const demoStatus = document.getElementById("demo-status");
const examples = document.getElementById("examples");
const notebookList = document.getElementById("notebook-list");
const notebookStatus = document.getElementById("notebook-status");
const createNotebookForm = document.getElementById("create-notebook-form");
const notebookName = document.getElementById("notebook-name");
const notebookDescription = document.getElementById("notebook-description");
const uploadForm = document.getElementById("upload-form");
const uploadNotebook = document.getElementById("upload-notebook");
const uploadFiles = document.getElementById("upload-files");

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

function selectedKnowledgeBases() {
  return [...notebookList.querySelectorAll("input[type=checkbox]:checked")].map((input) => input.value);
}

function renderNotebooks(payload, preferredId = "") {
  const previouslySelected = new Set(selectedKnowledgeBases());
  notebookList.replaceChildren();
  uploadNotebook.replaceChildren();

  payload.notebooks.forEach((notebook) => {
    const label = document.createElement("label");
    label.className = "notebook-option";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = notebook.id;
    checkbox.checked = preferredId === notebook.id
      || previouslySelected.has(notebook.id)
      || (!previouslySelected.size && payload.default_ids.includes(notebook.id));
    const details = document.createElement("span");
    const name = document.createElement("strong");
    name.textContent = notebook.name;
    const summary = document.createElement("small");
    summary.textContent = `${notebook.document_count} 篇 Markdown 文档${notebook.description ? ` · ${notebook.description}` : ""}`;
    details.append(name, summary);
    label.append(checkbox, details);
    notebookList.appendChild(label);

    if (notebook.writable) {
      const option = document.createElement("option");
      option.value = notebook.id;
      option.textContent = notebook.name;
      option.selected = preferredId === notebook.id;
      uploadNotebook.appendChild(option);
    }
  });

  const canUpload = uploadNotebook.options.length > 0;
  uploadNotebook.disabled = !canUpload;
  uploadFiles.disabled = !canUpload;
  uploadForm.querySelector("button").disabled = !canUpload;
  if (!canUpload) notebookStatus.textContent = "先创建一个笔记本，再上传文档。";
}

async function loadNotebooks(preferredId = "") {
  const response = await fetch("/api/notebooks");
  if (!response.ok) throw new Error("知识库列表加载失败");
  const payload = await response.json();
  renderNotebooks(payload, preferredId);
}

createNotebookForm.onsubmit = async (event) => {
  event.preventDefault();
  notebookStatus.textContent = "正在创建笔记本…";
  try {
    const response = await fetch("/api/notebooks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: notebookName.value, description: notebookDescription.value }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "创建失败");
    createNotebookForm.reset();
    await loadNotebooks(result.id);
    notebookStatus.textContent = `已创建“${result.name}”，现在可以上传文档。`;
  } catch (error) {
    notebookStatus.textContent = `创建失败：${error.message}`;
  }
};

uploadForm.onsubmit = async (event) => {
  event.preventDefault();
  const chosenFiles = [...uploadFiles.files];
  if (!chosenFiles.length || !uploadNotebook.value) return;
  const formData = new FormData();
  chosenFiles.forEach((file) => formData.append("files", file));
  notebookStatus.textContent = `正在转换并导入 ${chosenFiles.length} 个文件…`;
  try {
    const response = await fetch(`/api/notebooks/${encodeURIComponent(uploadNotebook.value)}/files`, {
      method: "POST",
      body: formData,
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "导入失败");
    const notebookId = uploadNotebook.value;
    uploadForm.reset();
    await loadNotebooks(notebookId);
    notebookStatus.textContent = `已转换并导入 ${result.imported.length} 篇 Markdown 文档。`;
  } catch (error) {
    notebookStatus.textContent = `导入失败：${error.message}`;
  }
};

loadNotebooks().catch((error) => {
  notebookStatus.textContent = error.message;
});

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
  const knowledgeBaseIds = selectedKnowledgeBases();
  show(`你: ${question}`);
  message.value = "";
  show("...");
  const url = `/api/chat/stream?message=${encodeURIComponent(question)}&session_id=s1&user_id=anon&knowledge_base_ids=${encodeURIComponent(knowledgeBaseIds.join(","))}`;
  const events = new EventSource(url);
  events.onmessage = (eventMessage) => {
    const result = JSON.parse(eventMessage.data);
    show(`Agent: ${result.answer}\n[trace: ${result.trace_id || ""}]\n`);
    events.close();
    loadNotebooks().catch((error) => {
      notebookStatus.textContent = error.message;
    });
  };
  events.onerror = () => {
    events.close();
    show("错误: 连接中断");
  };
};
