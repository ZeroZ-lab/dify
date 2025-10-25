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
