# 04 夜班调度·其一：执行循环与就绪判定

夜半开场，调度主任带我们绕着控制台走一圈：左手是 ready_queue 的出入口，右手是事件分发台。我们先盯住“怎么跑起来”，再讲“节点什么时候算就绪”。

夜巡随笔（00:07）
- 值班钟一响，GraphEngine 像老戏骨一样清嗓：“各位，今晚按四幕走台！”
- ReadyQueue 是门口的闸机，工牌对了就“滴”一声放行；
- Dispatcher 拿着对讲机：“事件到我这儿别挤，排队领流程。”
- Worker 小分队拎着工具箱，谁也不知道下一分钟会被派去修 LLM 还是搬 HTTP。

机房小地图（ASCII）
```
┌───────────────┐    ┌─────────────────┐    ┌──────────────────┐
│ ReadyQueue 门岗│───▶│ Worker 小分队区 │───▶│ 事件队列 (queue) │
└───────────────┘    └─────────────────┘    └──────────────────┘
        ▲                        │                     │
        │                        ▼                     ▼
   GraphStateMgr         EdgeProcessor           Dispatcher / EventMgr
        │                        │                     │
        └───────────── Graph ────┴───────────────► 响应协调台
```

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

## run() 的四幕戏（见 [api/core/workflow/graph_engine/graph_engine.py:220–297](../../api/core/workflow/graph_engine/graph_engine.py#L220-L297)）

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

舞台侧记（旁白）
- 第一幕，灯光一打，GraphRunStartedEvent 像开场锣：仓库门升起、路线灯变绿；
- 第二幕，主任把“root 工单”塞进 ReadyQueue，或者把“暂停名单”一一叫醒；
- 第三幕，工人们不断带回 NodeRunStarted/StreamChunk/Succeeded 的“传票”，Dispatcher 一边盖章一边往下家推进；
- 第四幕，夜色将尽：有人打卡“Paused”，有人签字“Aborted”，若一路安稳，就让 Succeeded 挂在公告栏。

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

## 就绪判定与屏障语义（见 [api/core/workflow/graph_engine/graph_state_manager.py:66–93](../../api/core/workflow/graph_engine/graph_state_manager.py#L66-L93)）

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

门岗传说（小剧场）
- 门神 UNKNOWN：爱说“我不认识你”，一开口就把候选人拦在闸机外；
- 开闸 TAKEN：像夜班钥匙，只要有一把是真钥匙，闸机就“叮”地一声放人；
- 全跳 SKIPPED：这条通道今夜封闭，门岗摆手：“走吧走吧，别等了。”

## Root/Paused 入队策略（见 [api/core/workflow/graph_engine/graph_engine.py:314–341](../../api/core/workflow/graph_engine/graph_engine.py#L314-L341)）

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

宿舍与叫醒服务（夜谈）
- root 是夜班第一声点名，必须先上岗，像是“今夜的总钥匙”；
- paused 列表则是被“临时外派去打盹”的同事，恢复时一个个拍肩点名：进队列，开工；
- 叫醒员是 GraphStateManager：既负责排队，也负责登记谁正在干活，防止“同一人同时上两班”。

## 完结判定：既没活儿也没人干

GraphStateManager 用“就绪队列为空 + 正在执行集合为空”判断完结：

```python
def is_execution_complete(self) -> bool:
    return self._ready_queue.empty() and len(self._executing_nodes) == 0
```

## 就绪/状态速查矩阵（边 → 节点）

```
入边状态集合           → 节点是否 ready     → 节点状态
────────────────────────────────────────────────────────
空集（无入边）         → 是                 → 待入队（root 等）
包含 UNKNOWN            → 否                 → 等待（屏障未开）
至少一条 TAKEN          → 是                 → 可入队
全部 SKIPPED            → 否                 → 最终会被标为 SKIPPED（不执行）
```

GraphStateManager 还提供了 `analyze_edge_states()`（has_unknown/has_taken/all_skipped），用于判断推进逻辑与 skip 传播的条件（见 [api/core/workflow/graph_engine/graph_state_manager.py:129–146](../../api/core/workflow/graph_engine/graph_state_manager.py#L129-L146)）。

## ReadyQueue 工厂与可替换实现

默认使用 `InMemoryReadyQueue`，同时保留 `create_ready_queue_from_state` 工厂，允许你按需实现持久/分布式就绪队列（实现 dumps/loads、put/get/task_done/empty/qsize 即可）。

```
ready_queue.dumps()   → 序列化排队节点（用于快照）
ready_queue.loads(s)  → 恢复队列（跨进程恢复）
```

换车无痛指南（彩蛋）
- InMemoryReadyQueue 像厂内小推车，好推好停；
- 若要换成“分布式叉车”，只需实现同一套接口（put/get/task_done/empty/qsize/dumps/loads），原有工人与调度都不用重新培训；
- 快照时，连车上堆的货（排队节点）都能一起装箱带走。

## 容器节点的边界：Iteration/Loop 的入口判定

在校验规则里，除了真正的 root，容器入口也被认可为“可作为起点”的节点类型（见 [api/core/workflow/graph/validation.py:69–76](../../api/core/workflow/graph/validation.py#L69-L76)）：

```
_RootNodeValidator.container_entry_types = (ITERATION_START, LOOP_START)
```

这意味着：
- 当一个子图以 `iteration-start` 或 `loop-start` 开头时，它可以作为容器内部的“根”，由父节点（`iteration/loop`）调度进入；
- 容器本体（`iteration`/`loop`）的 `NodeExecutionType` 通常是 CONTAINER，负责管理子图的多次/多轮执行；
- 就绪规则依旧生效：进入容器入口前，父级的出边必须到位（TAKEN）；容器内部的推进再遵循本章的“或门/skip”语义。

ASCII（简化）：
```
iteration(CONTAINER)
  └─▶ iteration-start(ROOT in container)
          └─▶ ... 子图 ...

loop(CONTAINER)
  └─▶ loop-start(ROOT in container)
          └─▶ ... 子图（多轮）...
```

实务提醒：容器如何“多次/多轮”驱动子图，属于节点实现与事件配合的内容，会在节点篇（05）里详细展开。

夜班尾声（04:42）
- 调度主任合上记录本：ready_queue 归零、执行集清空，今晚的车间安安静静；
- 墙上的指示灯从“运行”切回“待命”，Layers 收到 on_graph_end 的最后一声招呼；
- 我们把喇叭递给下一班的同事：去 05 篇的命令室试试对讲机吧——学会优雅地喊停、按下“暂停”，再把一切原样带回舞台中央。
