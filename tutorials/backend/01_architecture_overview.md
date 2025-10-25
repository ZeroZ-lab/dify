# 01 架构总览：从应用工厂到核心模块

夜幕刚降临，参观者踏入 Dify 的生产园区。前厅里，值班 AI 穿着闪闪发光的背心，在门禁台前核对访客名单，还顺手递上一杯“今日特调：JSON Latte”。打印机吐出临时工牌的同时，扬声器不忘提醒：“请勿喂食 GraphEngine，九点后它会偏爱异常”。不远处走廊灯光柔和，墙上贴满安全标语：“遇到循环节点请保持冷静”。

为了在这座园区里找到路线、听懂工人的术语，我们先沿着向导的指示，依次认识入口、扩展、服务、核心与仓储的布局。当后续同伴提起 `WorkflowService` 或 `GraphEngine`，你就能立刻指着楼层图说出它们的所在地和同事，还能顺便八卦一句：“那边的 NodeFactory 可精通一百八十种变形呢。”

参观路线概览：
```
Visitor Entrance (app_factory.py)
      ↓
Extension Hall (ext_*)
      ↓
Service Offices (services/)
      ↓
Core Workshop (core/workflow/)
      ↓
Storage & Records (repositories/, models/)
```

## 必读源码
- [api/app_factory.py:1](../../api/app_factory.py#L1)：Flask 应用工厂、扩展初始化
- `api/extensions/ext_*`：主要扩展的注册方式与可选策略
- [api/services/__init__.py:1](../../api/services/__init__.py#L1) 与 [api/services/workflow_service.py:1](../../api/services/workflow_service.py#L1)：服务层的入口、依赖注入
- [api/core/__init__.py:1](../../api/core/__init__.py#L1) 与 [api/core/workflow/README.md:1](../../api/core/workflow/README.md#L1)：核心域分层介绍
- [api/repositories/factory.py:1](../../api/repositories/factory.py#L1)：持久化层工厂的抽象
- `dev/import_linter/workflow_contracts.yml`（若存在）：查看 import-linter 的依赖约束

> 建议在阅读时同时打开项目结构树，标注各目录角色。

## Walkthrough
### 1. 入口大厅：应用工厂与扩展加载
向导推开大厅大门，只见 `create_flask_app_with_configs()` 坐在接待台前（位置 [api/app_factory.py:14](../../api/app_factory.py#L14)），熟练地把 `DifyConfig` 这份涵盖部署、特性、可观测性的“访客须知”拍成一本手册。办公室角落堆着 `.env`、远程配置中心的接入卡，旁边还摆着一台刻着 “search_file_upwards” 的自动售卡机，专门帮忙找 `pyproject.toml` 的影印件。

```python
# api/app_factory.py:14
def create_flask_app_with_configs() -> DifyApp:
    # 揉面团：先揉一个 Dify 专属的 Flask 面团，方便后面随意加馅
    dify_app = DifyApp(__name__)
    # 把 DifyConfig 的秘密酱汁（env、远程、pyproject）一次性倒进锅里
    dify_app.config.from_mapping(dify_config.model_dump())

    @dify_app.before_request
    def before_request():
        # 每次来访都敲下“换牌钟”，提醒厨房别用昨天的调料
        RecyclableContextVar.increment_thread_recycles()
```

同一函数在 [api/app_factory.py:23](../../api/app_factory.py#L23) 注册了 `before_request` 钩子，用 `RecyclableContextVar.increment_thread_recycles()` 保证线程复用时请求上下文不会串号。这直接依赖了 [api/contexts/wrapper.py:14](../../api/contexts/wrapper.py#L14) 的封装，稍后会继续解读。

正式的 `create_app()`（[api/app_factory.py:34](../../api/app_factory.py#L34)）像个拿着计时器的车间领班，一声令下，`initialize_extensions()` 排队进场。扩展军团的出场顺序全有讲究：前排的 `ext_logging`、`ext_warnings` 负责调音和广播；`ext_import_modules` 推门把事件监听员叫醒；中段的 `ext_database`、`ext_storage` 搞定原材料仓库；尾声的 `ext_blueprints` 则铺好通往各个展区的红毯。每名扩展上场前还要接受“是否启用”的问询（有些临时请假就不出场了），并在 `DEBUG` 模式下留下上台耗时的统计数据。

```python
# api/app_factory.py:44
extensions = [
    ext_timezone, ext_logging, ext_warnings, ext_import_modules,
    ext_orjson, ext_set_secretkey, ext_compress, ext_code_based_extension,
    ext_database, ext_app_metrics, ext_migrate, ext_redis,
    ext_storage, ext_celery, ext_login, ext_mail,
    ext_hosting_provider, ext_sentry, ext_proxy_fix,
    ext_blueprints, ext_commands, ext_otel, ext_request_logging,
]
for ext in extensions:
    # 某些夜班同事临时请假（禁用），我们就别点名了
    is_enabled = ext.is_enabled() if hasattr(ext, "is_enabled") else True
    if not is_enabled:
        continue
    # 让每位同事摸摸主控面板，自报家门、接好线路
    ext.init_app(app)
```

在走读时建议挑选几个关键扩展深入阅读：
- `ext_database.init_app()`（[api/extensions/ext_database.py:53](../../api/extensions/ext_database.py#L53)）初始化 SQLAlchemy 并在 gevent 场景下挂入连接 reset 钩子。
- `ext_blueprints.init_app()`（[api/extensions/ext_blueprints.py:16](../../api/extensions/ext_blueprints.py#L16)）注册所有蓝图并为不同入口配置 CORS，使请求得以进入服务层。
- `ext_import_modules`（[api/extensions/ext_import_modules.py:4](../../api/extensions/ext_import_modules.py#L4)）简单地 import `events.event_handlers`，靠 import 副作用把监听器接入全局事件总线。

阅读完扩展后，可以列出一张“初始化时间线”，标注哪些扩展提供全局单例（例如 `db`, `storage`, `celery_app`），方便后续章节追踪来源。

顺带抄下导览员在面板旁边贴的小卡片，提醒新来的同事们记得怎么接线：

```
主控面板快捷入门：
  ① 自报家门：ext.__name__ 会被登记，以免夜班互相踩脚本
  ② 接好线路：init_app(app) 时别忘了挂上路由、客户端或信号监听
  ③ 值班状态：is_enabled() == False 则自动免打扰，DEBUG 模式会记录来过几分钟
```

### 2. 工牌系统：上下文管理与请求隔离
发完胸牌，向导带我们参观“工牌管理处”——也就是 `RecyclableContextVar` 的办公室（`api/contexts/wrapper.py:14`）。主管手里握着一个 `_thread_recycles` 计数器，双眼时刻留意有没有线程偷偷换班却不换工牌。只要有人在 `before_request` 时喊一声“换牌啦！”，计数器就会上调；取牌时还要对比全场的换班次数，一旦发现旧牌，只能认命丢进失物招领处（直接抛出 `LookupError`）。

```python
# api/contexts/wrapper.py:14
class RecyclableContextVar(Generic[T]):
    # 工牌办公室的记账本：统计这条生产线换班多少次
    _thread_recycles: ContextVar[int] = ContextVar("thread_recycles")

    @classmethod
    def increment_thread_recycles(cls):
        try:
            # 啊哈，又见面了，旧工牌先查查换班次数
            recycles = cls._thread_recycles.get()
            # 给计数器加一，提醒大家立即换新牌
            cls._thread_recycles.set(recycles + 1)
        except LookupError:
            # 新面孔？那就从零开始登记
            cls._thread_recycles.set(0)

    def get(self, default: T | HiddenValue = _default) -> T:
        # 看看工牌更新次数是否追得上换班节奏
        thread_recycles = self._thread_recycles.get(0)
        self_updates = self._updates.get()
        if thread_recycles > self_updates:
            self._updates.set(thread_recycles)
        if thread_recycles < self_updates:
            return self._context_var.get()
        if isinstance(default, HiddenValue) or default is _default:
            raise LookupError
        return default
```

工牌管理员还贴了一段“防粘指南”，解释为什么要这么折腾：

```
工牌小贴士：
  • 同一条流水线（线程/greenlet）连轴转？记得敲换班钟 _thread_recycles += 1。
  • 每张工牌都会记住自己是在哪次换班后领到的（_updates）。
  • 取牌时若发现换班次数早就超过自己，立刻认定“我是旧牌”，交回去等新牌。
  • 写入时顺手把 _updates 调到最新一班，再加一，表示“我刚更新过”。
  • 如果调用者没给默认值又碰上旧牌，直接抛 LookupError 提醒“快补办”。

总结：无论线程如何复用，租户 ID、请求追踪号都不会粘在下一个访客身上，管理员已经替你清理干净了。
```

### 3. 服务办公室：入口与依赖注入
走进服务办公室，发现墙上贴着“请勿在走廊里直接 new Repository”。[api/services/__init__.py:1](../../api/services/__init__.py#L1) 把文件柜整理得一尘不染，只露出错误命名空间这个安全垫。拿工作流部门举例：`WorkflowService` 坐在 52 号工位（[api/services/workflow_service.py:52](../../api/services/workflow_service.py#L52)），手边放着一个 `sessionmaker` 备用电源，默认从 `ext_database` 的发电机拉线。它不自己动手造仓储，而是拨打 `DifyAPIRepositoryFactory.create_api_workflow_node_execution_repository()`，请求配送现成的仓储对象，这样随时可以换型号、调测试环境。

在 `WorkflowService` 的具体方法中，你会看到大量 `core.workflow.*` 的调用，例如 `WorkflowNodeExecution` 实体、`WorkflowEntry` 构造器、`VariablePool` 等。这证明服务层主要承担跨层协调、持久化和权限校验，而真正的业务规则来自核心域模块。

```python
# api/services/workflow_service.py:52
class WorkflowService:
    def __init__(self, session_maker: sessionmaker | None = None):
        # 有客人自带咖啡豆（session factory）？没带的话就用店里的
        if session_maker is None:
            session_maker = sessionmaker(bind=db.engine, expire_on_commit=False)
        self._node_execution_service_repo = (
            # 呼叫仓储配送中心：请送一份“节点执行仓库”到 52 号工位
            DifyAPIRepositoryFactory.create_api_workflow_node_execution_repository(session_maker)
        )
```

### 4. 生产车间：核心域的组织方式
穿上安全帽，我们正式踏入核心车间。`api/core/` 整整齐齐地把各类机器排成阵列，工作流车间还有自己的宣传册（`api/core/workflow/README.md:1`），声称“我们遵循严格的分层原则，GraphEngine 在最上层负责统筹，Graph/Nodes 则负责实际加工，Events 用来广播大事”。拐角处的 `core/workflow/enums.py` 像一本颜色鲜艳的说明书，提醒哪种信号是成功、哪种代表异常；`constants.py` 则把各种常量贴成海报，免得工人记错参数。

向导还拉开了几道安全警戒线，带我们看更细致的装配过程：

- **Graph（`core/workflow/graph/`）**：就像生产线的 CAD 图纸，包含节点、连线、条件、入口出口等数据结构。`graph_template.py` 定义了图纸的格式；`edge.py` 记录每根传送带的条件与去向；`runtime_state_protocol.py` 规定运行时需要遵守的“安全操作规程”。
- **Nodes（`core/workflow/nodes/`）**：这里是机器设备仓库，LLM、HTTP、Loop、Datasource 等各型机床都安有自己的 `_run()`，旁边还有 `node_mapping.py` 这份“设备与版本对照表”确保调用时不会接错电压。
- **Runtime（`core/workflow/runtime/`）**：运行时办公室看管 `GraphRuntimeState` 与 `VariablePool`，确保变量像原料一样被放在正确的货架；`variable_loader.py` 是叉车司机，缺原料时会去仓库补货。
- **Graph Engine（`core/workflow/graph_engine/`）**：调度中心，负责让每台机器按顺序工作，支持并发、暂停、恢复。`manager.py` 指挥整体运行，`worker.py` 执行具体节点，`layers/` 则是外挂的安全/监控插件。
- **Events（`core/workflow/graph_events/` 与 `node_events/`）**：扩音喇叭，广播每一次机器启动、成功、失败的消息；上层服务或监听器可以订阅这些事件，实现审计或回放。

宣传册上还反复强调：任何机器都不能擅自跨层拿零件——例如节点实现不能直接找 Graph Engine 借工具，这些“分层礼仪”写在 README 和 import-linter 规则里，违规会被巡逻机器人记名。

为了将“服务层调用核心域”串成图，可以引用以下文字示意：
```text
HTTP Blueprint (controllers/...) 
    -> Service (api/services/workflow_service.py) 
        -> Core Workflow (api/core/workflow/...) 
            -> Repository / Models (api/repositories, api/models)
```
建议自行扩展这张图，补充你在代码中发现的钩子或事件出口。

下面的字符画提供一个更完整的调用链，展示请求从入口到各层模块的流向：
```
        +-----------------------------+
        | HTTP Request / WSGI Server  |
        +--------------+--------------+
                       |
                       v
        +--------------+--------------+
        | controllers.* blueprints    |
        | (api/controllers/...)       |
        +--------------+--------------+
                       |
                       v
        +--------------+--------------+
        | services/workflow_service   |
        | services/workflow_run_*     |
        +--------------+--------------+
                       |
                       v
        +--------------+--------------+
        | core/workflow/...           |
        | graph | nodes | runtime     |
        +--------------+--------------+
                       |
                       v
        +--------+-----------+--------+
        | repositories/*.py  | models |
        | (SQLAlchemy layer) |        |
        +--------+-----------+--------+
                       |
                       v
        +--------------+--------------+
        | extensions   (db, storage,  |
        |               redis, celery)|
        +-----------------------------+
```

### 4.1 设备启停表：扩展初始化时间线（建议参考）
为了理解全局依赖对象的来源，向导给我们发了份“设备启停表”。每个扩展都是上夜班的工友，排班表清清楚楚写着谁负责照明、谁负责搬货，免得凌晨三点突然找不到 Redis 的钥匙：

```
┌───────────────────┬────────────────────────────┬─────────────────────────────┐
│ 顺序区块          │ 扩展列表                   │ 主要作用                    │
├───────────────────┼────────────────────────────┼─────────────────────────────┤
│ 启动前置          │ ext_timezone               │ 统一时区配置                │
│                   │ ext_logging                │ 日志处理器 + RequestId      │
│                   │ ext_warnings               │ 告警/警告钩子               │
│                   │ ext_import_modules         │ 触发事件处理器注册          │
├───────────────────┼────────────────────────────┼─────────────────────────────┤
│ 底层基础          │ ext_orjson                 │ JSON 序列化                 │
│                   │ ext_set_secretkey          │ Flask SECRET_KEY            │
│                   │ ext_compress               │ 响应压缩                    │
│                   │ ext_code_based_extension   │ 代码扩展能力加载            │
├───────────────────┼────────────────────────────┼─────────────────────────────┤
│ 数据与指标        │ ext_database               │ SQLAlchemy + gevent 兼容    │
│                   │ ext_app_metrics            │ 指标采集                    │
│                   │ ext_migrate                │ Alembic 迁移                │
├───────────────────┼────────────────────────────┼─────────────────────────────┤
│ 后端依赖          │ ext_redis                  │ Redis 客户端                │
│                   │ ext_storage                │ 存储后端                    │
│                   │ ext_celery                 │ Celery app                  │
│                   │ ext_login                  │ 登录管理                    │
│                   │ ext_mail                   │ 邮件发送                    │
│                   │ ext_hosting_provider       │ 托管提供商集成              │
├───────────────────┼────────────────────────────┼─────────────────────────────┤
│ 监控与网关        │ ext_sentry                 │ 错误上报                    │
│                   │ ext_proxy_fix              │ Proxy 适配                  │
│                   │ ext_otel                   │ OpenTelemetry               │
│                   │ ext_request_logging        │ 请求日志                    │
├───────────────────┼────────────────────────────┼─────────────────────────────┤
│ 接口与命令        │ ext_blueprints             │ 注册所有蓝图                │
│                   │ ext_commands               │ CLI 命令入口                │
└───────────────────┴────────────────────────────┴─────────────────────────────┘
```

阅读时可以把产生的全局对象（如 `db`, `storage`, `celery_app`）写在便利贴上贴回这张表，以后再遇到“Celery app 哪里来的”时，就能假装自己记忆力惊人。

### 2.1 工牌流转示意（补充）
工牌办公室还贴了一张流程图，防止有人忘记出门要交回胸牌。抄在本子上，免得下次 guard 又用“LookupError”瞪你：
```
Request Start
    |
    v
before_request hook
    |
    v
RecyclableContextVar.increment_thread_recycles()
    |
    v
Service layer sets tenant/user context vars
    |
    v
Core workflow reads context vars (e.g., system_variable.py)
    |
    v
Request end → context vars discarded (recycle count increments next time)
```
这张图说明：上下文值不会自动 reset，而是依赖回收计数避免“旧值泄漏到新请求”。在调试租户或用户身份相关问题时，可以先确认这些步骤是否按预期触发。

### 5. 仓储工厂与多实现支持
继续往后是仓储工厂，门口竖着一块牌子：“禁止服务层直接抱走 ORM 模型，请走仓储窗口。”`DifyAPIRepositoryFactory`（[api/repositories/factory.py:17](../../api/repositories/factory.py#L17)）负责根据配置发货——今天想要 SQLAlchemy 版？可以。明天想换企业定制版？也没问题。只要递上 `sessionmaker` 这张通关证，它就会从货架上抓出合适的仓储实例送到你桌前。对测试同学来说，还能随时换假货（Mock）练习。

```python
# api/repositories/factory.py:27
class DifyAPIRepositoryFactory(DifyCoreRepositoryFactory):
    @classmethod
    def create_api_workflow_node_execution_repository(cls, session_maker: sessionmaker):
        # 看看今天菜单上写的是哪款仓库实现（可被企业版换掉）
        class_path = dify_config.API_WORKFLOW_NODE_EXECUTION_REPOSITORY
        repository_class = import_string(class_path)
        # 把新鲜的 session_maker 塞给仓库，让它随叫随开数据库会话
        return repository_class(session_maker=session_maker)
```

### 6. 架构约束与静态守护
园区里偶尔还能看到巡逻机器人，胸前贴着“import-linter”。它会盯着每位工友：别跨楼层乱穿，GraphEngine 别直接摸 Nodes 的内部细节。于是像 `GraphRuntimeState` 这样的同学（[api/core/workflow/runtime/graph_runtime_state.py:352](../../api/core/workflow/runtime/graph_runtime_state.py#L352)）遇到需要的类时会悄悄打电话 `importlib.import_module(...)`，确保遵守“内向外”的交通规则。一旦违反，可是会被记名传唤的。

```python
# api/core/workflow/runtime/graph_runtime_state.py:352
def _build_ready_queue(self) -> ReadyQueueProtocol:
    # 悄悄打个越洋电话，要个“队列”同事来帮忙（保持分层礼仪）
    module = importlib.import_module("core.workflow.graph_engine.ready_queue")
    in_memory_cls = module.InMemoryReadyQueue
    # 默认派内存小推车上岗，哪天要换 Redis 叉车可以再说
    return in_memory_cls()
```

## 动手任务
- 在笔记中画出一张“入口大厅 → 服务办公室 → 生产车间 → 仓储记录”的调用图，标明文件路径与关键类。
- 记录每个扩展启用时机及其对全局对象（如 `db`, `storage`, `celery`）注入的位置。

## 思考题
- 如果要新增一个新的核心模块，例如“规则引擎”，你会把入口放在哪个目录？需要哪些扩展配合？
- 服务层为何要通过工厂获取仓储而不是直接引用 `models`？这与测试、解耦有什么关系？

## 延伸阅读
- `docs/zh-CN/README.md` 中的架构简介
- `CONTRIBUTING.md` 关于代码结构的约定
- `api/tests/unit_tests/core/workflow/test_workflow_entry.py`，提前感知核心域的测试策略
