# RAGnotebook 0.9.0 验证记录

基线：master `6af3fd8f8969b4114feae2e807200cd086332d4f`，已部署0.8.1。发布tag `v0.8.1` 已推送并核验指向该提交。新代码在 `ai/28-ragnotebook-0.9.0`；本文记录云Linux验证，不代表服务器已部署0.9.0。

## 分层改动

- 三级应用 RAGnotebook 0.9.0：删除HTTP/Web入口、确认和权限，弹窗上传进度、XHR传输进度、问答总时限和取消、非JSON响应处理；只调用四facade。
- 二级 agent-facade 0.5.3：免费文本及工具能力筛选。一级 llm-gateway 0.1.2：脱敏的稳定错误；agent-runtime及其余Agent一级模块沿用。
- 二级 rag-facade 0.3.3：解析/分块/32块向量进度回调，完成全部推理后原子写入。一级rag-core、rag-tools、ingestion沿用。
- 二级 data-facade 0.3.2：来源范围删除。一级storage、memory沿用，六表结构不变。auth-facade沿用owner/editor/viewer权限，无新增管理员越权。
- specifications 0.8.0：delete_document、progress与ModelRequestError契约。构建脚本补交付既有辅助模块mcp_servers.github，无MCP实现改动。

## 已执行检查

CPython3.11.17 / Linux x86_64，按仓库编译脚本生成18个模块入口与MCP辅助扩展。所有业务导入来自artifacts的.so，运行边界验证输出RAGNOTEBOOK_COMPILED_OK。

| 检查 | 通过 | 失败/跳过 |
|---|---:|---|
| source leaf | 106 | 0 |
| source facade | 49 | 0 |
| binary leaf | 106 | 0 |
| binary facade | 49 | 0 |
| binary scripts/integration | 23 | 1跳过：真实模型仅由独立凭据构建阶段启用 |
| binary specification（严格签名、元数据） | 12 | 0 |
| binary app | 16 | 0 |

源码与二进制是两次执行，不代表独立用例数翻倍。新增检查覆盖来源删除的范围与重启、owner/editor/viewer/guest及同源、导入中删除409、原子失败、分块进度轮询、上游429/无效响应/超时、总超时、客户端断开取消。模块依赖及JS语法检查通过。

真实Chromium浏览器对本地二进制服务验证：注册登录、建笔记本、上传真实附件、上传弹窗进度可见、来源删除、笔记本删除、纯文本500显示明确提示、取消等待后恢复。无页面JS异常。

## 真实小说导入证据

测试文件为用户上传的 `银河争霸战.txt`，非此前254KiB合成文档。原文件2065431字节，UTF-8解码698875字符；SHA-256 `7b1ebcf401306f171b12ea58ab1c5b7cf991021f865b3df40df9cce195afecea`。浏览器收到HTTP201完整回执：bytes=2065431、characters=698629、chunks=1650、sha256与原文件完全一致。characters是解析归一后的Markdown字符数，与原文件字符数含空白/BOM的口径不同。

验证明确设置RAG_EMBED=hash与LLM_PROVIDER=mock；证明上传、分块、入库、进度和权限，不证明BGE推理资源或真实模型质量。附件正文、数据库、密钥与会话令牌没有写入仓库。

## 模型与发布边界

此前线上0.8.1目录19项。已逐个调用10个具体免费模型（不把openrouter/free路由当成具体模型），5项检索问答通过、5项HTTP500纯文本失败。新版本修复筛选及错误呈现，不承诺外部免费provider永久可用，也不静默替换用户指定模型。

0.9.0仍需服务器/CI凭据环境中的真实模型门禁，以及服务器候选的BGE长文档导入和正式部署验收。当前SSH直连被拒绝、代理连接在SSH握手前关闭，尚未修改或部署服务器服务。

## 重跑

使用CPython3.11及requirements-runtime.txt、requirements-build.txt，从仓库根运行：

```sh
python scripts/check_module_dependencies.py
python scripts/run_tests.py --mode source --group leaf
python scripts/run_tests.py --mode source --group facade
python scripts/compile_extension_modules.py
python scripts/package_release_artifacts.py
RAG_EMBED=hash python scripts/verify_compiled_runtime.py
python scripts/run_tests.py --mode binary --group leaf
python scripts/run_tests.py --mode binary --group facade
python scripts/run_tests.py --mode binary --group scripts
python scripts/run_tests.py --mode binary --group specification
python scripts/run_tests.py --mode binary --group app
python scripts/build_release_bundle.py
```

流水线真实模型门禁仍由Jenkins现有凭据独立执行，不能用Mock替代。用户提供的真实小说不进入Git或发布包。
