const form = document.getElementById("login-form");
const submit = document.getElementById("submit");
const status = document.getElementById("status");
const password = document.getElementById("password");
let csrf = null;

async function refreshCsrf() {
  submit.disabled = true;
  csrf = null;
  const response = await fetch("auth/csrf", { cache: "no-store" });
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || "登录服务暂时不可用。");
  csrf = result;
  submit.disabled = false;
}

if (window.location.protocol !== "https:") {
  submit.disabled = true;
  document.getElementById("username").disabled = true;
  password.disabled = true;
  status.textContent = "请通过 HTTPS 管理入口登录。";
} else {
  refreshCsrf().then(() => { status.textContent = "请输入拥有者账号和密码。"; })
    .catch((error) => { status.textContent = error.message; });
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!csrf || submit.disabled) return;
  submit.disabled = true;
  status.textContent = "正在验证账号…";
  try {
    const response = await fetch("auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json", [csrf.headerName]: csrf.token },
      body: JSON.stringify({ username: document.getElementById("username").value, password: password.value }),
    });
    password.value = "";
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "登录失败。");
    window.location.assign(result.redirect);
  } catch (error) {
    password.value = "";
    status.textContent = error.message;
    try { await refreshCsrf(); } catch (failure) { status.textContent = failure.message; }
  } finally {
    if (csrf) submit.disabled = false;
  }
});
