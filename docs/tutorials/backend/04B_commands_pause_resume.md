# 04B 夜班调度·其二：命令通道、暂停与恢复

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
- pause → PauseCommand；abort → AbortCommand；其它回退 GraphEngineCommand。

## 外部暂停 vs 节点自发暂停

- 外部暂停：
  - 发送：`GraphEngineManager.send_pause_command(task_id, reason)`。
  - 处理：`PauseCommandHandler.handle()` → `GraphExecution.pause(reason)`。
- 节点自发暂停：
  - 节点发 `PauseRequestedEvent`，基类映射 `NodeRunPauseRequestedEvent`。
  - 引擎事件处理器：`GraphExecution.pause(...)` + `GraphRuntimeState.register_paused_node(node_id)`，run 收尾产出 `GraphRunPausedEvent`。

ASCII：
```
Client ── send_pause ──▶ Redis("workflow:{task}:commands")
       ◀─────────────── CommandProcessor.fetch()
GraphExecution.pause(reason)
GraphRuntimeState.register_paused_node(node_id)
   └─▶ run() 收尾：GraphRunPausedEvent(outputs)
```

## 恢复：再次 run 即可

恢复没有单独命令；再次 `engine.run()` 即进入 resume 分支：
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
state = GraphRuntimeState.from_snapshot(load_snapshot(execution_id))
graph = Graph.init(graph_config=original_graph_config, node_factory=DifyNodeFactory(graph_init_params, state))
engine = GraphEngine(workflow_id, graph, state, command_channel)
for ev in engine.run():
    handle(ev)
```

下一篇（04C）：我们去机修间，聊聊并行扩缩容、层（Layer）与事件、以及“失败不等于崩溃”的错误策略矩阵。

