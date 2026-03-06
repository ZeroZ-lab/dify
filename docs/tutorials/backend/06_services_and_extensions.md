# 06 业务协作与扩展机制

穿过节点车间后，导览员领我们来到“指挥塔”。这里是服务层与仓储层的集散地：左手边的 `WorkflowService` 正与核心域握手，右手边的扩展墙面则挂着
日志、监控、存储的开关。搞清楚这些角色，才能知道一条运行记录如何被落盘、一个插件凭据如何进入节点，亦或多租户信息怎样在整条链路保持隔离。

## 学习成果

- 说明服务层与仓储层的依赖注入方式，以及它们与核心工作流域的协同关系。
- 理解插件、工具、扩展点的装配流程，掌握新增能力的入口与注意事项。
- 总结多租户、系统变量、监控扩展在工作流运行过程中的关键实现。

## 引导问题

1. `DifyAPIRepositoryFactory` 如何基于配置返回具体仓储？它与核心仓储工厂的职责边界在哪里？
2. `WorkflowService`、`WorkflowAppService` 分别负责哪些业务能力？它们如何与 Graph Engine 产生的数据对接？
3. 插件或工具的凭据在服务层如何管理，并在节点执行时被使用？
4. 多租户与系统变量信息如何一路传递到核心域并回写输出？
5. 扩展（Extensions）如何在 Flask 应用初始化时挂接额外的日志、健康检查或请求追踪？

## 必读源码

- `api/repositories/factory.py:1`
- `api/core/repositories/factory.py:1` 及对应仓储实现
- `api/services/workflow_service.py:47`
- `api/services/workflow_app_service.py:12`
- `api/services/plugin/`、`api/services/tools/`、`api/services/agent_service.py`
- `api/core/workflow/system_variable.py:1`
- `api/extensions/ext_app_metrics.py:1`、`api/extensions/ext_request_logging.py:1`

## Walkthrough

### 1. 仓储工厂：服务层与核心层的双向桥

服务层使用 `DifyAPIRepositoryFactory`（`api/repositories/factory.py`）创建专门面向 API 的仓储实现。构造函数接受 `sessionmaker`，以依赖注入
方式提供数据库会话，便于测试与多数据库适配。当配置项 `API_WORKFLOW_NODE_EXECUTION_REPOSITORY`、`API_WORKFLOW_RUN_REPOSITORY`
指向不同类时，工厂会通过 `import_string` 动态加载，实现 Django 风格的可替换后端。【F:api/repositories/factory.py†L1-L80】

核心域在另一侧通过 `DifyCoreRepositoryFactory`（`api/core/repositories/factory.py`）提供运行态写入仓储。它除了接收 `sessionmaker`，还
需要当前用户、应用 ID、触发来源等上下文，以便对运行记录进行租户与触发方隔离。这两个工厂分别服务于“服务层查询/展示场景”和“核心引擎持久化场
景”，既解耦了实现，又可以通过配置实现混合后端（例如在线使用 PostgreSQL，异步写入走 Celery）。【F:api/core/repositories/factory.py†L1-L120】

### 2. WorkflowService：运行管理的门房

`WorkflowService`（`api/services/workflow_service.py:47`）在构造时注入节点执行仓储，提供草稿加载、发布版本校验、节点调试等接口。当调用单步调试
时，它会读取草稿版本的图结构，构造 `WorkflowEntry.single_step_run()` 并把返回的事件流转换成前端可消费的格式；查询节点最近一次执行则直接调仓储
的 `get_node_last_execution()`，确保读路径不依赖核心域的运行逻辑。【F:api/services/workflow_service.py†L47-L160】

工作流运行日志展示则由 `WorkflowAppService`（`api/services/workflow_app_service.py:12`）负责。它以 SQLAlchemy 2.0 风格拼接查询，支持多条件过
滤、分页，并通过 `WorkflowRun`、`WorkflowAppLog` 关联 end-user / account 信息，满足控制台的搜索需求。【F:api/services/workflow_app_service.py†L12-L120】

### 3. 插件、工具与 Agent：服务层如何喂给节点

插件与工具的凭据管理散落在 `api/services/plugin/` 与 `api/services/tools/`。例如工具服务会负责校验凭据、保存用户自定义配置，再在节点执行
时通过 `ToolNode` 的 `BaseNodeData` 注入。Agent 服务则协调工具集合与策略，最终由 `AgentNode` 在 `_run()` 中调用。理解这一层的职责后，新增
一个外部能力通常需要：

1. 在服务层添加凭据管理与业务规则。
2. 在节点数据模型中暴露可配置项。
3. 在节点运行逻辑中读取服务层写入的配置，调用 Runtime 或 SDK。

### 4. 多租户上下文与系统变量

系统变量模型位于 `api/core/workflow/system_variable.py`，包含 `user_id`、`app_id`、`workflow_id`、`workflow_execution_id` 等字段。服务层在构造
`WorkflowAppRunner` 时，将这些信息装入 `SystemVariable`，最终被 `VariablePool` 注入节点运行环境。模型通过 `AliasChoices` 同时兼容历史字段
（如 `workflow_run_id`），确保老版本数据不会出错。【F:api/core/workflow/system_variable.py†L1-L120】

多租户隔离还体现在仓储查询条件上：无论是 `WorkflowService` 的草稿查询，还是 `WorkflowAppService` 的运行记录，都显式带上 `tenant_id` 与
`app_id` 过滤，避免串租户数据。【F:api/services/workflow_service.py†L47-L160】【F:api/services/workflow_app_service.py†L12-L120】

### 5. Extensions：把横切能力插到应用工厂

扩展位于 `api/extensions/`，由 `app_factory` 在初始化阶段逐一挂载。以 `ext_app_metrics` 为例，它在 `after_request` 钩子中写入版本号 Header，并提
供 `/health`、`/threads`、`/db-pool-stat` 诊断接口；`ext_request_logging` 根据配置订阅 Flask `request_started` / `request_finished` 信号，记录进出
口的 JSON 载荷，方便调试 API 请求。这些扩展统一由 `create_app()` 注册，必要时可以根据配置开关启停。【F:api/extensions/ext_app_metrics.py†L1-L80】【F:api/extensions/ext_request_logging.py†L1-L120】

## 动手任务

- 列出工作流运行涉及的主要仓储类（API 层与核心层各自至少两个），标注负责的数据表和关键方法。
- 选择一个插件或工具服务，梳理其从保存凭据 → 注入节点 → 节点调用 Runtime 的完整流程。

## 思考题

- 如果要接入新的外部知识库，哪些服务需要扩展？是否需要新增节点类型或仓储？
- 在多租户场景下，除了系统变量，哪些缓存/队列键名也必须带上租户信息以避免串数据？

## 延伸阅读

- `api/core/workflow/variable_loader.py`
- `api/services/dataset_service.py` 中与 workflow graph 关联的逻辑
- `api/core/workflow/graph_engine/layers/persistence.py`

