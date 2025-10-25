# 04C 夜班调度·其三：并行扩缩容、层与事件、错误策略

工友们戴上耳罩进入机修间。这里讨论“要派几个人”“什么时候收队”“错误来了咋办”。

## WorkerPool：开几班、何时加人减人

参数（来自 dify_config，WorkerPool 支持覆盖）：
- GRAPH_ENGINE_MIN_WORKERS / MAX_WORKERS
- GRAPH_ENGINE_SCALE_UP_THRESHOLD（队列深度超阈值 → 扩容）
- GRAPH_ENGINE_SCALE_DOWN_IDLE_TIME（空闲超过 N 秒 → 缩容）

初始人数：
```python
# api/core/workflow/graph_engine/worker_management/worker_pool.py（节选）
node_count = len(graph.nodes)
if node_count < 10: initial = min_workers
elif node_count < 50: initial = min(min_workers + 1, max_workers)
else: initial = min(min_workers + 2, max_workers)
```

扩容/缩容：
```python
queue_depth = ready_queue.qsize()
idle_count = sum(worker.is_idle for worker in workers)
active_count = total - idle_count

# 扩：队列深且未到上限
if queue_depth > scale_up_threshold and total < max_workers: create_worker()

# 缩：达到最低需求且有足够空闲（只移一个避免抖动）
if total > min_workers and idle_count and has_excess_capacity(...): remove_idle_worker()
```

ASCII：
```
队列深 → +1 工人；
长时间空闲 + 超配 → -1 工人；
避免抖动：一次只加/减一个；
```

## 事件顺序与流式输出

典型顺序：
```
NodeRunStarted → （流式）NodeRunStreamChunk×N → NodeRunSucceeded/Failed
```

RESPONSE 节点开场先登记，否则流式事件无处安放：`response_coordinator.register(node.id)`（graph_engine.py:326）。

边事件：当一条边被标记为 TAKEN，ResponseCoordinator 也可能产出边级流式事件（edge_processor.py:137）。

## Layer：三钩子与常见用途

```python
class GraphEngineLayer:
    def initialize(read_only_state, command_channel): pass
    def on_graph_start(self): pass
    def on_event(self, event): pass
    def on_graph_end(self, error): pass
```

常见用途：
- DebugLoggingLayer：把输入/输出/中间数据打给日志（调试利器）。
- ExecutionLimitsLayer：限制步数/时间，防止深夜“无限循环”。
- PersistenceLayer：把 WorkflowExecution/NodeExecution 落库，方便回放与观测。

## 错误策略矩阵：失败 ≠ 崩溃

当节点失败：
1) ErrorHandler 决策：是否重试；是否走异常分支（NodeRunExceptionEvent）；是否直接失败。
2) 图级结果：
   - 有异常但整体跑完 → GraphRunPartialSucceededEvent（exceptions_count > 0）。
   - 真正失败 → GraphRunFailedEvent（引擎抛错）。

ASCII 决策树：
```
Node 失败?
  ├─ 可重试 → Retry → 成功? → 继续 : 失败分支
  ├─ 有异常分支/默认值 → NodeRunExceptionEvent → 标记异常但前进
  └─ 否 → 记录失败 → 引擎 fail/abort

图收尾：
  exceptions_count > 0 → PartialSucceeded
  else → Succeeded
```

## 观察与背压（附加建议）

- 观测：结合 PersistenceLayer 的统计字段（total_steps/total_tokens/exceptions_count/elapsed_time），以及 ext_otel，把关键指标挂上监控。
- 背压：
  - 适当调大 SCALE_UP_THRESHOLD，避免瞬时抖动就扩容；
  - 若下游消费慢，限制同时活跃工人数量，或在 Layer 中加速率阈值。

下一章（05 节点的一生）：深入 `_run()`，我们去看 LLM、HTTP、Loop 等节点如何进出变量仓、如何发事件、如何触发错误策略。

