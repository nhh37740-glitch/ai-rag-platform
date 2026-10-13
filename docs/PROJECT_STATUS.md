# RAGnotebook · Project 进度快照

**更新：2026-10-13。** 此页面是仓库文档中的进度索引，不是 GitHub Projects 看板。实时状态以 [Issues](https://github.com/nhh37740-glitch/ai-rag-platform/issues)、[PR](https://github.com/nhh37740-glitch/ai-rag-platform/pulls) 与 [Actions](https://github.com/nhh37740-glitch/ai-rag-platform/actions) 为准。

## 当前项目

- 应用版本声明：`0.8.1`，来自 `apps/ragnotebook/pyproject.toml`，不代表已创建 GitHub Release。
- 产品：RAGnotebook，浏览器中的文档问答与共享笔记本。
- 核心边界：一个后端进程、四个业务 facade、一个 SQLite 数据库；源码编译后，应用运行时校验二进制来源。
- 唯一生效的设计依据：[docs/PLAN.md](PLAN.md)。本页只负责导航，不重新定义需求。

## 已合并的代码

| 事项 | 证据 | 说明 |
| --- | --- | --- |
| RAGnotebook 统一服务 | [PR #7](https://github.com/nhh37740-glitch/ai-rag-platform/pull/7)、[PR #8](https://github.com/nhh37740-glitch/ai-rag-platform/pull/8) | 服务重构及测试调整 |
| PR Guard 基础工作流 | [Issue #11](https://github.com/nhh37740-glitch/ai-rag-platform/issues/11)、[PR #12](https://github.com/nhh37740-glitch/ai-rag-platform/pull/12) | 工作流已合并；无法确认 Rulesets 已设必过 |
| GitHub 主线构建 | [Issue #15](https://github.com/nhh37740-glitch/ai-rag-platform/issues/15)、[PR #16](https://github.com/nhh37740-glitch/ai-rag-platform/pull/16) | 编译、测试、ZIP Artifact，保留 14 天 |
| 大文档分批嵌入 | [Issue #18](https://github.com/nhh37740-glitch/ai-rag-platform/issues/18)、[PR #19](https://github.com/nhh37740-glitch/ai-rag-platform/pull/19) | 代码已合并，不等于 VPS 已部署 |
| 项目进度与 Wiki 源稿整理 | [Issue #20](https://github.com/nhh37740-glitch/ai-rag-platform/issues/20)、[PR #21](https://github.com/nhh37740-glitch/ai-rag-platform/pull/21) | PR 已合并，Issue 已关闭；实际 Wiki 网页和 Projects 看板仍未更新 |
| 大文档验收文本修复 | [Issue #22](https://github.com/nhh37740-glitch/ai-rag-platform/issues/22)、[PR #23](https://github.com/nhh37740-glitch/ai-rag-platform/pull/23) | 将测试文本扩到 200 KB 以上，修复构建中的大小断言失败 |

## 构建证据快照

- PR #21 合并后的[主线构建](https://github.com/nhh37740-glitch/ai-rag-platform/actions/runs/38381208873)失败；PR #23 修复后，[提交 `cb80ac0` 的主线构建](https://github.com/nhh37740-glitch/ai-rag-platform/actions/runs/38381905326)成功，生成 `ai-rag-platform-release-4` Artifact。
- 该证据只覆盖对应提交的编译、测试与产物，不代表 VPS 已部署；后续提交以其各自 Actions 结果为准。

## 进行中

- [PR #17](https://github.com/nhh37740-glitch/ai-rag-platform/pull/17)：Issue 格式、200 字上限与中性描述校验，待合并后才能在主线检查器中生效。

## 待规划（尚未自动创建任务）

- 核对 GitHub Required status checks 的规则设置。
- 将正式版本发布到 GitHub Releases / GHCR，并评估由 VPS 拉取已验证的镜像。
- 完善部署回滚及资源治理，减少 VPS 上的重复编译。

## 四个不同状态

**Issue 已关闭** ≠ **PR 已合并** ≠ **构建成功且有产物** ≠ **已成功部署**。不要把合并或生成 ZIP 当作线上发布。Wiki 网页与 Projects 看板不能由当前 GitHub 连接直接维护；Wiki 内容源稿见 [Home](wiki/Home.md)。
