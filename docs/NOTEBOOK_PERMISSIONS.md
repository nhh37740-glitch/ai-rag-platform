# 笔记本、成员与管理员权限设计

任务：RAG-NOTEBOOK-20261011。日期：2026-10-11（北京时间）。状态：正式实施依据；发布结果另见 NOTEBOOK_ACCESS_VALIDATION.md。本文件维护权限矩阵和数据模型，PLAN.md 链接执行范围，接口签名由 specifications/API_SCHEMA.json 管理。

## 1. 权限放在哪里

笔记本表不为每个用户复制一组布尔权限。notebooks 保存资源信息；notebook_members 保存用户与笔记本的关系和角色；roles、permissions、role_permissions 定义角色拥有的操作。HTTP 每次检查操作权限及具体笔记本范围。全局管理员来自已有 Media 会话与服务器指定 owner 的验证，不能通过写数据库成员角色或浏览器字段获得。

参考成熟模型：[OpenFGA 角色与权限](https://openfga.dev/docs/modeling/roles-and-permissions)将角色和资源操作分开；[直接授权](https://openfga.dev/docs/modeling/direct-access)用唯一用户ID和资源ID建立关系。本项目采用该资源范围角色模型并存入已有 SQLite；这是架构选择，不表示部署了 OpenFGA 服务。

## 2. 笔记本操作权限

| 操作 / permission | 游客 | 无该笔记本成员身份的登录用户 | viewer 查看者 | editor 编辑者 | manager 笔记本管理者 | 全局管理员 |
| --- | --- | --- | --- | --- | --- | --- |
| 查看公开内置资料 / read | 是 | 是 | 是 | 是 | 是 | 是 |
| 私人笔记本出现在列表、查看文档 / read | 否 | 否 | 是 | 是 | 是 | 是 |
| 在该笔记本提问、检索 / query | 仅公开 | 仅公开 | 是 | 是 | 是 | 是 |
| 导入文档 / import_document | 否 | 否 | 否 | 是 | 是 | 是 |
| 当前笔记本编辑能力 / write | 否 | 否 | 否 | 是 | 是 | 是 |
| 改笔记本名称和说明 / manage_notebook | 否 | 否 | 否 | 否 | 是 | 是 |
| 创建新私人笔记本 / create_notebook | 否 | 否 | 否 | 否 | 否 | 是 |
| 归档私人笔记本 / archive_notebook | 否 | 否 | 否 | 否 | 否 | 是 |
| 恢复归档笔记本 / restore_notebook | 否 | 否 | 否 | 否 | 否 | 是 |

write 仅指该笔记本范围内已实现的编辑能力，目前导入与浏览器本地笔记；不授予任意磁盘文件或全局写工具。普通成员的 Agent 仅有五个检索工具，即使模型伪造 create_file/save_conversation 调用也拒绝。内置公开笔记本对任何身份都只读，不能改名、导入、设置成员或归档。归档使用数据库标记，保留 Markdown、索引与成员；归档后成员不能列出/读/查该笔记本，全局管理员可在归档目录查看名称并恢复，但不能在归档状态问答。当前不提供物理删除功能。

## 3. 成员表操作权限

| 操作 | viewer | editor | manager | 全局管理员 |
| --- | --- | --- | --- | --- |
| 查看自己的角色和可执行操作 | 是 | 是 | 是 | 是 |
| 列出该笔记本全部成员 / manage_members | 否 | 否 | 是 | 是 |
| 添加已登记用户为 viewer/editor/manager | 否 | 否 | 是 | 是 |
| 修改成员角色 | 否 | 否 | 是 | 是 |
| 移除成员 | 否 | 否 | 是 | 是 |
| 改其他笔记本成员 | 否 | 否 | 仅该笔记本也授权manager时 | 是 |
| 授予全局管理员、改拥有者身份 | 否 | 否 | 否 | 本成员接口也不提供 |

添加对象必须先用现有 Media 账号登录一次 RAG，登记不可变 userId，再复制ID交给管理者。不得用用户名、请求 body.user_id 或客户端角色代替认证身份。manager 可以设置其它 manager，也可移除自己；系统指定全局管理员始终保留权限，不能作为普通成员降级/移除，避免无人管理。移除是删除关联，不删除用户账号或文档；对其他笔记本的授权不受影响。撤权后的新请求立即重新检查；已被用户取得的数据无法远程撤回。

## 4. 全局管理员的范围

管理员可管理所有私人笔记本、创建、改名、导入、管理成员、归档和恢复。管理员可看当前服务记录的私人trace/上传进度；普通成员只能看自己产生的记录，且读取时仍须有对应笔记本权限。全局管理员角色与 notebook manager 严格分开，不允许通过成员表获得管理员。

本功能不提供创建 Media 账号、重置密码、改变其他项目账户权限、Jenkins或服务器权限。RAG 的 users 是认证身份的本地目录，不存密码、会话cookie或模型key。管理员身份仍由 auth-runtime 验证可信代理证明及固定 owner ID，普通用户需真实 Media /me 校验。

## 5. 关系表与约束

| 表 | 字段与作用 | 约束 |
| --- | --- | --- |
| users | user_id，created_at，last_seen_at | user_id 非空主键；只登记可信登录身份，迁移可登记历史关联ID |
| notebooks | notebook_id，owner_user_id，name，description，created_at，is_public，archived，acl_revision，legacy_migrated | notebook_id主键；owner_user_id引用users；公开/归档标记为0/1；ACL版本非负 |
| notebook_members | notebook_id，user_id，role_id | (notebook_id,user_id)联合主键；分别引用notebooks/users/roles；关联删除不删除用户 |
| roles | role_id | 主键，默认viewer/editor/manager；没有admin角色可供成员授予 |
| permissions | permission_id | 主键，操作标识 |
| role_permissions | role_id，permission_id | 联合主键，角色和权限外键 |
| schema_migrations | version，applied_at | 版本主键，记录结构迁移 |

user_id与notebook_id索引支持按用户查成员、按笔记本查成员。每个 SQLite NotebookStore 连接执行 PRAGMA foreign_keys=ON；不能依赖默认值。[SQLite 外键依据](https://www.sqlite.org/foreignkeys.html) 成员增改删采用事务和 acl_revision 比较更新。冲突后 auth-facade 重新读快照、重新检查 manage_members 再重试，禁止撤权后使用旧版本写入。[SQLite 事务依据](https://www.sqlite.org/lang_transaction.html)

## 6. 模块、迁移与接口

- auth-facade：拥有角色和操作决策，使用 NotebookStorePort，不导入具体数据库实现。
- data-facade：拥有 notebook.sqlite 的生命周期，向业务提供仓库端口。
- storage：关系表、外键、参数化SQL、事务、版本检查及幂等迁移，不判定HTTP身份或管理员。
- agent-server：认证/HTTP装配；目录从数据库读取。旧笔记本名称、说明、创建时间和文件资产迁移保留；旧 JSON ACL 仅迁移一次，之后表是事实来源。
- agent-facade/agent-runtime：保持中文约束和只读工具检查；rag-facade：只在授权范围执行检索。

API：现有笔记本与成员路径保持；新增 PATCH /api/notebooks/{id} 接受仅 name/description，POST /api/notebooks/{id}/archive 与 /restore 仅管理员，GET /api/notebooks?include_archived=true 仅管理员显示归档目录。归档状态不在默认列表中；恢复后原成员及文档保留。公开内置笔记本拒绝上述写操作。

迁移须在开启服务前完成，事务提交成功再设置legacy_migrated，重复启动不恢复已撤销成员；不删除旧数据、不自动公开私人笔记本。发生非法旧角色、ID或数据时停止该迁移并报错，不能擅自扩大权限。

## 7. 验收标准

按矩阵逐项验证：身份伪造和越权拒绝；viewer不能导入、editor不能管理成员、manager不能管理其它笔记本或归档；管理员创建/归档/恢复；内置公开资料只读；未登记用户拒绝；成员变更重启持久；目录迁移幂等且保留旧文档；多连接成员并发不丢失、旧版本不能写入；撤权后的问答/SSE/trace/进度拒绝；SQL外键/唯一约束与回滚；源码和编译接口行为一致；实际默认模型中文回答及免费模型/日限20回归。

本文件先写于关系表实现之前。各完成阶段及提交/构建/上线证据写入 NOTEBOOK_ACCESS_VALIDATION.md，不能将设计要求写成上线事实。
