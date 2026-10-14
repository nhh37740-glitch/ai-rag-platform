# GitHub PR 强制门禁设置

本 PR 先以预览方式安装 GitHub Actions 工作流。PR Guard **从默认主分支检出脚本**，不会执行 PR 代码，也不使用 PR 的 Dockerfile/工作流。工作流合入 master 后才能触发稳定的检查。此 PR 不直接修改 Rulesets、Branch Protection 或 Jenkins。

## 仓库所有者需要手动设置

1. 先审阅并合并本 PR；启用 Actions，创建下一个 `ai/<Issue>-...` PR，确认 `pr-guard` 运行成功。
2. Settings → Rules → Rulesets，针对 `master` 创建/更新分支规则：Require a pull request before merging、Block force pushes、Restrict deletions；避免允许 AI 使用的账号或 Token 获得 bypass 权限。
3. Require status checks to pass：加入 `pr-guard`。若有独立且稳定上报 PR commit 状态的测试 CI，一并设为必过；不能把 Jenkins 只在 master 上执行的 Job 直接加入 PR 必过，否则 PR 可能永久 Pending。
4. Require conversation resolution before merging；条件允许时启用 Restrict updates / restrict who can push，注意个人仓库不要开启无法由本人满足的审批条件。
5. 为了避免检查器被绕过，保护 `.github/workflows/**`、`.github/scripts/**` 及本文件的审批路径；单人仓库 GitHub 不能形成独立双人审批，需将 AI 写入身份与管理员身份分开。

## 实际执行检查
- 恰好一个 `Fixes #N` 等关闭关联，且号码必须是 Issue。
- 关联 Issue 必须按固定顺序填写 `## 问题`、`## 影响`、`## 验收标准`、`## 涉及模块`、`## 作者`，每节只出现一次并有真实内容；模板提示原样保留也会失败。
- `## 问题` 只允许一个普通文本段落，最多 **200 个可见字符**（汉字、英文、数字及标点均计入；连续空白归一），不允许列表、多个段落、额外问题或原标题下的多个小节。
- Issue 用面向人的中性语言写“在哪里、做了什么、实际发生什么”。禁止攻击性、贬损性和无依据的归责（例如“垃圾系统”“脑残”），高确定性词汇由脚本拦截；更复杂的情绪化表述或一个描述中是否隐含两个问题，仍需人审，机器无法百分之百识别。
- Issue 里的 HTML 注释只是填写提示，不算有效内容；不懂技术模块可以填写“待确认”。
- `## 验收标准` 至少有一项 `- [ ] 可以检验的结果`；这能检查格式，不能机器证明 Issue 只包含一个逻辑问题。
- PR Guard 会在 Actions 失败日志中列出缺失/重复栏目和修复方式。更正 Issue 后，需要重新运行该 PR 的检查（例如让 Agent 更新 PR 正文触发 `edited` 事件，或通过 GitHub UI 重跑检查）；单独编辑 Issue 不会自动刷新已有 PR 的检查结果。
- 分支名称 `ai/N-description`，PR 标题 Conventional Commit。
- PR 必须有目的、问题、改动、验证、作者。
- 跨多个模块必须说明原因；超过 20 个文件必须解释。
- 改模块实现 .py：同时修改模块 `pyproject.toml`、`VERSION`、`CHANGELOG.md`，新 X.Y.Z 版本递增且一致。

## 边界与后续
- 该工作流不执行 PR 源码，**不等于**已经验证模块行为和架构依赖。现有 `scripts/check_module_dependencies.py` 必须另由可信 PR 测试 Job 执行并设为必过，不能复用只在 master 上运行的 Jenkins Job。
- GitHub 的状态检查不能阻止直接在本地写代码；它只阻止合入。分支创建时命名限制需要仓库 Ruleset。
- 本次不启用自动合并、自动 Tag、自动删除镜像和部署，避免未经验证的副作用。
