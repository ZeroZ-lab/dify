# 06 夜班调度·其三：并行扩缩容、层与事件、错误策略

工友们戴上耳罩进入机修间。这里讨论“要派几个人”“什么时候收队”“错误来了咋办”。

## WorkerPool：开几班、何时加人减人

参数（来自 dify_config，WorkerPool 支持覆盖）：
- GRAPH_ENGINE_MIN_WORKERS / MAX_WORKERS
- GRAPH_ENGINE_SCALE_UP_THRESHOLD（队列深度超阈值 → 扩容）
- GRAPH_ENGINE_SCALE_DOWN_IDLE_TIME（空闲超过 N 秒 → 缩容）

初始人数（见 [api/core/workflow/graph_engine/worker_management/worker_pool.py:96–105](../../api/core/workflow/graph_engine/worker_management/worker_pool.py#L96-L105)）：
```python
# api/core/workflow/graph_engine/worker_management/worker_pool.py（节选）
node_count = len(graph.nodes)
if node_count < 10: initial = min_workers
elif node_count < 50: initial = min(min_workers + 1, max_workers)
else: initial = min(min_workers + 2, max_workers)
```

扩容/缩容（见 [worker_pool.py:168–191](../../api/core/workflow/graph_engine/worker_management/worker_pool.py#L168-L191)、[worker_pool.py:193–220](../../api/core/workflow/graph_engine/worker_management/worker_pool.py#L193-L220)）：
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

RESPONSE 节点开场先登记，否则流式事件无处安放：`response_coordinator.register(node.id)`（见 [api/core/workflow/graph_engine/graph_engine.py:323–327](../../api/core/workflow/graph_engine/graph_engine.py#L323-L327)）。

边事件：当一条边被标记为 TAKEN，ResponseCoordinator 也可能产出边级流式事件（见 [api/core/workflow/graph_engine/graph_traversal/edge_processor.py:141–147](../../api/core/workflow/graph_engine/graph_traversal/edge_processor.py#L141-L147)）。

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

更多细节（来自 ErrorHandler）：
- 重试参数：节点若配置 `retry`，遵循 `retry_config.max_retries` 与 `retry_interval_seconds`；重试通过 `NodeRunRetryEvent` 发起（见 [api/core/workflow/graph_engine/error_handler.py:67](../../api/core/workflow/graph_engine/error_handler.py#L67)，以及重试实现 [104–137](../../api/core/workflow/graph_engine/error_handler.py#L104-L137)）。
- 异常分支：`FAIL_BRANCH` 会产出 `NodeRunExceptionEvent`，并把 `edge_source_handle` 设为 `fail-branch`，EdgeProcessor 将据此选边（见 [api/core/workflow/graph_engine/error_handler.py:139–173](../../api/core/workflow/graph_engine/error_handler.py#L139-L173)）。
- 默认值：`DEFAULT_VALUE` 策略会把 `node.default_value_dict` 与错误信息合并为 outputs，然后继续推进（见 [api/core/workflow/graph_engine/error_handler.py:175–201](../../api/core/workflow/graph_engine/error_handler.py#L175-L201)）。
- 终止：当无策略或重试穷尽且未配置异常分支时，引擎会把图置为失败或中止（由上层流程决定）。

## 观察与背压（附加建议）

- 观测：结合 PersistenceLayer 的统计字段（total_steps/total_tokens/exceptions_count/elapsed_time），以及 ext_otel，把关键指标挂上监控。
- 背压：
  - 适当调大 SCALE_UP_THRESHOLD，避免瞬时抖动就扩容；
  - 若下游消费慢，限制同时活跃工人数量，或在 Layer 中加速率阈值。

下一章（07 节点的一生）：深入 `_run()`，我们去看 LLM、HTTP、Loop 等节点如何进出变量仓、如何发事件、如何触发错误策略。

---

## 配置开关与默认值（调优清单）

来源：[api/configs/feature/__init__.py:568](../../api/configs/feature/__init__.py#L568)、[api/configs/feature/__init__.py:596](../../api/configs/feature/__init__.py#L596)

- 执行上限（ExecutionLimitsLayer 会用到）：
  - `WORKFLOW_MAX_EXECUTION_STEPS`（默认 500）：最多执行多少步，超限即 Abort。
  - `WORKFLOW_MAX_EXECUTION_TIME`（默认 1200s）：最多跑多久，超限即 Abort。
  - `WORKFLOW_CALL_MAX_DEPTH`（默认 5）：嵌套工作流调用的最大深度。

- Worker 池（并行度/弹性）：
  - `GRAPH_ENGINE_MIN_WORKERS`（默认 1）/`GRAPH_ENGINE_MAX_WORKERS`（默认 10）。
  - `GRAPH_ENGINE_SCALE_UP_THRESHOLD`（默认 3）：队列深度超过阈值触发扩容。
  - `GRAPH_ENGINE_SCALE_DOWN_IDLE_TIME`（默认 5.0s）：空闲超过此时间可缩容。

调优建议：
- 高吞吐：提高 `MAX_WORKERS`、适当降低 `SCALE_UP_THRESHOLD`；同时监控下游（数据库/外部 API）避免压爆。
- 慢模型/IO：适度提高 `MAX_EXECUTION_TIME`；为流式消费者预留足够工人，保证事件不堆积。
- 资源受限：降低 `MAX_WORKERS`、提高 `SCALE_UP_THRESHOLD`、缩短 `SCALE_DOWN_IDLE_TIME`，减少线程驻留。
