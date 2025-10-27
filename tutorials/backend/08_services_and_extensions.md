# 08 业务协作与扩展机制

## 学习成果
- 理解服务层 ↔ 核心域 ↔ 仓储/扩展的协作路径与职责边界
- 掌握仓储工厂与可替换实现的配置切换方式
- 熟悉 Runner 组装、持久化 Layer 挂载与多租户上下文贯通

本篇从“服务层 ↔ 核心域 ↔ 仓储/扩展”角度，梳理运行记录、配置、插件与多租户的协作路径，并给出可替换点。

## 仓储工厂与可替换实现

- API 层工厂：`DifyAPIRepositoryFactory` 为服务层提供面向业务的仓储，使用 `sessionmaker` 依赖注入，便于测试与隔离（`api/repositories/factory.py:1`）。
  - 节点执行记录仓储创建：`create_api_workflow_node_execution_repository()`（`api/repositories/factory.py:22`–`api/repositories/factory.py:46`）。
  - 运行记录仓储创建：`create_api_workflow_run_repository()`（`api/repositories/factory.py:48`–`api/repositories/factory.py:73`）。
- 核心域工厂：`DifyCoreRepositoryFactory` 通过模块路径选择不同实现（SQLAlchemy/Celery 等），配置项见：
  - `CORE_WORKFLOW_EXECUTION_REPOSITORY`（`api/configs/feature/__init__.py:639`–`api/configs/feature/__init__.py:644`）。
  - `CORE_WORKFLOW_NODE_EXECUTION_REPOSITORY`（`api/configs/feature/__init__.py:646`–`api/configs/feature/__init__.py:653`）。
  - 接口约束见 `api/core/workflow/repositories/workflow_execution_repository.py:1` 与同目录下 `workflow_node_execution_repository.py`。

更换实现的实践：修改上述配置为自定义类路径（保持相同接口），即可在不改动服务/引擎代码的前提下替换存储后端。

## 服务层如何驱动引擎并持久化

- 入口与分发：`AppGenerateService.generate()` 根据应用模式选择生成器（工作流走 `WorkflowAppGenerator`，见 `api/services/app_generate_service.py:104`–`api/services/app_generate_service.py:121`）。
- Runner 组装：`WorkflowAppRunner.run()` 创建 `VariablePool` 与 `GraphRuntimeState`，实例化 Graph，再建立 Redis 命令通道与 `WorkflowEntry`（`api/core/app/apps/workflow/app_runner.py:79`–`api/core/app/apps/workflow/app_runner.py:122`）。
- 持久化层：Runner 注入 `WorkflowPersistenceLayer`，监听所有 `GraphEngineEvent` 并写入 `WorkflowExecution/WorkflowNodeExecution`（`api/core/app/apps/workflow/app_runner.py:124`–`api/core/app/apps/workflow/app_runner.py:141`；实现见 `api/core/workflow/graph_engine/layers/persistence.py:1`）。
  - 图级起/止：`_handle_graph_run_started/succeeded/partial_succeeded/failed/aborted/paused`（`persistence.py:74` 起各 handler）。
  - 节点级：`_handle_node_started/retry/succeeded/failed/exception/pause_requested`。

要点：持久化在引擎线程内完成，呈现层仅消费事件，不直接写库，避免竞态与状态不一致。

## 插件、工具与凭证

- 工具/插件服务位于 `api/services/plugin` 与 `api/services/tools`，用于：
  - 管理与校验凭证，按租户隔离；
  - 暴露供节点使用的执行入口（如 HTTP、Agent 工具扩展）。
- 节点侧读取：节点通过自身的 NodeData/配置结合变量池取值；工具相关的文件读写可借助 `file_factory` 与 `ToolFileManager`（例如 HTTP 节点文件处理见 `api/core/workflow/nodes/http_request/node.py:135` 附近）。

## 多租户上下文的贯通

- SystemVariable 汇集用户/应用/工作流/运行 ID 与文件等上下文，序列化规则兼容 `workflow_run_id`（`api/core/workflow/system_variable.py:23`–`api/core/workflow/system_variable.py:41`、`api/core/workflow/system_variable.py:33`–`api/core/workflow/system_variable.py:41`）。
- 服务层在 Runner 中构造 `SystemVariable` 并注入 VariablePool（`api/core/app/apps/workflow/app_runner.py:59`–`api/core/app/apps/workflow/app_runner.py:66`、`api/core/app/apps/workflow/app_runner.py:79`–`api/core/app/apps/workflow/app_runner.py:85`）。
- 运行态中的变量池对节点透明，节点通过 selector 访问（详见第 03 篇）。

## 扩展点：命令通道、层与配置

- 命令通道：`GraphEngine` 通过 `CommandChannel` 接收外部控制（InMemory/Redis），控制面 API 同时设置“旧停止标记 + 新命令通道”以兼容（`api/controllers/service_api/app/workflow.py:270`–`api/controllers/service_api/app/workflow.py:277`）。
- 层（Layer）：可在引擎上挂载任意横切逻辑，例如：
  - `DebugLoggingLayer`（调试日志，`api/core/workflow/graph_engine/layers/debug_logging.py`）。
  - `ExecutionLimitsLayer`（步数/时间上限，`api/core/workflow/graph_engine/layers/execution_limits.py`）。
  - `WorkflowPersistenceLayer`（持久化，`api/core/workflow/graph_engine/layers/persistence.py`）。
  - 层初始化入口：`GraphEngine.layer()` 与 `initialize/on_event/on_graph_start/on_graph_end` 生命周期（`api/core/workflow/graph_engine/layers/base.py:28` 起）。
- 配置集中：`api/configs/feature/__init__.py` 下的 Workflow/Repository/Worker 池参数（见第 06 篇尾部“调优清单”）。

## 实用清单（落地）

- 替换仓储：将 `CORE_WORKFLOW_*` 或 `API_WORKFLOW_*` 指向你的实现类路径，确保实现核心接口即可。
- 跨进程恢复：结合第 05 篇的快照策略，在 `GraphRunPausedEvent` 时由自定义 Layer 落 `GraphRuntimeState.dumps()`，恢复时 `from_snapshot()` + 原图重建。
- 新增能力：
  - 简单观测/限额 → 写 Layer；
  - 外部系统集成（凭证/限流/审计）→ 写服务 + 节点/工具；
  - 存储后端变更 → 写仓储实现 + 配置切换。

## 延伸阅读

- 变量加载：`api/core/workflow/variable_loader.py`
- Runner 任务管线：`api/core/app/apps/workflow/generate_task_pipeline.py`
- 观测与日志：`api/extensions/ext_app_metrics.py`、`api/extensions/ext_request_logging.py`
