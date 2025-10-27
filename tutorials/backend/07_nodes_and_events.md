# 07 节点实现与事件联动

## 学习成果
- 掌握节点基类的运行壳与事件映射（run/_run/singledispatch）
- 理解 LLM/HTTP/Loop 等典型节点的实现差异与输出形态
- 熟悉节点事件 → 引擎事件 → 响应/持久化的传播链路

本篇深入节点基类到典型实现，串起“节点内部事件 → 引擎 Graph 事件”的完整链路，并给出精确源码锚点。

## 基类 Node：执行壳与事件桥

- 构造与上下文注入：基类在构造时注入租户、应用、工作流、调用方等上下文，以及共享的 `GraphRuntimeState`（见 `api/core/workflow/nodes/base/node.py:18` 起）。
- run 包装器：`run()` 负责生成一次性的 node_execution_id、产生 `NodeRunStartedEvent`，并将 `_run()` 的返回结果统一转为图事件（`GraphNodeEventBase`），见：
  - 创建 started 事件与 ID 复用：`api/core/workflow/nodes/base/node.py:36`、`api/core/workflow/nodes/base/node.py:49`。
  - 处理 `_run()` 同步结果 `NodeRunResult` 与事件流：`api/core/workflow/nodes/base/node.py:81`–`api/core/workflow/nodes/base/node.py:107`。
  - 异常兜底映射为 `NodeRunFailedEvent`：`api/core/workflow/nodes/base/node.py:108`–`api/core/workflow/nodes/base/node.py:123`。
- 事件转换器：基类以 singledispatch 将节点内部事件（`node_events`）翻译为图事件（`graph_events`）：
  - 流式与完成：`StreamChunkEvent` → `NodeRunStreamChunkEvent`（`api/core/workflow/nodes/base/node.py:197`），`StreamCompletedEvent` → `NodeRunSucceeded/FailedEvent`（`api/core/workflow/nodes/base/node.py:201`–`api/core/workflow/nodes/base/node.py:224`）。
  - 暂停：`PauseRequestedEvent` → `NodeRunPauseRequestedEvent`（`api/core/workflow/nodes/base/node.py:238`–`api/core/workflow/nodes/base/node.py:244`）。
  - 容器与智能体：Loop/Iteration/Agent 系列事件到对应 Graph 事件的映射，参见 `api/core/workflow/nodes/base/node.py:246` 起各 `@_dispatch.register` 实现。
- NodeRunResult 映射：`_convert_node_run_result_to_graph_node_event()` 将 “SUCCEEDED/FAILED” 结果映射到图事件（`api/core/workflow/nodes/base/node.py:164`–`api/core/workflow/nodes/base/node.py:192`）。
- 子类契约：子类需实现 `init_node_data()` 与 `_run()`，以及一组元信息/策略访问器（错误策略、重试、标题、默认值等），见 `api/core/workflow/nodes/base/node.py:132`–`api/core/workflow/nodes/base/node.py:162`。

小抄：基类保证“事件语义统一”，子类只管专注业务与产出 NodeRunResult 或节点内部事件流。

## 典型节点对比

### LLM 节点（流式）
- 文件：`api/core/workflow/nodes/llm/node.py`
- 特点：以生成器形式产出流式块与最终完成事件；同时收集 usage 与结构化输出。
- 关键点：
  - `_run()` 主体：`api/core/workflow/nodes/llm/node.py:166` 起。
  - 消费模型事件并透传流式块：`api/core/workflow/nodes/llm/node.py:267`–`api/core/workflow/nodes/llm/node.py:286`。
  - 发送最终“空块”作为结束标记，再发送 `StreamCompletedEvent`：`api/core/workflow/nodes/llm/node.py:320`–`api/core/workflow/nodes/llm/node.py:353`。
  - 失败映射为失败的 `StreamCompletedEvent`：`api/core/workflow/nodes/llm/node.py:352`–`api/core/workflow/nodes/llm/node.py:356` 与 `api/core/workflow/nodes/llm/node.py:357`–`api/core/workflow/nodes/llm/node.py:382`。

要点：LLM 节点不直接触达引擎，所有事件经过基类转译为 `GraphNodeEventBase`，随后由引擎的 `EventHandler` 处理写入变量池与推进边。

