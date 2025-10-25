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
- `api/services/workflow_service.py:1`
- `api/services/workflow_run_service.py:1`
- `api/services/workflow_app_service.py:1`
- `api/services/workflow/workflow_converter.py:1`
- `api/core/workflow/workflow_entry.py:1`
- `api/core/workflow/enums.py:1`、`errors.py:1`
- `api/models/workflow.py:1`

## Walkthrough
### 1. 服务层角色分工与调用链
工作流运行入口通常由 HTTP 控制器调用 `AppGenerateService.generate()`（`api/services/app_generate_service.py:22`），后者根据 app 模式委派给相应的 `AppGenerator`。工作流模式对应 `WorkflowAppGenerator.generate()`（`api/core/app/apps/workflow/app_generator.py:44`）。

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

关键片段（`api/services/app_generate_service.py:84` 起）：
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

`WorkflowService` 负责草稿/发布版本的读取、节点单步调试、特性校验等；`WorkflowRunService` 则提供运行记录查询、分页等只读接口（`api/services/workflow_run_service.py:65`）。两者都通过 `DifyAPIRepositoryFactory` 注入仓储，保持与核心仓储实现解耦。

### 2. 工作流模型的加载与转换
工作流 DSL 存在于 `models.workflow.Workflow`（`graph`, `features` 字段）。当应用首次转换为工作流模式时，`WorkflowConverter.convert_app_model_config_to_workflow()`（`api/services/workflow/workflow_converter.py:90`）会把变量、模型配置、提示词等结构化为图节点，并持久化为草稿版本：
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

### 3. 运行条目构建：VariablePool 与 WorkflowEntry
`WorkflowAppRunner.run()`（`api/core/app/apps/workflow/app_runner.py:52`）负责准备变量池、运行时状态、命令通道，并实例化 `WorkflowEntry`：
```python
variable_pool = VariablePool(
    system_variables=SystemVariable(
        files=self.application_generate_entity.files,
        user_id=self._sys_user_id,
        app_id=app_config.app_id,
        workflow_id=app_config.workflow_id,
        workflow_execution_id=self.application_generate_entity.workflow_execution_id,
    ),
    user_inputs=inputs,
    environment_variables=self._workflow.environment_variables,
    conversation_variables=[],
)
graph_runtime_state = GraphRuntimeState(variable_pool=variable_pool, start_at=time.perf_counter())
graph = self._init_graph(
    graph_config=self._workflow.graph_dict,
    graph_runtime_state=graph_runtime_state,
    workflow_id=self._workflow.id,
    tenant_id=self._workflow.tenant_id,
    user_id=self.application_generate_entity.user_id,
)
command_channel = RedisChannel(redis_client, f"workflow:{task_id}:commands")
workflow_entry = WorkflowEntry(
    tenant_id=self._workflow.tenant_id,
    app_id=self._workflow.app_id,
    workflow_id=self._workflow.id,
    graph=graph,
    graph_config=self._workflow.graph_dict,
    user_id=self.application_generate_entity.user_id,
    user_from=UserFrom.END_USER,
    invoke_from=self.application_generate_entity.invoke_from,
    call_depth=self.application_generate_entity.call_depth,
    variable_pool=variable_pool,
    graph_runtime_state=graph_runtime_state,
    command_channel=command_channel,
)
```

`WorkflowEntry` 本身在构造函数中初始化 `GraphEngine` 并追加默认 Layer（DebugLoggingLayer、ExecutionLimitsLayer），见 `api/core/workflow/workflow_entry.py:33`。单步调试场景会走 `WorkflowEntry.single_step_run()`，它会临时创建节点实例并返回事件生成器，供 `WorkflowService.run_draft_workflow_node()` 使用。

### 4. 调度、命令通道与事件
`WorkflowEntry.run()` 返回的生成器会驱动图引擎执行节点。为支持实时控制，`WorkflowAppRunner` 将 Redis 命令通道与 `GraphEngine` 关联；停止指令由 `GraphEngineManager.send_stop_command()` 发送，控制器直接调用它（`api/controllers/service_api/app/workflow.py:274`）。

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

### 5. 运行记录持久化与异步写入
`WorkflowExecutionRepository` 会将运行状态序列化为 `WorkflowExecution` 实体，并通过 Celery 任务 `save_workflow_execution_task`（`api/tasks/workflow_execution_tasks.py:24`）异步写入 `WorkflowRun` 表。任务会判断 run 是否存在，从而支持重试与幂等：
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

节点级别的执行记录由 `WorkflowNodeExecutionRepository` 保存，可在 `WorkflowRunService.get_workflow_run_node_executions()`（`api/services/workflow_run_service.py:125`）中查询，服务层会注入租户上下文并加载关联文件输出。

### 6. 错误处理与策略
当节点执行抛出 `WorkflowNodeRunFailedError` 时，`WorkflowService._handle_single_step_result()`（`api/services/workflow_service.py:680`）或 `WorkflowAppRunner` 会捕获并应用错误策略（`ErrorStrategy.DEFAULT_VALUE` 等），保证节点 Execution 记录能准确标注状态与错误原因。全局异常会触发 `WorkflowEntry.run()` 中的 `GraphRunFailedEvent`，由持久化层写入运行失败信息。

## 动手任务
- 画出“前端发起运行 → 服务层 → 核心域”时序图，标注关键方法与数据结构。
- 挑选一个工作流节点，查找其最新一次运行记录（依赖数据库），确认写入字段与代码位置一致。

## 思考题
- 如果需要添加运行前置校验（例如限流），应该挂在哪个服务更合理？为什么？
- 当前的运行记录写入是否具备幂等性？遇到重试会怎样？

## 延伸阅读
- `api/services/workflow/workflow_draft_variable_service.py`
- `api/events/` 中与工作流相关的事件触发
- `api/core/workflow/callbacks/` 中的回调定义
