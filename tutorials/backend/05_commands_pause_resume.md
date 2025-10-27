# 05 夜班调度·其二：命令通道、暂停与恢复

主任把我们带进“电台室”。墙上两根粗线：一根接“命令通道”，一根接“快照柜”。今晚要学两件事：怎么喊停/暂停、怎么从半路恢复。

## Redis 命令通道：Key 与 JSON 长什么样

```
Key 约定：
  commands list   →  workflow:{task_id}:commands
  pending marker  →  workflow:{task_id}:commands:pending

入库流水（send_command）：
  RPUSH workflow:{task}:commands  <JSON>
  EXPIRE workflow:{task}:commands <ttl=3600 默认>
  SET   workflow:{task}:commands:pending "1" EX <ttl>

拉取流水（fetch_commands）：
  GET+DEL workflow:{task}:commands:pending  # 无 pending 则不扫列表
  LRANGE workflow:{task}:commands 0 -1
  DEL    workflow:{task}:commands
```

暂停命令 JSON 示例：

```json
{"command_type":"pause","payload":null,"reason":"Awaiting human input"}
```

反序列化映射：
- pause → PauseCommand；abort → AbortCommand；其它回退 GraphEngineCommand（实现见 [api/core/workflow/graph_engine/command_channels/redis_channel.py:95–121](../../api/core/workflow/graph_engine/command_channels/redis_channel.py#L95-L121)）。

## 外部暂停 vs 节点自发暂停

- 外部暂停：
  - 发送：`GraphEngineManager.send_pause_command(task_id, reason)`（见 [api/core/workflow/graph_engine/manager.py:39](../../api/core/workflow/graph_engine/manager.py#L39)）。
  - 处理：`PauseCommandHandler.handle()`（见 [api/core/workflow/graph_engine/command_processing/command_handlers.py:23–28](../../api/core/workflow/graph_engine/command_processing/command_handlers.py#L23-L28)） → `GraphExecution.pause(reason)`（见 [api/core/workflow/graph_engine/domain/graph_execution.py:133–143](../../api/core/workflow/graph_engine/domain/graph_execution.py#L133-L143)）。
- 节点自发暂停：
  - 节点发 `PauseRequestedEvent`，基类映射 `NodeRunPauseRequestedEvent`。
  - 引擎事件处理器：`GraphExecution.pause(...)` + `GraphRuntimeState.register_paused_node(node_id)`，run 收尾产出 `GraphRunPausedEvent`。

ASCII：
```
Client ── send_pause ──▶ Redis("workflow:{task}:commands")
       ◀─────────────── CommandProcessor.fetch()
GraphExecution.pause(reason)
GraphRuntimeState.register_paused_node(node_id)（见 [api/core/workflow/runtime/graph_runtime_state.py:337–341](../../api/core/workflow/runtime/graph_runtime_state.py#L337-L341)）
   └─▶ run() 收尾：GraphRunPausedEvent(outputs)
```

## 恢复：再次 run 即可

恢复没有单独命令；再次 `engine.run()` 即进入 resume 分支（见 [api/core/workflow/graph_engine/graph_engine.py:231–246](../../api/core/workflow/graph_engine/graph_engine.py#L231-L246)）：
- `consume_paused_nodes()` 取出待续节点并重新入队；
- 清除 paused 标记与 reason，照常推进。

```python
# api/core/workflow/graph_engine/graph_engine.py（节选）
is_resume = self._graph_execution.started
if not is_resume: self._graph_execution.start()
else: self._graph_execution.paused = False; self._graph_execution.pause_reason = None
...
if not resume:
    enqueue(root)
else:
    for node_id in state.consume_paused_nodes(): enqueue(node_id)
```

## 跨进程恢复：把“背包”放进快照柜

默认只有运行账本落库（WorkflowExecution/NodeExecution）。要想无损续跑，请在暂停时保存运行态快照：

```python
class SnapshotPersistenceLayer(GraphEngineLayer):
    def on_event(self, event):
        from core.workflow.graph_events import GraphRunPausedEvent
        if isinstance(event, GraphRunPausedEvent):
            snapshot = self.graph_runtime_state.dumps()  # JSON, 含 ready_queue/paused_nodes/outputs/...
            save_snapshot(execution_id=self._exec_id(), payload=snapshot)
```

恢复时：

```python
state = GraphRuntimeState.from_snapshot(load_snapshot(execution_id))  # 见 [graph_runtime_state.py:314–329](../../api/core/workflow/runtime/graph_runtime_state.py#L314-L329)
graph = Graph.init(graph_config=original_graph_config, node_factory=DifyNodeFactory(graph_init_params, state))
engine = GraphEngine(workflow_id, graph, state, command_channel)
for ev in engine.run():
    handle(ev)
```

### 为什么没有“resume 命令”？

恢复被设计成“再次 run()”，好处是：
- 同进程：直接用内存里的 GraphRuntimeState（含 paused_nodes/ready_queue/variable_pool 等）续跑；
- 跨进程：先 from_snapshot 重建 GraphRuntimeState，再用原 graph_config 重建 Graph，然后 run() 按恢复分支推进；
- 语义简单：停止/暂停用命令，恢复就是“启动”，不必维护额外的命令语义和竞态。

### TTL 与 pending 标记的取舍

- TTL：命令队列与 pending 标记默认 3600s，控制面数据过期即清理，避免长期积压。
- pending：先 GET+DEL pending 才 LRANGE 列表，未设置 pending 则不扫表，降低空轮询对 Redis 的压力。
- 幂等：多次 pause 只会置位，已 paused 的执行不会重复写状态；Redis 不可用时 Manager 静默失败（降级）。

### 快照存储介质与安全（重要）

- 快照体积：`GraphRuntimeState.dumps()` 会包含 `variable_pool/ready_queue/graph_execution/paused_nodes/outputs/llm_usage` 等；若变量多/文件多，JSON 会较大，建议放对象存储或专用表，并做压缩。
- 敏感信息：`variable_pool` 可能包含凭证/API 返回/用户上传内容。持久化前应按你的合规要求“打码”或过滤；
  - 例如对系统变量/环境变量做白名单只存允许的键；
  - 文件引用可只存 metadata（id/url/hash），避免存二进制。
- 会话数据：PersistenceLayer 在准备 WorkflowExecution.inputs 时特意剔除了会话 ID（convo_id），避免将运行绑定到特定会话（见 persistence.py `_prepare_workflow_inputs`）。快照里若仍带会话上下文，也应考虑脱敏。

下一篇（06）：我们去机修间，聊聊并行扩缩容、层（Layer）与事件、以及“失败不等于崩溃”的错误策略矩阵。

## 命令体系总览（类型与模型）

- 命令类型：`abort`、`pause`（见 `CommandType`，`api/core/workflow/graph_engine/entities/commands.py:14`）。
- 数据模型：`AbortCommand`、`PauseCommand` 继承自 `GraphEngineCommand`（见 `api/core/workflow/graph_engine/entities/commands.py:21`）。
- 协议接口：`CommandChannel` 规定 `fetch_commands()/send_command()`（见 `api/core/workflow/graph_engine/protocols/command_channel.py:13`）。

小抄：
```json
{"command_type":"abort","payload":null,"reason":"User requested stop"}
```

## 处理链路（注册与轮询）

- 注册处理器：引擎在构造阶段注册 `AbortCommandHandler`/`PauseCommandHandler`（见 `api/core/workflow/graph_engine/graph_engine.py:129`、`api/core/workflow/graph_engine/graph_engine.py:136`）。
- 轮询触发：
  - 调度线程在以下时机检查命令：
    - 收到节点“终结类”事件后（`Succeeded/Failed/Exception`）（见 `api/core/workflow/graph_engine/orchestration/dispatcher.py:36`、`api/core/workflow/graph_engine/orchestration/dispatcher.py:101`、`api/core/workflow/graph_engine/orchestration/dispatcher.py:113`）。
    - 空转时也会周期性检查，避免漏掉停止请求（见 `api/core/workflow/graph_engine/orchestration/dispatcher.py:108`–`api/core/workflow/graph_engine/orchestration/dispatcher.py:111`）。
  - 命令拉取和分派由 `CommandProcessor` 完成（见 `api/core/workflow/graph_engine/command_processing/command_processor.py:56`、`api/core/workflow/graph_engine/command_processing/command_processor.py:65`）。

提示：`ExecutionCoordinator.is_execution_complete()` 把 `paused/aborted/error` 当作“终结态”，因此命令一旦生效，调度循环会尽快收尾（见 `api/core/workflow/graph_engine/orchestration/execution_coordinator.py:58`–`api/core/workflow/graph_engine/orchestration/execution_coordinator.py:65`）。

## 暂停/中止的可观测结果

- 暂停：`GraphExecution.is_paused=True`，`run()` 收尾产出 `GraphRunPausedEvent(outputs, reason)`（见 `api/core/workflow/graph_engine/graph_engine.py:248`–`api/core/workflow/graph_engine/graph_engine.py:255`）。
- 中止：`GraphRunAbortedEvent(outputs, reason)`（见 `api/core/workflow/graph_engine/graph_engine.py:256`–`api/core/workflow/graph_engine/graph_engine.py:265`）。
- 错误：`GraphRunFailedEvent`（见 `api/core/workflow/graph_engine/graph_engine.py:286`–`api/core/workflow/graph_engine/graph_engine.py:293`）。

补充：节点自发暂停事件处理时会把该节点标记出执行队列、并把节点状态复位为 `UNKNOWN` 以便恢复后可重新调度（见 `api/core/workflow/graph_engine/event_management/event_handlers.py:208`–`api/core/workflow/graph_engine/event_management/event_handlers.py:217`）。

## InMemory 通道与本地开发

- `InMemoryChannel` 通过线程安全队列实现，适合单进程本地/单元测试（见 `api/core/workflow/graph_engine/command_channels/in_memory_channel.py:15`、`api/core/workflow/graph_engine/command_channels/in_memory_channel.py:27`）。
- `WorkflowEntry` 默认未显式传入时会使用 InMemory 通道，并把它注入 `GraphEngine`（见 `api/core/workflow/workflow_entry.py:41`、`api/core/workflow/workflow_entry.py:62`）。

## 控制面入口与“双停机制”

- 控制面 API：`POST /service-api/workflows/tasks/{task_id}/stop` 既设置“旧的停止标记”，也通过新通道发送 `abort`，两套机制并存以保证兼容（见 `api/controllers/service_api/app/workflow.py:250`、`api/controllers/service_api/app/workflow.py:275`）。
- 旧机制：`AppQueueManager.set_stop_flag_no_user_check(task_id)` 写入 `generate_task_stopped:{task_id}`，用于老消费方轮询停止（见 `api/core/app/apps/base_app_queue_manager.py:160`、`api/core/app/apps/base_app_queue_manager.py:176`）。
- 新机制：`GraphEngineManager.send_stop_command(task_id)` 通过 Redis 通道下发（见 `api/core/workflow/graph_engine/manager.py:26`、`api/core/workflow/graph_engine/manager.py:35`）。
- 单测参考：`test_redis_stop_integration.py` 覆盖了 send/receive 细节与双机制并存（见 `api/tests/unit_tests/core/workflow/graph_engine/test_redis_stop_integration.py:1`）。

## 竞态与触发边界（实践建议）

- 生效边界：命令在调度线程“事件处理的间隙”或“空转检查”时生效；正在运行的节点不会被强制中断，属于“协作式停止”。
- Worker 停止：当执行进入 `paused/aborted` 终结态后，`_stop_execution()` 会停止调度器与工作池，避免继续取新任务（见 `api/core/workflow/graph_engine/graph_engine.py:341`–`api/core/workflow/graph_engine/graph_engine.py:349`）。
- 扩展点：`ExecutionCoordinator.handle_pause_if_needed/handle_abort_if_needed` 提供“立即停工并清空执行中的节点”的钩子，适用于需要更激进的停机策略的场景（见 `api/core/workflow/graph_engine/orchestration/execution_coordinator.py:88`、`api/core/workflow/graph_engine/orchestration/execution_coordinator.py:97`）。

## 常见问题（FAQ）

- 为什么暂停后恢复会从该节点“重新开始”？
  - 节点自发暂停时会把节点状态重置为 `UNKNOWN` 并登记到 `paused_nodes`，恢复时重新入队（见 `api/core/workflow/graph_engine/event_management/event_handlers.py:213`、`api/core/workflow/runtime/graph_runtime_state.py:337`）。
- 恢复时流式输出还能接上吗？
  - 若仅同进程恢复：`ResponseCoordinator` 仍在内存，能继续基于变量池/缓冲推进；跨进程则需要将 `response_coordinator.dumps()` 一并入快照（`GraphRuntimeState.dumps()` 已内置，见 `api/core/workflow/runtime/graph_runtime_state.py:309`–`api/core/workflow/runtime/graph_runtime_state.py:312`）。
- Redis 掉线发送命令会怎样？
  - `GraphEngineManager._send_command` 对异常静默，旧机制仍可兜底（见 `api/core/workflow/graph_engine/manager.py:55`–`api/core/workflow/graph_engine/manager.py:60`）。

## 彩蛋：在 Layer 里下达命令

`GraphEngineLayer.initialize()` 会注入只读运行态与 `CommandChannel`，你可以在 Layer 内基于业务策略主动下达暂停/停止：

```python
from core.workflow.graph_engine.layers.base import GraphEngineLayer
from core.workflow.graph_engine.entities.commands import PauseCommand

class QuotaGuardLayer(GraphEngineLayer):
    def on_graph_start(self):
        pass

    def on_event(self, event):
        if self.graph_runtime_state.total_tokens > 100_000:
            # 发送暂停，等待人工处理
            self.command_channel.send_command(PauseCommand(reason="Quota exceeded"))

    def on_graph_end(self, error: Exception | None):
        pass
```

这类策略和“快照层”可以搭配使用，在 `GraphRunPausedEvent` 时一并落快照，实现“自动刹车 + 可续跑”。
