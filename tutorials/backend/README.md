# Dify Backend Deep Dive Tutorials

针对已经具备 Python、Flask 与领域驱动设计基础的开发者，这套教程聚焦于 `api/` 目录的源码导读，帮助你懂得如何追踪一次请求从服务层一路进入工作流图引擎并落地在节点执行上。课程不会重复环境搭建步骤，而是专注于结构、调用链与关键实现。

## 受众与目标
- 希望快速熟悉 Dify 后端源码的新同事或贡献者
- 想理解图引擎、节点体系、事件系统等核心模块的资深开发者
- 目标：完成系列后能独立定位工作流相关代码、读懂关键函数并掌握调试策略

## 篇章规划
0. **夜班花名册与地图**：一眼认全子系统与协作关系（见 `00_cast_and_map.md`）
1. **架构总览**：从 `app_factory.py` 切入，理解扩展加载、服务层与核心域的依赖关系
2. **工作流入口到调度**：跟踪 `workflow_service.py`、`workflow_run_service.py` 如何构建并启动一次运行
3. **Graph 模型与运行态**：拆解 `core/workflow/graph/` 模板、边条件与变量池协议
4. **Graph Engine·其一**：执行循环与就绪判定（见 `04_engine_run_and_state.md`）
5. **Graph Engine·其二**：命令通道、暂停与恢复（见 `05_commands_pause_resume.md`）
6. **Graph Engine·其三**：并行扩缩容、层与事件、错误策略（见 `06_workers_layers_errors.md`）
7. **节点实现与事件**：对比常见节点的 `_run()` 流程及 `node_events/`、`graph_events/` 的协同（见 `07_nodes_and_events.md`）
8. **业务协作与扩展点**：回到 `services/`、`repositories/`，总结持久化、插件与扩展策略（见 `08_services_and_extensions.md`）
9. **测试与调试**：整理 `tests/unit_tests/core/workflow/` 的夹具、常见断点与排障步骤（见 `09_testing_and_debugging.md`）

> 随着学习深入，篇章可继续扩展，例如 RAG 集成、插件机制或跨上下文协作等主题。

## 阅读建议
- 搭配源码：每篇都会标注具体文件路径与关键行号，建议在 IDE 中同步阅读
- 做图与笔记：用序列图或调用链梳理理解，记录遇到的疑问
- 先读测试再读实现：单元测试常包含简化场景，能帮助快速建立对模块职责的预期

## 链接跳转约定
- 在 Codex CLI/本地编辑器中：直接使用反引号包裹的文件引用格式 `path:line`（如 `api/core/workflow/graph_engine/graph_engine.py:220`），通常可直接点击跳转。
- 在 GitHub 等 Markdown 渲染环境中：使用相对链接 + 行号锚点，例如：
  - `[api/services/app_generate_service.py:22](../../api/services/app_generate_service.py#L22)`
  - `[api/core/workflow/graph_engine/graph_engine.py:220](../../api/core/workflow/graph_engine/graph_engine.py#L220)`
  - 本教程逐步将关键引用补充为上述两种兼容方案中的一种，以便不同阅读器下都能点击跳转。

## 状态
- `00 夜班花名册与地图`：已就绪（见 `00_cast_and_map.md`）
- `01 架构总览`：草案已就绪（见 `01_architecture_overview.md`）
- `02 工作流入口到调度`：提纲完成（见 `02_workflow_entry_to_dispatch.md`）
- `03 Graph 模型与运行态`：详细完成（见 `03_graph_model_and_runtime.md`）
- `04/05/06 Graph Engine 调度机制`：详细完成（见对应文件）
- `07 节点实现与事件`：提纲完成（见 `07_nodes_and_events.md`）
- `08 业务协作与扩展机制`：提纲完成（见 `08_services_and_extensions.md`）
- `09 测试与调试`：提纲完成（见 `09_testing_and_debugging.md`）
- 后续主题（RAG、插件等）：待进一步调研，欢迎提出学习需求
