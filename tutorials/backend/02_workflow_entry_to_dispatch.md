# 02 工作流入口到调度启动

傍晚的参观继续深入。离开接待大厅，向导给每个人发了副耳塞——据说等会儿“Workflow 调度 RAP”会震得地板跟着点头。我们穿过挂满流程图的走廊，来到第二栋厂房：这里是工作流生产线调度中心，控制台上贴着“慎按红色按钮，除非你真想停止宇宙”。

所有应用请求会在这儿聚合、校验、分发，再搭乘传送轨道驶向核心车间。扶梯上升时，隔着玻璃就能看到 `WorkflowEntry` 站在中央挥手，一旁的图引擎伴奏着“咔嗒咔嗒”的节点节拍器。我们把见闻记在游记里：从入口调度到命令广播、再到存档归档的全过程，一路既科技又戏剧。

先用一幅字符画概览调度中心的流程：
```
HTTP Request
    |
    v
controllers (service_api/console/web)
    |
    v
AppGenerateService.generate()
    |
    v
WorkflowAppGenerator.generate()
    |
    v
WorkflowAppRunner.run()
    |
    v
WorkflowEntry.run() ──────→ GraphEngine (事件/节点执行)
    |                           |
    |                           └─── emits events ─→ WorkflowPersistenceLayer
    |                                                   |
    |                                                   ├─ sync write → repositories (node exec)
    |                                                   └─ enqueue → Celery save_workflow_execution_task
    |
    └─ CommandChannel (Redis/InMemory) ←─ GraphEngineManager.send_*()
```

