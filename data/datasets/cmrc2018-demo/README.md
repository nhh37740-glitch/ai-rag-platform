# CMRC2018 中文阅读理解演示集

用于 Web 端演示的内置数据集：在知识库页点「导入知识库」，系统会把下面的文档逐篇索引，
之后可以在欢迎页直接点示例问题提问，查看带引用的回答与检索轨迹。

## 来源与许可

- 数据集：**CMRC 2018**（The Second Evaluation Workshop on Chinese Machine Reading Comprehension）
- 主页：<https://huggingface.co/datasets/hfl/cmrc2018>　｜　官方仓库：<https://github.com/ymcui/cmrc2018>
- 论文：Cui et al., *A Span-Extraction Dataset for Chinese Machine Reading Comprehension*, EMNLP-IJCNLP 2019
- 许可证：**CC BY-SA 4.0**（<https://creativecommons.org/licenses/by-sa/4.0/>）
- 原始语料来源：中文维基百科条目，问题由人工标注

本目录是 CMRC2018 **dev 集**的子集，按 CC BY-SA 4.0 的署名与相同方式共享条款再分发。

## 子集是怎么挑出来的

从官方 `cmrc2018_dev.json`（848 篇文章）中筛选：

1. 正文长度 ≥ 600 字符（保证一篇文档有足够信息量）；
2. 至少 3 个答案非空、且答案确实出现在正文中的问题；
3. 按正文长度降序，跳过标题高度相似的条目（避免同一主题重复）；
4. 取前 24 篇。

最终：**24 篇文档 / 99 个示例问题**，每篇 933~980 字符，每篇 3~5 个问题。

文档正文只做了一处改动：在开头加一行 `# 标题`，其余与原文一致（原文中的标点、空格瑕疵保留）。

## 目录结构

```
manifest.json     数据集清单：id、名称、来源、许可证、文档与问题
documents/*.md    24 篇文档，UTF-8 无 BOM
```

`manifest.json` 字段：

| 字段 | 说明 |
|---|---|
| `id` | 数据集标识，与目录名一致 |
| `name` / `source` / `license` | 展示用元信息 |
| `document_count` / `question_count` | 文档数与问题总数 |
| `documents[].file` | `documents/` 下的文件名，导入时的文档名 |
| `documents[].title` | 文档标题 |
| `documents[].source_id` | 原始数据集里的 `context_id`，便于溯源 |
| `documents[].questions` | 该文档的示例问题，答案可在该文档中直接找到 |

## 重新生成

1. 取官方 dev 集：`https://raw.githubusercontent.com/ymcui/cmrc2018/master/data/cmrc2018_dev.json`
2. 按上面 4 条规则筛选，把 `context_text` 写入 `documents/NNN-<标题>.md`（开头加 `# <title>`）
3. 把每个条目的 `qas[].query_text` 汇总进 `manifest.json` 的 `documents[].questions`

## 已知限制

- 语料是**通用百科**知识，不是研发/技术文档；选它是因为它公开、许可证明确、且自带「文档 + 问题」配对，适合演示检索与引用链路。
- 每篇文档偏短（约 1 千字），引用片段较短。
- 少量维基条目标题在简繁、译名上不统一（如「乔许·哈却森」），这是原始数据集本身的状况。
