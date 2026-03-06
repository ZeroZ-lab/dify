# 07 测试策略与调试路径

巡礼的最后一站是“实验室”。这里摆放着覆盖层层模块的单元测试、用于本地排障的脚本、以及能让事件流一览无遗的调试层。掌握这些工具，你就能
在不依赖生产环境的前提下复现大多数问题，并给出可靠修复方案。

## 学习成果

- 熟悉核心工作流模块的单元测试目录、夹具组织方式与模拟策略。
- 能够快速定位某段逻辑对应的测试案例，并据此复现或验证缺陷。
- 掌握常用调试技巧：调试层日志、事件监听、Redis/命令通道的模拟。

## 引导问题

1. 工作流相关测试主要分布在哪些子目录？各自关注什么？
2. 单元测试如何模拟 Graph Engine、变量池和外部依赖（如 Redis）？
3. 运行测试时有哪些推荐脚本或超时时间设置？
4. 调试日志层、事件监听器如何帮助还原节点执行？
5. 出现运行异常时，应该在哪些断点或事件上排查？

## 必读源码

- `api/tests/unit_tests/core/workflow/`
- `api/tests/unit_tests/conftest.py`
- `dev/pytest/pytest_unit_tests.sh`
- `api/core/workflow/graph_engine/layers/debug_logging.py`
- `api/core/workflow/graph_engine/layers/persistence.py`

## Walkthrough

### 1. 测试目录导览

`api/tests/unit_tests/core/workflow/` 目录按职能划分：`graph_engine/` 关注调度器状态、命令通道；`graph/` 负责 DSL 转换与校验；`nodes/` 则针对
单个节点 `_run()` 的输入输出；`entities/`、`utils/` 等目录测试数据结构或辅助函数。了解目录结构，能让你根据 bug 类型迅速定位已有案例。

全局 `conftest.py`（`api/tests/unit_tests/conftest.py`）提供 Flask 应用上下文与 Redis Mock。它在模块级别打补丁 `ext_redis.redis_client`，确保
所有测试共享同一组伪造的 `get/set` 行为，并在每个用例前自动重置，避免状态泄漏。这种方式让 Graph Engine 的命令通道、缓存逻辑都能在纯内存
环境运行。【F:api/tests/unit_tests/conftest.py†L1-L60】

### 2. Arrange-Act-Assert：以 Graph Engine 测试为例

挑一个图引擎测试（如 `test_workflow_entry.py`），你会看到典型的三段式结构：

1. **Arrange**：构造变量池、Graph 模板、节点假实现。
2. **Act**：调用 `WorkflowEntry.run()` 或 Graph Engine 的 `run()` 方法，让生成器产出事件。
3. **Assert**：断言事件序列、节点状态、变量池输出，与预期完全匹配。

通过阅读这些断言，可以总结哪些字段是运行正确与否的信号（例如 `WorkflowNodeExecutionStatus`、`GraphRunSucceededEvent.outputs`），在调试
时对照即可。

### 3. 运行脚本与超时

`dev/pytest/pytest_unit_tests.sh` 定义了默认的运行命令：设置 `PYTEST_TIMEOUT`（默认 20 秒），然后执行 `pytest --timeout <值> api/tests/unit_tests`。
当你只需跑单个目录时，可以覆写 `PYTEST_TIMEOUT` 并传入 `-k` 过滤表达式。结合仓库根目录的 `make lint`、`make type-check`，就形成了基本的本地
质量验证流程。【F:dev/pytest/pytest_unit_tests.sh†L1-L20】

### 4. 调试层与日志

Graph Engine 支持挂载 `DebugLoggingLayer`（`api/core/workflow/graph_engine/layers/debug_logging.py`）：

- `on_graph_start()` 会打印分隔线并记录初始状态；
- `on_event()` 针对不同事件输出详细日志（包含重试次数、输出摘要等），还能按需显示 inputs、outputs、process_data；
- 内部还维护了节点统计计数器，方便确认哪些节点成功、失败或重试。

在本地调试时，只需在 `WorkflowEntry` 构造后手动 `graph_engine.layer(DebugLoggingLayer(level="DEBUG", include_inputs=True))`，就能获得详
细事件轨迹。【F:api/core/workflow/graph_engine/layers/debug_logging.py†L1-L200】

### 5. 实战排障建议

- **节点级问题**：在节点 `_run()` 中打断点，关注 `NodeRunResult` 或 `StreamChunkEvent` 是否符合预期。
- **变量不对**：检查 `VariablePool` 的 `add/get` 调用，或在测试里断言 `graph_runtime_state.outputs`。
- **运行停止/异常**：观察事件流是否出现 `NodeRunFailedEvent`、`GraphRunFailedEvent`；结合 `DebugLoggingLayer` 日志定位。
- **命令通道**：查看 Redis Mock 的调用次数，确保暂停/恢复命令正确发送。

## 动手任务

- 运行任意一个 `graph_engine` 相关测试，对照源码记录关键断言对应的实现位置。
- 在本地启动一个最小化工作流（或使用测试夹具），启用 `DebugLoggingLayer`，整理一段包含开始/成功/流式片段的日志样例。

## 思考题

- 当前单元测试覆盖是否包含所有节点类型？对于新节点应补充哪些场景？
- 如果要编写端到端测试覆盖服务层到节点执行的链路，你会如何模拟外部依赖（模型、Redis、数据库）？

## 延伸阅读

- `CONTRIBUTING.md` 中的测试指南
- `docs/zh-CN/README.md` 对工作流功能的描述
- 真实 Issues/PR 中的调试讨论，了解常见排障思路

