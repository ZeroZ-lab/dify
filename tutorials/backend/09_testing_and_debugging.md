# 09 测试策略与调试路径

## 学习成果
- 会运行与筛选核心工作流相关单测，形成本地检查闭环
- 能基于示例测试快速定位命令系统、变量池与事件传播的问题
- 掌握常见断点位与日志 Layer 用法，能快速构造/隔离测试场景

本篇给出核心模块的测试切入点、常用夹具/Mock、事件断言与调试技巧，并附运行命令。

## 如何运行

- 单元测试脚本：`dev/pytest/pytest_unit_tests.sh`（默认超时 `PYTEST_TIMEOUT=20`，参见 `dev/pytest/pytest_unit_tests.sh:1`）。
- 后端本地检查（见仓库约定）：`make lint`、`make type-check`，再执行上述脚本。

## 目录与样例

- 总入口：`api/tests/unit_tests/core/workflow/`
  - graph_engine：引擎调度与命令系统等（如 `test_command_system.py`）。
  - nodes：各节点单测（LLM/HTTP/Loop 等）。
  - entities：运行态/变量池等领域实体。

样例 1：命令系统（InMemory 通道）
- 文件：`api/tests/unit_tests/core/workflow/graph_engine/test_command_system.py:1`
- 关键点：
  - 使用 `InMemoryChannel`，向引擎发送 `Abort/Pause` 命令（`test_abort_command/test_pause_command`）。
  - 使用 `MagicMock(Graph)` 构造最小图，构造共享 `GraphRuntimeState`（`test_command_system.py:13`–`test_command_system.py:33`）。
  - 收集并断言 `GraphRunStartedEvent/AbortedEvent/PausedEvent`（`test_command_system.py:40`–`test_command_system.py:59`、`test_command_system.py:97`–`test_command_system.py:119`）。

样例 2：Redis 命令通道序列化
- 文件：`api/tests/unit_tests/core/workflow/graph_engine/test_redis_stop_integration.py`
- 关键点：验证 Manager/RedisChannel 的 send/fetch 行为、pending 标记、TTL、防御性 JSON 解析等（文件内多处）。

样例 3：变量池与运行态
- 文件：`api/tests/unit_tests/core/workflow/entities/test_variable_pool.py`
- 关键点：`VariablePool.empty()`、selector 访问、嵌套属性读取、越界/缺失键的异常覆盖（多段断言）。

## 事件断言与调试

- 引擎事件来源：
  - Worker 推送节点事件；Dispatcher 拉取后交由 `EventHandler`（`api/core/workflow/graph_engine/orchestration/dispatcher.py:101`–`api/core/workflow/graph_engine/orchestration/dispatcher.py:111`、`api/core/workflow/graph_engine/event_management/event_handlers.py:92` 起）。
  - 收尾事件由 `GraphEngine.run()` 统一产生（`api/core/workflow/graph_engine/graph_engine.py:248` 起）。
- 断点建议：
  - 节点 `_run()` 出口处（LLM/HTTP/Loop），便于观察 `NodeRunResult`；
  - `EventHandler._dispatch(NodeRunSucceededEvent)` 存变量与推进边（`api/core/workflow/graph_engine/event_management/event_handlers.py:151` 起）；
  - ResponseCoordinator 的 `intercept_event/try_flush`，用于调试流式输出组装（`api/core/workflow/graph_engine/response_coordinator/coordinator.py`）。
- 日志层：在 Debug 模式下，`WorkflowEntry` 默认注入 `DebugLoggingLayer`；也可手动追加 Layer 到 `GraphEngine`（`api/core/workflow/workflow_entry.py:96`–`api/core/workflow/workflow_entry.py:109`）。

## 快速构造与隔离

- 快速图构造：`Graph.new()` + `GraphBuilder.add_root/add_node/build()`（`api/core/workflow/graph/graph.py:200`、`api/core/workflow/graph/graph.py:376` 起）。
- 注入 NodeFactory：在 Graph.init 内部已处理；单测中更常见是直接使用已有节点类构建 `GraphBuilder`。
- 隔离外部依赖：
  - Redis：使用 `InMemoryChannel` 替代；或 `MagicMock` Redis 管道（参考 `test_redis_stop_integration.py`）。
  - Flask 上下文：`WorkerPool` 会在构造时传入 `flask_app/context_vars`，一般不需在单测中显式设置。

## 常用命令与检查

- 运行工作流相关单测：`uv run --project api --dev dev/pytest/pytest_unit_tests.sh`。
- 保存时间：可通过 `-k` 过滤某类测试，例如 `pytest -k graph_engine`。
- 代码规范：`make lint`、类型检查：`make type-check`。

## 额外建议

- 对新节点：优先为 NodeData 解析、`_run()` 正常/失败分支、变量池写入与事件流完结补单测。
- 对容器节点：补充循环中断、失败分支、子图输出合并等路径的断言。
- 对持久化：建议以仓储 Mock 校验 `WorkflowPersistenceLayer` 是否在正确事件上进行 save（减少对真实 DB 的依赖）。
