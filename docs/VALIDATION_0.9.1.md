# RAGnotebook 0.9.1 云端编译部署验收

基线GitHub master c0a9a1df49e631b0ebd90c8f3f2555cc6f59a2a7 / 0.9.0。独立分支ai/33-import-parser-errors；问题#33（损坏文件终态）、#34（部署测试预算）、#35（真实长导入20分钟XHR超时）。本记录是本地云工作区验收，不代表服务器正式部署。

## 实现与边界

三级RAGnotebook0.9.1：可选background=true暂存后202返回任务号，短请求取进度及完成result；全站最多一个导入任务，忙时409，完成/失败清理临时文件及释放。网页轮询终态并处理任务记录失效，静态资源版本更新。同步API保留201，损坏文件422；未知程序错误仍500但任务终止，避免永远阻止删除。服务退出先等后台任务再关facade连接。进程内任务不跨重启恢复。

二级rag-facade/data-facade/auth-facade/agent-facade均沿用公开接口。一级ingestion0.2.2规范DOCX ZIP/XML/缺正文及PDF损坏/加密错误为ValueError。rag-core0.5.3沿用批次8、threads1、串行模型推理；其它一级模块沿用。数据库仍固定六表，无迁移或新增库。

## 已完成回归

CPython3.11.17/Linux x86_64：source leaf111、source facade49；binary leaf111、binary facade49；严格specification12；binary app20；source scripts25/binary scripts25，分别跳过1项独立真实LLM门禁。JS语法与模块依赖检查通过；18个发布二进制可加载。

初次scripts的两项180轮边界测试因固定30秒预算失败；仅增加预算仍不稳定，最终改用shell健康计数器，正常假Docker同步完整记录，保留精确180轮及服务/清理断言。source/binary scripts最终均25通过、1按既有约定跳过。

## 0.9.0 真实BGE故障复现

权重来自官方Qdrant/bge-small-zh-v1.5，94781076字节，SHA256 1294ea4b6331115a353d81f96b85e8c8d7fdcc284453d5b2fab5b016230aad38。校验后离线加载真实BGE，维度512；没有hash降级。

用户附件银河争霸战TXT：2065431字节，SHA256 7b1ebcf401306f171b12ea58ab1c5b7cf991021f865b3df40df9cce195afecea，归一后698629字符、1650块。Chromium在1201秒被旧XHR时限中断；后台继续并最终保存1篇/1650块。1CPU、memory=1GB、memory-swap=1GB（无额外swap）容器峰值544.355MiB，无OOM/重启。导入期间实际BGE检索返回200，用时33.196秒。此证据只能说明本地0.9.0候选，不能倒推此前生产0.8.1的502原因。

损坏DOCX/PDF真实HTTP均500 text/plain，progress=running，删除409；0.9.1修复后同步HTTP422 JSON、progress=error，删除200；Chromium后台202错误反馈和删除也已通过。

## 0.9.1 站点验收

独立ZIP解压运行，容器仅挂载发布资产/依赖/状态/模型缓存，没有业务源码，18个模块入口来自.so。站点使用真实BGE；LLM仍Mock，因为当前环境没有模型API凭据，不以该测试证明自然语言回答或外部免费模型可用。

已完成Chromium注册登录及四集合13篇导入（接受请求0.563—1.403秒），实际MD/TXT/DOCX/PDF全部完成。真实后台任务曾因测试工具一次socket中断关闭浏览器，任务继续；已恢复同一任务并通过刷新续看，不重复上传。新任务恢复记录仅保存按用户隔离的任务ID/笔记本ID，不保存正文或密钥。

Chromium真实小说后台任务已完成：202接受任务，最终GET result回执bytes=2065431、characters=698629、chunks=1650、sha256与原附件匹配。刷新恢复同一任务通过，无重复上传；5个笔记本、14份文件全部导入，页面JS异常0。0.9.1容器峰值520.91MiB，1CPU/1GB、无额外swap、OOM=false、RestartCount=0。

角色及低并发真实HTTP已验证：第二个导入409；处理中删除409；其它用户读私有小说403、读进度404；viewer读4篇但写/删403；editor权限通过后受全局导入互斥409、删除笔记本403。

正在执行来源检索隔离、删除后不再检索及最终重启保留，完成后填写实际结果。原文附件、凭据、数据库及带原文的trace均不进入Git。LLM使用Mock，真实BGE检索成功不等于自然语言回答/免费模型可用性通过。