### HTTP Request 节点（一次性返回）
- 文件：`api/core/workflow/nodes/http_request/node.py`
- 特点：返回单个 `NodeRunResult`，适配失败策略与默认值。
- 关键点：
  - `_run()` 返回 `NodeRunResult(SUCCEEDED|FAILED)`，包含 `status_code/body/headers/files` 等（`api/core/workflow/nodes/http_request/node.py:89`–`api/core/workflow/nodes/http_request/node.py:144`）。
  - 节点默认配置与重试参数示例：`get_default_config()`（`api/core/workflow/nodes/http_request/node.py:117`–`api/core/workflow/nodes/http_request/node.py:141`）。

### Loop 容器节点（子图驱动）
- 文件：`api/core/workflow/nodes/loop/loop_node.py`
- 特点：容器型节点，驱动子图多轮执行，并产出 Loop 系列事件供 UI/审计。
- 关键点：
  - `_run()` 产出 `LoopStarted/Next/Succeeded/Failed` 事件并在内部通过 `GraphEngine.run()` 执行子图（`api/core/workflow/nodes/loop/loop_node.py:79`–`api/core/workflow/nodes/loop/loop_node.py:218`）。
  - 将子图的 `GraphNodeEventBase` 透传并打上 loop 元数据（`api/core/workflow/nodes/loop/loop_node.py:262`–`api/core/workflow/nodes/loop/loop_node.py:313`）。
  - 完成时发 `StreamCompletedEvent` 携带聚合的 `NodeRunResult`（成功/失败）（`api/core/workflow/nodes/loop/loop_node.py:200`–`api/core/workflow/nodes/loop/loop_node.py:218`，`api/core/workflow/nodes/loop/loop_node.py:318`–`api/core/workflow/nodes/loop/loop_node.py:341`）。

## 事件传播：节点 → 引擎 → 响应/持久化

- Worker 线程把节点事件放入引擎事件队列；Dispatcher 取走并交给 `EventHandler`：
  - `NodeRunStartedEvent` 更新追踪并可能收集（`api/core/workflow/graph_engine/event_management/event_handlers.py:108` 起）。
  - `NodeRunStreamChunkEvent` 经 ResponseCoordinator 归并与前置输出（`api/core/workflow/graph_engine/event_management/event_handlers.py:128`–`api/core/workflow/graph_engine/event_management/event_handlers.py:140`）。
  - `NodeRunSucceededEvent` 存 outputs 到变量池、处理边、入队下游（`api/core/workflow/graph_engine/event_management/event_handlers.py:151`–`api/core/workflow/graph_engine/event_management/event_handlers.py:205`）。
  - `NodeRunPauseRequestedEvent` 触发图暂停并登记待续节点（`api/core/workflow/graph_engine/event_management/event_handlers.py:207`–`api/core/workflow/graph_engine/event_management/event_handlers.py:217`）。
- 图级收尾事件：`GraphEngine.run()` 根据执行聚合产出 `GraphRunSucceeded/PartialSucceeded/Failed/Aborted/Paused`（`api/core/workflow/graph_engine/graph_engine.py:248`–`api/core/workflow/graph_engine/graph_engine.py:284`）。

## 节点注册与工厂

- 工厂实现：`DifyNodeFactory` 根据 `NODE_TYPE_CLASSES_MAPPING` 实例化节点，注入同一 `GraphRuntimeState` 实例（`api/core/workflow/nodes/node_factory.py:12`、`api/core/workflow/nodes/node_factory.py:37`–`api/core/workflow/nodes/node_factory.py:76`）。
- Graph 在 `init()` 时用 NodeFactory 组装节点、建立入出边、提升 FAIL_BRANCH 节点为 BRANCH 执行类型（`api/core/workflow/graph/graph.py:190`–`api/core/workflow/graph/graph.py:197`、`api/core/workflow/graph/graph.py:206`–`api/core/workflow/graph/graph.py:215`）。

## 实战建议

- 设计节点时，优先返回 `NodeRunResult` 或（必要时）产生小而快的事件流；流式场景下最后发送 `StreamCompletedEvent`，并保证基类能翻译出收尾的 `NodeRunSucceeded/FailedEvent`。
- 需要暂停时，发 `PauseRequestedEvent`，引擎会把该节点恢复为 `UNKNOWN` 并登记 `paused_nodes`；下次 run() 自动入队续跑。
- 变量依赖可通过各节点的 `extract_variable_selector_to_variable_mapping()` 静态分析，Loop/Iteration 节点已提供实现示例。

## 延伸阅读

- 事件到响应协调：`api/core/workflow/graph_engine/response_coordinator/coordinator.py`
- 事件到持久化：`api/core/workflow/graph_engine/layers/persistence.py`
- 单测路径：`api/tests/unit_tests/core/workflow/nodes/` 与 `graph_engine/`，如 LLM/HTTP/Loop 的行为断言
