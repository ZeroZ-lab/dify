# 08 业务协作与扩展机制

## 学习成果
- 说明服务层、仓储层如何与核心工作流域协同管理运行记录与配置
- 理解插件、工具、扩展点的装配方式，掌握新增能力的入口
- 总结工作流在多租户、权限、配置场景下的关键实现

## 引导问题
1. `DifyAPIRepositoryFactory` 如何返回具体仓储？与核心仓储之间的关系是什么？
2. 插件/工具调用在哪个层处理？如何与节点或服务集成？
3. 多租户或 Workspace 信息怎样在服务层传递到核心域？

## 必读源码
- [api/repositories/factory.py:1](../../api/repositories/factory.py#L1)
- [api/core/repositories/__init__.py](../../api/core/repositories/__init__.py) 与工作流相关仓储实现
- [api/services/workflow_app_service.py:1](../../api/services/workflow_app_service.py#L1)、[api/services/workspace_service.py:1](../../api/services/workspace_service.py#L1)
- [api/services/plugin](../../api/services/plugin)、[api/services/tools](../../api/services/tools)、[api/services/agent_service.py:1](../../api/services/agent_service.py#L1)
- [api/core/workflow/system_variable.py:1](../../api/core/workflow/system_variable.py#L1)
- `extensions/ext_*` 中与工作流相关的扩展（如存储、身份等）

## Walkthrough
1. **仓储工厂与会话管理**  
   - 追踪 `sessionmaker` 如何被注入仓储，理解事务边界与 commit 策略。  
   - 列出与工作流节点执行记录、运行日志相关的仓储实现。
2. **服务层与核心域交互**  
   - 观察 `WorkflowService` 如何在核心域返回结果后更新数据库、发送事件。  
   - 查找涉及变量同步、配置读取的服务函数。
3. **插件与工具扩展**  
   - 阅读 `services/plugin` 目录，了解凭证管理、插件注册流程。  
   - 分析工具（如 HTTP、Agent 扩展）如何在服务层初始化并在节点中调用。
4. **多租户与权限**  
   - 研究 `system_variable.py`、`context` 管理，确认 tenant、user 等信息的传播路径。  
   - 查阅相关验证逻辑确保请求在正确租户下执行。
5. **横切关注点**  
   - 探索日志、监控、审计相关的扩展，明确它们如何与工作流运行绑定。

## 动手任务
- 列出工作流运行涉及的主要仓储类，标注其负责的数据表和关键方法。  
- 选择一个插件或工具，整理其从配置、注入到使用的完整流程。

## 思考题
- 如果要接入新的外部知识库，哪些服务与核心模块需要扩展？  
- 在多租户场景下，哪些信息必须在工作流运行时隔离？怎样验证？

## 延伸阅读
- [api/core/workflow/variable_loader.py](../../api/core/workflow/variable_loader.py)
- [api/services/dataset_service.py](../../api/services/dataset_service.py) 中与 workflow graph 关联的代码
- [api/extensions/ext_app_metrics.py](../../api/extensions/ext_app_metrics.py)、[api/extensions/ext_request_logging.py](../../api/extensions/ext_request_logging.py)
