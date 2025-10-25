# 04A 夜班调度·其一：执行循环与就绪判定

夜半开场，调度主任带我们绕着控制台走一圈：左手是 ready_queue 的出入口，右手是事件分发台。我们先盯住“怎么跑起来”，再讲“节点什么时候算就绪”。

## GraphEngine 的上电自检

```python
# api/core/workflow/graph_engine/graph_engine.py（节选）
class GraphEngine:
    def __init__(self, workflow_id, graph, state, command_channel, ...):
        self._graph = graph
        self._graph_runtime_state = state
        self._graph_runtime_state.configure(graph=graph)

        self._graph_execution = state.graph_execution
        self._ready_queue = state.ready_queue
        self._event_queue = queue.Queue()

        self._state_manager = GraphStateManager(graph, self._ready_queue)
        self._response_coordinator = state.response_coordinator
        self._event_manager = EventManager()
        self._error_handler = ErrorHandler(graph, self._graph_execution)

        self._skip_propagator = SkipPropagator(graph=graph, state_manager=self._state_manager)
        self._edge_processor = EdgeProcessor(
            graph=graph,
            state_manager=self._state_manager,
            response_coordinator=self._response_coordinator,
            skip_propagator=self._skip_propagator,
        )
        self._command_processor = CommandProcessor(command_channel, self._graph_execution)
        self._worker_pool = WorkerPool(...)
        self._dispatcher = Dispatcher(event_queue=self._event_queue, ...)
```

ASCII 总览：
```
GraphEngine
  ├ state  ──► ready_queue / graph_execution / response_coordinator
  ├ state_manager ──► enqueue/start/mark/ready?
  ├ edge_processor + skip_propagator
  ├ worker_pool → Worker×N（拉活→node.run→事件）
  └ dispatcher/event_manager（收事件→推进→发事件）
```

## run() 的四幕戏

```python
def run(self):
    self._initialize_layers()                   # 幕前准备
    is_resume = self._graph_execution.started
    if not is_resume: self._graph_execution.start()
    else: self._graph_execution.paused = False

    yield GraphRunStartedEvent()                # 第一幕：宣布开场
    self._start_execution(resume=is_resume)     # 第二幕：工人上岗、root/paused 入队
    yield from self._event_manager.emit_events()# 第三幕：事件流不停
    ...                                         # 第四幕：收尾（paused/aborted/partial/success）
finally:
    self._stop_execution()                      # 落幕：停分发、停工人、通知 Layers
```

时序图：
```
WorkerPool          Dispatcher/EventHandler         EdgeProcessor/StateMgr
    |                        |                               |
    |  get ready node        |                               |
    |----------------------->|                               |
    |  node.run() 事件流     |-- put events -->[queue]-->    |
    |                        |-- handle(event) ------------->|
    |                        |   · mark success/fail         |
    |                        |   · edge taken/skip           |
    |                        |   · enqueue downstream        |
    |                        |<--------- ready nodes --------|
    |                        |-- enqueue/start -------------->
```

## 就绪判定与屏障语义

某节点何时“够格”进入 ready_queue？看入边状态：

```python
# api/core/workflow/graph_engine/graph_state_manager.py（节选）
def is_node_ready(self, node_id: str) -> bool:
    incoming = self._graph.get_incoming_edges(node_id)
    if not incoming:
        return True                   # 没有入边就随时可跑
    if any(e.state == UNKNOWN for e in incoming):
        return False                  # 有未知状态的入边，不可跑
    return any(e.state == TAKEN for e in incoming)  # 至少一条 TAKEN 即可
```

速记：
```
UNKNOWN 入边 = 屏障未开；
≥1 条 TAKEN = “或门”打开；
全 SKIPPED = 无需执行（不会 ready，也不会排队）。
```

这与 EdgeProcessor 的推进相呼应：当一条边标记为 TAKEN，就检查下游是否“或门打开”；未选分支的边会被标记为 SKIPPED，并触发 skip 传播（所有入边都 SKIPPED 的节点，也被标记为 SKIPPED）。

## Root/Paused 入队策略

- 首启：`_start_execution()` 把 root 节点 `enqueue_node()` 并 `start_execution()`。
- 恢复：`consume_paused_nodes()` 取出待续节点，逐一入队并标记开始执行。

```python
# api/core/workflow/graph_engine/graph_engine.py（节选）
if not resume:
    root = self._graph.root_node
    self._state_manager.enqueue_node(root.id)
    self._state_manager.start_execution(root.id)
else:
    for node_id in paused_nodes:
        self._state_manager.enqueue_node(node_id)
        self._state_manager.start_execution(node_id)
```

## 完结判定：既没活儿也没人干

GraphStateManager 用“就绪队列为空 + 正在执行集合为空”判断完结：

```python
def is_execution_complete(self) -> bool:
    return self._ready_queue.empty() and len(self._executing_nodes) == 0
```

下一篇（04B）：我们去命令室，看看 Redis 通道如何喊停、如何优雅地暂停并恢复；顺便学会把运行态装进“背包”带走。