## 必读源码
- [api/services/workflow_service.py:1](../../api/services/workflow_service.py#L1)
- [api/services/workflow_run_service.py:1](../../api/services/workflow_run_service.py#L1)
- [api/services/workflow_app_service.py:1](../../api/services/workflow_app_service.py#L1)
- [api/services/workflow/workflow_converter.py:1](../../api/services/workflow/workflow_converter.py#L1)
- [api/core/workflow/workflow_entry.py:1](../../api/core/workflow/workflow_entry.py#L1)
- [api/core/workflow/enums.py:1](../../api/core/workflow/enums.py#L1)、[api/core/workflow/errors.py:1](../../api/core/workflow/errors.py#L1)
- [api/models/workflow.py:1](../../api/models/workflow.py#L1)

## Walkthrough
### 1. 服务层角色分工与调用链
工作流运行入口通常由 HTTP 控制器调用 `AppGenerateService.generate()`（[api/services/app_generate_service.py:22](../../api/services/app_generate_service.py#L22)），后者根据 app 模式委派给相应的 `AppGenerator`。工作流模式对应 `WorkflowAppGenerator.generate()`（[api/core/app/apps/workflow/app_generator.py:44](../../api/core/app/apps/workflow/app_generator.py#L44)）。

调用关系可以用下面的字符画表示：
```
controllers.* → AppGenerateService.generate()
      ↓
WorkflowAppGenerator.generate()
      ↓
WorkflowAppRunner.run()
      ↓
WorkflowEntry.run() → GraphEngine
```

关键片段（[api/services/app_generate_service.py:104](../../api/services/app_generate_service.py#L104) 起）：
```python
elif app_model.mode == AppMode.WORKFLOW:
    workflow = cls._get_workflow(app_model, invoke_from, workflow_id)
    return rate_limit.generate(
        WorkflowAppGenerator.convert_to_event_stream(
            WorkflowAppGenerator().generate(
                app_model=app_model,
                workflow=workflow,
                user=user,
                args=args,
                invoke_from=invoke_from,
                streaming=streaming,
                call_depth=0,
            ),
        ),
        request_id,
    )
```

`WorkflowService` 负责草稿/发布版本的读取、节点单步调试、特性校验等；`WorkflowRunService` 则提供运行记录查询、分页等只读接口（[api/services/workflow_run_service.py:65](../../api/services/workflow_run_service.py#L65)）。两者都通过 `DifyAPIRepositoryFactory` 注入仓储，保持与核心仓储实现解耦。

门禁与保安队（加戏）：
- 控制器先核验门禁（Token/权限），再把客人转给 `AppGenerateService`；
- 大堂保安是两个限流器：
  - 系统级“当天限流”在免费套餐时生效（`AppGenerateService.system_rate_limiter`，[app_generate_service.py:22–54](../../api/services/app_generate_service.py#L22-L54)）。
  - 应用级“并发限流”由 `RateLimit(app_id, max_active_request)` 把守（`_get_max_active_requests` 读取全局与应用配置，[app_generate_service.py:130–149](../../api/services/app_generate_service.py#L130-L149)）。
  - 如果撞上大门口 RAP：“Rate limit exceeded...”——要么升级，要么等夜班更替。

### 2. 工作流模型的加载与转换
工作流 DSL 存在于 `models.workflow.Workflow`（`graph`, `features` 字段）。当应用首次转换为工作流模式时，`WorkflowConverter.convert_app_model_config_to_workflow()`（[api/services/workflow/workflow_converter.py:90](../../api/services/workflow/workflow_converter.py#L90)）会把变量、模型配置、提示词等结构化为图节点，并持久化为草稿版本：
```python
graph: dict[str, Any] = {"nodes": [], "edges": []}
start_node = self._convert_to_start_node(variables=app_config.variables)
graph["nodes"].append(start_node)
# ...append http/knowledge/llm/end 节点
workflow = Workflow(
    tenant_id=app_model.tenant_id,
    app_id=app_model.id,
    type=WorkflowType.from_app_mode(new_app_mode).value,
    version=Workflow.VERSION_DRAFT,
    graph=json.dumps(graph),
    features=json.dumps(features),
    created_by=account_id,
)
```

运行时，`WorkflowAppGenerator` 会调用 `WorkflowAppConfigManager.get_app_config()` 解析最新图数据、变量与特性配置，再将用户输入与文件等信息整合为 `WorkflowAppGenerateEntity`。

文件巡检（小剧场）：
- 有人背着“文件”进入，前台会给它们换上标准制服：
  - `FileUploadConfigManager.convert()` 读图配置（`app_generator.py:103`），
  - `file_factory.build_from_mappings()` 把 JSON 映射成 File 对象（`app_generator.py:104-109`）。
  - 文件随后被塞进系统变量，便于后续节点搬运（见下节 `SystemVariable(files=...)`）。

顺手一提：如果是 CHAT/AGENT/ADVANCED_CHAT 等模式，`AppGenerateService` 会把生成器转换成“事件流”（`convert_to_event_stream`），让前端能边看边收；WORKFLOW 模式也同理（[app_generate_service.py:108–120](../../api/services/app_generate_service.py#L108-L120)）。

### 3. 运行条目构建：VariablePool 与 WorkflowEntry
`WorkflowAppRunner.run()`（[api/core/app/apps/workflow/app_runner.py:52](../../api/core/app/apps/workflow/app_runner.py#L52)）负责准备变量池、运行时状态、命令通道，并实例化 `WorkflowEntry`：
```python
# 变量仓：把系统变量/用户输入/环境变量上架，节点后续从这里取货
variable_pool = VariablePool(
    # 系统变量：把文件/用户/应用/执行ID装进“背包”
    system_variables=SystemVariable(
        files=self.application_generate_entity.files,  # 统一封装的 File 对象列表
        user_id=self._sys_user_id,                    # 系统用户/终端用户 ID
        app_id=app_config.app_id,                     # 应用 ID
        workflow_id=app_config.workflow_id,           # 工作流 ID
        workflow_execution_id=self.application_generate_entity.workflow_execution_id,  # 本次运行 ID
    ),
    user_inputs=inputs,                                # Start/前台传入的 inputs
    environment_variables=self._workflow.environment_variables,  # 发布配置/草稿侧变量
    conversation_variables=[],                         # 调试/草稿阶段通常为空，由 DraftVarLoader 补齐
)

# 运行态：记录开始时间、累计 tokens/步骤、输出等（需要时可序列化为快照）
graph_runtime_state = GraphRuntimeState(variable_pool=variable_pool, start_at=time.perf_counter())

# 立体化蓝图：把 DSL 图纸 + 运行态组装成 Graph，准备启动
graph = self._init_graph(
    graph_config=self._workflow.graph_dict,         # 原始 DSL 图
    graph_runtime_state=graph_runtime_state,        # 共享运行态
    workflow_id=self._workflow.id,                  # 图执行上下文
    tenant_id=self._workflow.tenant_id,
    user_id=self.application_generate_entity.user_id,
)

# 命令通道：分配给本次运行的 Redis key（停/暂停都走这里）
command_channel = RedisChannel(redis_client, f"workflow:{task_id}:commands")

# 工单：WorkflowEntry 绑定 graph/runtime/通道，稍后交给 GraphEngine.run()
workflow_entry = WorkflowEntry(
    tenant_id=self._workflow.tenant_id,
    app_id=self._workflow.app_id,
    workflow_id=self._workflow.id,
    graph=graph,
    graph_config=self._workflow.graph_dict,        # 保留原始图配置用于事件/持久化
    user_id=self.application_generate_entity.user_id,
    user_from=UserFrom.END_USER,                   # 也可能是 ACCOUNT（控制台调试）
    invoke_from=self.application_generate_entity.invoke_from,
    call_depth=self.application_generate_entity.call_depth,  # 嵌套调用深度
    variable_pool=variable_pool,
    graph_runtime_state=graph_runtime_state,
    command_channel=command_channel,
)
```

`WorkflowEntry` 本身在构造函数中初始化 `GraphEngine` 并追加默认 Layer（DebugLoggingLayer、ExecutionLimitsLayer），见 [api/core/workflow/workflow_entry.py:33](../../api/core/workflow/workflow_entry.py#L33)。单步调试场景会走 `WorkflowEntry.single_step_run()`，它会临时创建节点实例并返回事件生成器，供 `WorkflowService.run_draft_workflow_node()` 使用。

搬运队与追踪员（加戏）：
- 变量搬运队：`VariablePool` 像高架仓库，把系统变量（含文件）、用户输入、环境变量整齐上架；后续节点要啥自己取（详见第 03 篇）。
- 追踪员：`TraceQueueManager` 在一旁记账（[api/core/app/apps/workflow/app_generator.py:117–121](../../api/core/app/apps/workflow/app_generator.py#L117-L121)），把一次运行的“旅程”打包归档，便于夜班过后复盘。

### 4. 调度、命令通道与事件
`WorkflowEntry.run()` 返回的生成器会驱动图引擎执行节点。为支持实时控制，`WorkflowAppRunner` 将 Redis 命令通道与 `GraphEngine` 关联；停止指令由 `GraphEngineManager.send_stop_command()` 发送，控制器直接调用它（[api/controllers/service_api/app/workflow.py:274](../../api/controllers/service_api/app/workflow.py#L274)）。

执行过程中，`WorkflowPersistenceLayer`（由 `WorkflowAppRunner` 注入）监听 `GraphEngineEvent`，把节点执行、整体运行等事件写入仓储：
```python
persistence_layer = WorkflowPersistenceLayer(
    application_generate_entity=self.application_generate_entity,
    workflow_info=PersistenceWorkflowInfo(...),
    workflow_execution_repository=self._workflow_execution_repository,
    workflow_node_execution_repository=self._workflow_node_execution_repository,
    trace_manager=self.application_generate_entity.trace_manager,
)
workflow_entry.graph_engine.layer(persistence_layer)
```

字符画展示事件与命令流向：
```
WorkflowEntry.run()
    ├─ GraphEngine emits events ─→ WorkflowPersistenceLayer → repositories
    └─ CommandChannel (Redis/InMemory) ←─ GraphEngineManager.send_*()
```

播报台（小剧场）：
- 事件从 Worker 传来，经 `EventHandler` 处理后送达 `EventManager`，一部分变成“播报内容”（流式 chunk），一部分变成“账本记录”（持久化）；
- 前端若订阅了流式事件，就像看“跑马灯”一样能看到 LLM 的逐字输出；
- 红色按钮（停止）和黄色按钮（暂停）都走命令通道，若不慎按下，播报台会立刻提醒并记录缘由（详见第 05 篇）。

### 5. 运行记录持久化与异步写入
`WorkflowExecutionRepository` 会将运行状态序列化为 `WorkflowExecution` 实体，并通过 Celery 任务 `save_workflow_execution_task`（[api/tasks/workflow_execution_tasks.py:24](../../api/tasks/workflow_execution_tasks.py#L24)）异步写入 `WorkflowRun` 表。任务会判断 run 是否存在，从而支持重试与幂等：
```python
execution = WorkflowExecution.model_validate(execution_data)
existing_run = session.scalar(select(WorkflowRun).where(WorkflowRun.id == execution.id_))
if existing_run:
    _update_workflow_run_from_execution(existing_run, execution)
else:
    workflow_run = _create_workflow_run_from_execution(...)
    session.add(workflow_run)
session.commit()
```

节点级别的执行记录由 `WorkflowNodeExecutionRepository` 保存，可在 `WorkflowRunService.get_workflow_run_node_executions()`（[api/services/workflow_run_service.py:125](../../api/services/workflow_run_service.py#L125)）中查询，服务层会注入租户上下文并加载关联文件输出。

归档叉车（加戏）：
- PersistenceLayer 相当于“当班记录员”，抓取 Graph/Node 事件做两件事：
  - 更新运行总账（WorkflowExecution）：状态、异常数、总步数、总 tokens、耗时、输出快照；
  - 更新节点流水（WorkflowNodeExecution）：每步的输入/过程数据/输出/错误与时间戳。
- 大件搬运交给 Celery（`save_workflow_execution_task`），夜深人静把“账本”批量落库，失败还能重试。

### 6. 错误处理与策略
当节点执行抛出 `WorkflowNodeRunFailedError` 时，`WorkflowService._handle_single_step_result()`（[api/services/workflow_service.py:680](../../api/services/workflow_service.py#L680)）或 `WorkflowAppRunner` 会捕获并应用错误策略（`ErrorStrategy.DEFAULT_VALUE` 等），保证节点 Execution 记录能准确标注状态与错误原因。全局异常会触发 `WorkflowEntry.run()` 中的 `GraphRunFailedEvent`（见 [api/core/workflow/graph_engine/graph_engine.py:286–294](../../api/core/workflow/graph_engine/graph_engine.py#L286-L294)），由持久化层写入运行失败信息。

夜间应急预案（更详细）
- 重试策略：若节点配置了 `retry`，并且未超过 `retry_config.max_retries`，引擎会在 `retry_interval_seconds` 后发起 `NodeRunRetryEvent` 继续尝试（[api/core/workflow/graph_engine/error_handler.py:67](../../api/core/workflow/graph_engine/error_handler.py#L67)，重试逻辑见 [104–137](../../api/core/workflow/graph_engine/error_handler.py#L104-L137)）。
- 失败分支（FAIL_BRANCH）：把失败改写为 `NodeRunExceptionEvent`，并设置 `edge_source_handle = 'fail-branch'`，由 EdgeProcessor 选择对应的分支推进（[error_handler.py:139–173](../../api/core/workflow/graph_engine/error_handler.py#L139-L173)）。
- 默认值（DEFAULT_VALUE）：将 `node.default_value_dict` 与错误信息合并为 outputs，继续向前（[error_handler.py:175–201](../../api/core/workflow/graph_engine/error_handler.py#L175-L201)）。
- 终止：当无策略/重试穷尽且未配置异常分支时，引擎将终止或抛错，Dispatcher 进入收尾流程。

ASCII 决策树
```
Node 失败?
  ├─ 可重试? ──► 等待 retry_interval → Retry → 成功? → 继续 : 进入下一分支
  ├─ FAIL_BRANCH? ──► NodeRunExceptionEvent(edge='fail-branch') → 继续
  ├─ DEFAULT_VALUE? ──► NodeRunExceptionEvent(outputs=default+error) → 继续
  └─ 否 ──► 终止/抛错

图收尾：
  exceptions_count > 0 → GraphRunPartialSucceededEvent（[api/core/workflow/graph_engine/graph_engine.py:270–284](../../api/core/workflow/graph_engine/graph_engine.py#L270-L284)）
  else → GraphRunSucceededEvent（[api/core/workflow/graph_engine/graph_engine.py:279–284](../../api/core/workflow/graph_engine/graph_engine.py#L279-L284)）
```

附加 ASCII：变量与文件的搬运
```
用户输入/文件 JSON
    │  (FileUploadConfigManager + file_factory)
    v
SystemVariable.files  ──► VariablePool['sys','files']
    │                                    │
    └─────────► 节点取用（selector） ◄────┘
```

## 动手任务
- 画出“前端发起运行 → 服务层 → 核心域”时序图，标注关键方法与数据结构。
- 挑选一个工作流节点，查找其最新一次运行记录（依赖数据库），确认写入字段与代码位置一致。

## 思考题
- 如果需要添加运行前置校验（例如限流），应该挂在哪个服务更合理？为什么？
- 当前的运行记录写入是否具备幂等性？遇到重试会怎样？

## 延伸阅读
- [api/services/workflow/workflow_draft_variable_service.py](../../api/services/workflow/workflow_draft_variable_service.py)
- `api/events/` 中与工作流相关的事件触发
- `api/core/workflow/callbacks/` 中的回调定义
