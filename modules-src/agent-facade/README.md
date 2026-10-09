# agent-facade

AGENT 中间包对应用只公开 AgentService 和 make_provider。接口见 INTERFACE.md；构建以 VERSION=0.1.0 编译为当前平台扩展模块。

注入 data/rag/tracing 的共享接口对象，内部创建工具注册表和技能注册表。应用通过 register_tool 扩展工具，通过 history 获取当前用户和会话的消息副本。
资源所有者负责关闭数据库与 Provider；AgentService.aclose 只释放自己的内存运行对象。

从仓库根目录执行源码中间包测试：

```powershell
.venv/Scripts/python.exe scripts/run_tests.py --mode source --group facade
```

集成运行只从 artifacts 的已发布二进制加载本包。
