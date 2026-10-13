# 开发协作

## 提交一个问题（Issue）

一个 Issue 只描述一个可观察的现象。用中性、易懂的语言说明在哪里、做了什么、出现什么情况，禁止人身攻击和臆测归责。

Issue 正文包含：`问题`、`影响`、`验收标准`、`涉及模块`、`作者`。问题描述最多 200 个可见字符、一个自然段；不懂技术模块可写“待确认”。

**状态提醒：** 200 字与措辞强制检查还在 [PR #17](https://github.com/nhh37740-glitch/ai-rag-platform/pull/17)，合入后才能成为主线 Guard 的规则。

## 代码交付

1. 关联一个 Issue，在 `ai/<Issue号>-简短描述` 分支开发。
2. PR 正文有 `Fixes #编号`，说明目的、问题、改动、验证、作者。
3. 一个 PR 解决一个主要问题。合理跨模块修改要解释原因。
4. 通过适用的自动检查后合入主分支；是否强制所有检查，需要 GitHub Rulesets 实际配置。

详细要求见 [AGENTS.md](https://github.com/nhh37740-glitch/ai-rag-platform/blob/master/AGENTS.md) 和 [治理规则](https://github.com/nhh37740-glitch/ai-rag-platform/blob/master/docs/GITHUB_GOVERNANCE.md)。
