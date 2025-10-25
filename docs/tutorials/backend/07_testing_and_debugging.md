# 07 测试策略与调试路径

## 学习成果
- 熟悉核心工作流模块的单元测试、夹具组织方式
- 能够使用测试案例快速定位业务逻辑、复现问题
- 掌握常见调试技巧：日志层、事件监听、断点设置

## 引导问题
1. 工作流相关测试主要分布在哪些目录？夹具如何复用？
2. 单元测试如何模拟变量池、图引擎运行？有哪些 Mock？
3. 日志、事件能提供哪些调试线索？如何开启更详细的输出来定位问题？

## 必读源码
- `api/tests/unit_tests/core/workflow/` 全部子目录
- `api/tests/unit_tests/core/workflow/graph_engine/`、`nodes/`、`entities/`
- `api/tests/conftest.py` 与工作流相关夹具
- `dev/pytest/pytest_unit_tests.sh`
- `api/core/workflow/graph_engine/layer/debug_logging_layer.py`（或同类）
- `api/core/workflow/graph_events/listeners/`（如有）

## Walkthrough
1. **测试目录导览**  
   - 归纳 `tests/unit_tests/core/workflow/` 子目录（graph、engine、nodes、utils 等），记录每个目录关注点。  
   - 总结常见 Fixture（如 `workflow_builder`, `variable_pool`）的定义位置与用途。
2. **构造与断言**  
   - 选择一个 graph_engine 测试，分析 Arrange-Act-Assert 三步如何组织，提炼可复用技巧。  
   - 注意对事件、状态、变量池的断言方式，为调试提供参考。
3. **命令与脚本**  
   - 学习 `dev/pytest/pytest_unit_tests.sh` 的执行逻辑，了解调试工作流模块时的推荐命令。  
   - 结合 `make lint`、`make type-check` 形成常规检查流程。
4. **日志与层辅助**  
   - 阅读 Debug Logging Layer 或其他辅助层，记录如何在本地启用详细日志。  
   - 探索事件监听器如何输出或收集诊断信息。
5. **实战调试建议**  
   - 总结断点位置（如节点 `_run`、变量池写入、事件广播）与常见异常排查步骤。

## 动手任务
- 运行选定的单元测试（在本地或思想实验），对照源码标注关键断言。  
- 尝试启用 DebugLoggingLayer，设计一份日志输出示例（无需真实运行）。

## 思考题
- 目前测试覆盖面是否足够？哪些模块缺乏自动化验证？  
- 如何构造端到端测试或集成测试来覆盖跨服务协作的场景？

## 延伸阅读
- `CONTRIBUTING.md` 中的测试指南  
- `docs/zh-CN/README.md` 对工作流功能的描述  
- 相关 GitHub Issues/PR，了解真实问题的调试过程

