# 07 节点实现与事件联动

## 学习成果
- 熟悉节点基类的 `_run()` 模式、输入解析、输出写入流程
- 对比 LLM、HTTP、Loop 等典型节点的实现细节
- 解释 `node_events` 与 `graph_events` 在节点生命周期中的作用

## 引导问题
1. `BaseNode` 提供了哪些通用能力？子类需要覆盖哪些方法？
2. 节点如何解析输入变量、读取变量池并输出结果？
3. 事件是如何从节点执行传播到引擎、再到上层服务或监听器的？

## 必读源码
- [api/core/workflow/nodes/base/node.py:1](../../api/core/workflow/nodes/base/node.py#L1)
- [api/core/workflow/nodes/node_mapping.py:1](../../api/core/workflow/nodes/node_mapping.py#L1)
- 典型节点：
  - [api/core/workflow/nodes/llm/node.py:1](../../api/core/workflow/nodes/llm/node.py#L1)
  - [api/core/workflow/nodes/http_request/node.py:1](../../api/core/workflow/nodes/http_request/node.py#L1)
  - [api/core/workflow/nodes/loop/loop_node.py:1](../../api/core/workflow/nodes/loop/loop_node.py#L1)
- `api/core/workflow/nodes/_utils`（若存在的工具函数）
- [api/core/workflow/node_events/__init__.py:1](../../api/core/workflow/node_events/__init__.py#L1)
- [api/core/workflow/graph_events/__init__.py:1](../../api/core/workflow/graph_events/__init__.py#L1)

## Walkthrough
1. **节点基类**  
   - 阅读 `BaseNode` 的初始化、`run()`、`_run()`、输入输出处理流程。  
   - 注意异常处理、metadata、变量映射等逻辑。
2. **节点注册与版本管理**  
   - 查看 `node_mapping.py` 如何维护 `NODE_TYPE_CLASSES_MAPPING` 与版本策略。  
   - 理解引擎如何根据节点类型实例化具体类。
3. **典型节点对比**  
   - LLM 节点：关注 prompt 构造、模型选择、输出结构。  
   - HTTP 节点：观察请求构造、错误处理、重试机制。  
   - Loop/Iteration 节点：记录控制流处理、迭代变量管理。
4. **事件传播链**  
   - 研究节点执行期间触发的 `NodeRunStartedEvent`、`NodeRunSucceededEvent` 等。  
   - 追踪 `GraphNodeEventBase` 如何在引擎和服务层间流动。
5. **调试与扩展**  
   - 指出添加新节点时需要实现的接口、需要补充的事件与测试。

## 动手任务
- 选一个节点，列出其 `_run()` 的输入输出，并画出变量依赖图。  
- 尝试在笔记中模拟编写一个伪节点类，确保覆盖基类要求的接口。

## 思考题
- 节点事件与图事件是否存在重复信息？能否统一？  
- 如果要新增“长时间运行”的节点，需要留意哪些超时或心跳逻辑？

## 延伸阅读
- [api/services/tools](../../api/services/tools) 或 [api/services/agent_service.py:1](../../api/services/agent_service.py#L1) 中使用节点的场景
- [api/tests/unit_tests/core/workflow/nodes](../../api/tests/unit_tests/core/workflow/nodes) 的测试策略
- `api/core/workflow/node_events/listeners/`（如有）
