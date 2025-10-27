# 00 夜班花名册与导览地图

开场白：今晚先发一份“夜班手册”。别慌着开机器，先认人、认路、认对讲机。等你把花名册背熟了，后面的 01–09 篇就像逛自家工厂一样顺路。

## 角色花名册（岗位 → 角色 → 职责）

```
┌──────────────────────┬──────────────────────┬─────────────────────────────────┐
│ ReadyQueue 门岗      │ 闸机                 │ 排队放行（put/get/task_done）   │
│ GraphStateManager    │ 班长/记账员          │ enqueue/start/finish，判定 ready │
│ WorkerPool           │ 工人队               │ 拉单→node.run→产出事件          │
│ Dispatcher           │ 调度台               │ 收事件→分派给 EventHandler       │
│ EventHandler         │ 站务员               │ 处理 Node/Graph 事件，推进边      │
│ EventManager         │ 播音员/收发室        │ 收集事件、通知 Layers、emit 流出  │
│ ResponseCoordinator  │ 接驳员/导演          │ 登记 RESPONSE 节点、组织流式输出 │
│ EdgeProcessor        │ 转辙员               │ 标记 TAKEN/SKIPPED、放行下游      │
│ SkipPropagator       │ 交通警               │ 未选分支全线 SKIPPED 级联         │
│ ErrorHandler         │ 急救箱/医生          │ 重试、异常分支、默认值、终止       │
│ CommandChannel       │ 电台（Redis/内存）    │ 外部下达 stop/pause 指令           │
│ CommandProcessor     │ 指挥台               │ 拉取指令并分派处理器               │
│ Layers               │ 巡逻队               │ 日志、限额、持久化、快照等         │
│ GraphRuntimeState    │ 账本/背包            │ variable_pool/outputs/ready_queue │
│ GraphExecution       │ 大钟/跑表            │ started/paused/aborted/completed  │
└──────────────────────┴──────────────────────┴─────────────────────────────────┘
```

## 岗位关系连线图（一眼看懂协作链）

```
  电台(CommandChannel) ──▶ 指挥台(CommandProcessor) ─┐
                                                     ▼
  工单(ready_queue) ─▶ 班长(StateMgr) ─▶ 工人(Workers) ─▶ 事件队列(queue)
                                                     │             │
                                                     ▼             ▼
                                              调度台(Dispatcher) ─▶ 播音员(EventManager)
                                                     │             ▲
                                                     ▼             │
                                              站务员(EventHandler) │
                                                     │             │
               转辙员(EdgeProcessor) ◀───────────────┘             │
                    │        ▲                                    │
          交通警(SkipProp.)  │                                    │
                    ▼        │                                    │
              下游放行/封线  │                            巡逻队(Layers)

账本区：账本/背包(GraphRuntimeState) 记录 ready_queue / graph_execution / outputs / variable_pool
大钟台：大钟(GraphExecution) 记录 started/paused/aborted/completed 与异常计数
```

## 快速索引（点击直达源码）

- 执行循环：GraphEngine.run（见 [api/core/workflow/graph_engine/graph_engine.py:220–297](../../api/core/workflow/graph_engine/graph_engine.py#L220-L297)）
- 就绪判定与入队：GraphStateManager（见 [api/core/workflow/graph_engine/graph_state_manager.py:66–93](../../api/core/workflow/graph_engine/graph_state_manager.py#L66-L93)）
- 事件收发：EventManager（见 [api/core/workflow/graph_engine/event_management/event_manager.py:1](../../api/core/workflow/graph_engine/event_management/event_manager.py#L1)）
- 事件处理：EventHandler（见 [api/core/workflow/graph_engine/event_management/event_handlers.py:1](../../api/core/workflow/graph_engine/event_management/event_handlers.py#L1)）
- 错误急救：ErrorHandler（见 [api/core/workflow/graph_engine/error_handler.py:1](../../api/core/workflow/graph_engine/error_handler.py#L1)）
- 转辙/封线：EdgeProcessor 与 SkipPropagator（见 [api/core/workflow/graph_engine/graph_traversal/edge_processor.py:1](../../api/core/workflow/graph_engine/graph_traversal/edge_processor.py#L1)，[api/core/workflow/graph_engine/graph_traversal/skip_propagator.py:1](../../api/core/workflow/graph_engine/graph_traversal/skip_propagator.py#L1)）
- 工人调度：WorkerPool（见 [api/core/workflow/graph_engine/worker_management/worker_pool.py:1](../../api/core/workflow/graph_engine/worker_management/worker_pool.py#L1)）
- 指令通道：RedisChannel / InMemory（见 [api/core/workflow/graph_engine/command_channels/redis_channel.py:1](../../api/core/workflow/graph_engine/command_channels/redis_channel.py#L1)，[api/core/workflow/graph_engine/command_channels/in_memory_channel.py:1](../../api/core/workflow/graph_engine/command_channels/in_memory_channel.py#L1)）
- 指令处理：CommandProcessor / Handlers（见 [api/core/workflow/graph_engine/command_processing/command_processor.py:1](../../api/core/workflow/graph_engine/command_processing/command_processor.py#L1)，[api/core/workflow/graph_engine/command_processing/command_handlers.py:1](../../api/core/workflow/graph_engine/command_processing/command_handlers.py#L1)）
- ReadyQueue 实现/工厂（见 [api/core/workflow/graph_engine/ready_queue/in_memory.py:1](../../api/core/workflow/graph_engine/ready_queue/in_memory.py#L1)，[api/core/workflow/graph_engine/ready_queue/factory.py:1](../../api/core/workflow/graph_engine/ready_queue/factory.py#L1)）
- 响应接驳：ResponseCoordinator（见 [api/core/workflow/graph_engine/response_coordinator/coordinator.py:1](../../api/core/workflow/graph_engine/response_coordinator/coordinator.py#L1)）
- 账本与大钟：GraphRuntimeState / GraphExecution（见 [api/core/workflow/runtime/graph_runtime_state.py:1](../../api/core/workflow/runtime/graph_runtime_state.py#L1)，[api/core/workflow/graph_engine/domain/graph_execution.py:1](../../api/core/workflow/graph_engine/domain/graph_execution.py#L1)）

## 用法建议

- 读 03 篇看“图纸与运行态”，再回到本篇花名册定位子系统；
- 读 04/05/06 时，把“岗位关系连线图”打开对照每一步事件与状态变更；
- 建议在 IDE 同时打开以上“快速索引”的文件，配合断点或注释跳读。

