# 03 图纸档案室与运行态监控室

夜深了，导览车在走廊里悄悄滑行。我们拐进“图纸档案室”，墙上整齐挂着 Graph 的蓝图；再往里是“运行态监控室”，屏幕上跳动着 ready queue、outputs、llm_usage 等指标。向导说：若想看懂 Dify 的工作流，先要读懂这两间屋子里发生了什么。

本章分两部分：先拆蓝图（Graph、Edge、Template、工厂），再逛监控室（GraphRuntimeState、VariablePool）。途中穿插一段小剧场，把 JSON 图纸翻译成真实机器运转。

---

## 图纸：从 DSL 到 Graph

档案柜第一层，标着 GraphTemplate（[api/core/workflow/graph/graph_template.py:1](../../api/core/workflow/graph/graph_template.py#L1)）。它像“子装配图册”，把一组节点和边打包，标注根节点与输出选择器（字段定义在 `api/core/workflow/graph/graph_template.py:17`–`api/core/workflow/graph/graph_template.py:20`）：

```python
# api/core/workflow/graph/graph_template.py
class GraphTemplate(BaseModel):
    """CAD 图册：节点、边、根节点列表、输出选择器"""
    nodes: dict[str, dict[str, Any]] = Field(default_factory=dict, description="node definitions mapping")
    edges: dict[str, dict[str, Any]] = Field(default_factory=dict, description="edge definitions mapping")
    root_ids: list[str] = Field(default_factory=list, description="root node IDs")
    output_selectors: list[str] = Field(default_factory=list, description="output selectors")
```

再往下是 Edge（[api/core/workflow/graph/edge.py:1](../../api/core/workflow/graph/edge.py#L1)），每条边都清楚写着从哪台机器（tail）到哪台机器（head），以及是哪个“出口”（`source_handle`）发出来的（`Edge` 字段定义见 `api/core/workflow/graph/edge.py` 顶部）：

```python
# api/core/workflow/graph/edge.py
@dataclass
class Edge:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tail: str = ""      # 谁把物料送出来（source）
    head: str = ""      # 谁来接（target）
    source_handle: str = "source"  # 哪个出口（条件/分支口）
    state: NodeState = field(default=NodeState.UNKNOWN)  # 这条传送带当前状态
```

蓝图真正立体化的是 Graph（[api/core/workflow/graph/graph.py:1](../../api/core/workflow/graph/graph.py#L1)）。它接过“节点清单 + 边清单”，决定谁是根，怎么连线，哪些分支一开始就应该跳过：

```python
# api/core/workflow/graph/graph.py（节选）
class Graph:
    def __init__(..., root_node: Node):
        self.nodes = nodes or {}
        self.edges = edges or {}
        self.in_edges = in_edges or {}
        self.out_edges = out_edges or {}
        self.root_node = root_node

    @classmethod
    def init(cls, *, graph_config, node_factory, root_node_id=None) -> "Graph":
        # 1) 取图纸里的 edges/nodes
        edge_configs = cast(list[dict[str, object]], graph_config.get("edges", []))
        node_configs = cast(list[dict[str, object]], graph_config.get("nodes", []))
        if not node_configs:
            raise ValueError("Graph must have at least one node")

        # 2) 去掉“便签”类节点（自带注释的小黄贴）
        node_configs = [c for c in node_configs if c.get("type", "") != "custom-note"]

        # 3) 映射 node_id -> node_config
        node_configs_map = cls._parse_node_configs(node_configs)

        # 4) 自动/显式寻找 root（实现见 `api/core/workflow/graph/graph.py:83`–`api/core/workflow/graph/graph.py:121`）
        root_node_id = cls._find_root_node_id(node_configs_map, edge_configs, root_node_id)

        # 5) 把边做成真传送带（in_edges/out_edges 也建好）
        edges, in_edges, out_edges = cls._build_edges(edge_configs)

        # 6) 用 NodeFactory 把“节点图纸”变成“可动的机器实例”
        nodes = cls._create_node_instances(node_configs_map, node_factory)

        # 7) 若某些机器设置了 FAIL_BRANCH，则把它们提升为“分支型执行”
        cls._promote_fail_branch_nodes(nodes)

        # 8) 标记非激活根分支为跳过（多根场景）
        cls._mark_inactive_root_branches(nodes, edges, in_edges, out_edges, root_node_id)

        # 9) 装配完成，校验一遍，再交付
        graph = cls(nodes=nodes, edges=edges, in_edges=in_edges, out_edges=out_edges, root_node=nodes[root_node_id])
        get_graph_validator().validate(graph)
        return graph
```

上面这段“装配九步曲”，贯穿了从用户 DSL 到引擎可运行图的全部关键点。它有三个易踩坑的小提醒：
- 根节点的判定不仅看“没有入边”，还会优先挑 START/DATASOURCE 类节点。
- `sourceHandle` 代表条件/出口口子，决定一条边属于哪条分支（例如 true/false）。
- 多根图里，只能有一个“活跃根”。其它根及下游会被标为 SKIPPED，避免同时跑错线。

九步曲速记（装配流水线，对应 Graph 内部各 @classmethod 实现位置）：

```
[DSL nodes/edges]
     |
     v
(1) 读取配置  ──▶  (2) 过滤便签节点  ──▶  (3) 建 node 映射
                                           |
                                           v
                                   (4) 寻找 root
                                           |
                                           v
                                   (5) 建 Edge + 倒排表
                                           |
                                           v
                                   (6) NodeFactory 造机器
                                           |
                                           v
                                   (7) 提升 FAIL_BRANCH
                                           |
                                           v
                                   (8) 标记非活跃根支线
                                           |
                                           v
                                   (9) 校验并交付 Graph
```

多根场景速览：

```
rootA (active) ───▶ ...

rootB (inactive, SKIPPED) ──x─▶ nodeB1 (SKIPPED)
                               x─▶ nodeB2 (若全部入边 SKIPPED → 也 SKIPPED)

注：只有 top-level ROOT 会参与这个“择一而活”，其余会被整支线跳过。
```

### NodeFactory 与版本映射：谁来把图纸变机器

装配车间的“招工规则”由工厂类决定。默认工厂 `DifyNodeFactory`（[api/core/workflow/nodes/node_factory.py:1](../../api/core/workflow/nodes/node_factory.py#L1)）会从“类型→类”对照表里挑 `latest` 版本的实现：

```python
# api/core/workflow/nodes/node_factory.py（节选）
class DifyNodeFactory(NodeFactory):
    def create_node(self, node_config: dict[str, object]) -> Node:
        node_id = node_config.get("id")
        node_data = node_config.get("data", {})
        node_type_str = node_data.get("type")  # 例如 "llm" / "http_request" / ...
        node_type = NodeType(node_type_str)

        node_mapping = NODE_TYPE_CLASSES_MAPPING.get(node_type)
        node_class = node_mapping.get(LATEST_VERSION)   # 优先 latest（兼容策略也支持具体版本）

        node_instance = node_class(
            id=node_id,
            config=node_config,
            graph_init_params=self.graph_init_params,
            graph_runtime_state=self.graph_runtime_state,
        )
        node_instance.init_node_data(node_data)
        return node_instance
```

“对照表”就在 [api/core/workflow/nodes/node_mapping.py:1](../../api/core/workflow/nodes/node_mapping.py#L1)，其中有些类型（如 TOOL/AGENT）同时保留了历史版本号以兼容旧数据。速记图：

```
NodeType ──► { "latest": NodeClass, "1": OldNodeClass, ... }
   │
   └── DifyNodeFactory ──► 选用 latest（或按需要挑具体版本）
```

### Graph 校验：别把传送带接到空气上

交付前，还要跑一遍安全巡检（[api/core/workflow/graph/validation.py:1](../../api/core/workflow/graph/validation.py#L1)）：

```python
class _EdgeEndpointValidator:
    def validate(self, graph: Graph):
        for edge in graph.edges.values():
            if edge.tail not in graph.nodes:  # 源节点不存在
                ...
            if edge.head not in graph.nodes:  # 目标节点不存在
                ...

class _RootNodeValidator:
    container_entry_types = (NodeType.ITERATION_START, NodeType.LOOP_START)  # 见 `api/core/workflow/graph/validation.py:74`
    def validate(self, graph: Graph):
        root = graph.root_node
        if root.id not in graph.nodes: ...
        if root.execution_type != ROOT and node_type not in container_entry_types: ...
```

常见报错小抄：
- `[MISSING_NODE] Edge edge_3 references unknown target node 'foo'.` 你把传送带接到了空气上。
- `[INVALID_ROOT] Root node 'xxx' must declare execution type 'root'.` 根节点姿势不对，记得声明 ROOT 或使用容器入口（ITERATION_START/LOOP_START）。

### GraphBuilder：五分钟拼一条测试线

写单测时不必每次都手搓 DSL，可用 `GraphBuilder`（[api/core/workflow/graph/graph.py:376](../../api/core/workflow/graph/graph.py#L376) 起）快速搭一条线：

```python
from core.workflow.graph.graph import Graph, GraphBuilder
from core.workflow.nodes.start import StartNode
from core.workflow.nodes.llm import LLMNode
from core.workflow.nodes.end.end_node import EndNode

builder = Graph.new()             # 或 GraphBuilder(graph_cls=Graph)
root = StartNode(...)
builder.add_root(root)
builder.add_node(LLMNode(...), from_node_id=root.id)
builder.add_node(EndNode(...))
graph = builder.build()
```

ASCII：
```
StartNode ──► LLMNode ──► EndNode
```

### 小样例：把 JSON 图纸翻译成 Graph

先写一份最小 DSL（start → llm → end）：

```json
{
  "nodes": [
    {"id": "start", "type": "custom", "data": {"type": "start"}},
    {"id": "llm_1", "type": "custom", "data": {"type": "llm", "version": "1"}},
    {"id": "end",   "type": "custom", "data": {"type": "end"}}
  ],
  "edges": [
    {"source": "start", "target": "llm_1", "sourceHandle": "source"},
    {"source": "llm_1", "target": "end",   "sourceHandle": "source"}
  ]
}
```

ASCII 视角看一眼：

```
start ──(source)──▶ llm_1 ──(source)──▶ end
```

交给 `Graph.init()` 后，就能得到：
- `nodes`: {"start": Node(...), "llm_1": Node(...), "end": Node(...)}
- `edges`: {"edge_0": Edge(tail="start", head="llm_1"), "edge_1": Edge(tail="llm_1", head="end")}
- `in_edges/out_edges`: 两张倒排表，查询谁连进来、谁连出去。
- `root_node`: “start” 这位台柱子。

---

## 运行态监控：GraphRuntimeState

监控室的大屏幕展示的是运行态（[api/core/workflow/runtime/graph_runtime_state.py:1](../../api/core/workflow/runtime/graph_runtime_state.py#L1)）。它掌管 ready queue、执行聚合、响应协调、以及 outputs/tokens 等统计。核心属性都带着“需要时才开灯”的节电模式（lazy init）：

```python
# api/core/workflow/runtime/graph_runtime_state.py（节选）
class GraphRuntimeState:
    def __init__(..., variable_pool: VariablePool, start_at: float, ...):
        self._variable_pool = variable_pool
        self._start_at = start_at
        self._llm_usage = (llm_usage or LLMUsage.empty_usage()).model_copy()
        self._outputs = deepcopy(outputs) if outputs is not None else {}
        self._ready_queue = ready_queue
        self._graph_execution = graph_execution
        self._response_coordinator = response_coordinator

    @property
    def ready_queue(self) -> ReadyQueueProtocol:
        if self._ready_queue is None:
            self._ready_queue = self._build_ready_queue()    # 临时打电话叫“排队同事”来上岗
        return self._ready_queue  # 参见 `api/core/workflow/runtime/graph_runtime_state.py:318`–`api/core/workflow/runtime/graph_runtime_state.py:356`

    @property
    def graph_execution(self) -> GraphExecutionProtocol:
        if self._graph_execution is None:
            self._graph_execution = self._build_graph_execution()  # 同理，执行聚合也是需要时再就位
        return self._graph_execution

    @property
    def response_coordinator(self) -> ResponseStreamCoordinatorProtocol:
        if self._response_coordinator is None:
            if self._graph is None:
                raise ValueError("Graph must be attached before accessing response coordinator")
            self._response_coordinator = self._build_response_coordinator(self._graph)
        return self._response_coordinator
```

三位常驻同事的职责分工：
- ready_queue：谁准备好了就“上号”，并支持序列化/反序列化，断电也不慌。
- graph_execution：记录开工、完成、失败、异常数，像个“班长日志”。
- response_coordinator：把“能流式输出的节点”登记好，方便上游边跑边看结果。

序列化/恢复一条龙也都准备好了：

```python
def dumps(self) -> str:
    snapshot = {
        "version": "1.0",
        "start_at": self._start_at,
        "total_tokens": self._total_tokens,
        "node_run_steps": self._node_run_steps,
        "llm_usage": self._llm_usage.model_dump(mode="json"),
        "outputs": self.outputs,
        "variable_pool": self.variable_pool.model_dump(mode="json"),
        "ready_queue": self.ready_queue.dumps(),
        "graph_execution": self.graph_execution.dumps(),
        "paused_nodes": list(self._paused_nodes),
    }
    if self._response_coordinator is not None and self._graph is not None:
        snapshot["response_coordinator"] = self._response_coordinator.dumps()
    return json.dumps(snapshot, default=pydantic_encoder)
```

> 小贴士：`_build_ready_queue/_build_graph_execution/_build_response_coordinator` 都是“打越洋电话”按需加载，遵守分层礼仪（runtime 不直接 import 引擎实现）。

运行态鸟瞰图：

```
           +----------------------+
           |      VariablePool    |
           +----------+-----------+
                      |
                      | (attach)
                      v
 +--------------------+--------------------+
 |           GraphRuntimeState             |
 |  start_at, outputs, llm_usage, steps   |
 +----+---------------+--------------------+
      |               |                |
      |               |                |
      v               v                v
 +----+----+    +-----+------+   +-----+----------------+
 | Ready   |    | GraphExec  |   | ResponseCoordinator  |
 | Queue   |    | (started/  |   | (stream response    |
 | (put/   |    |  done/err) |   |  nodes/register)    |
 |  get)   |    +------------+   +----------------------+
 +---------+

  (Graph) ——— attached later for response coordinator to know the shape
```

暂停/恢复小剧场：

```
用户点“暂停”
   → GraphRuntimeState.register_paused_node(node_id)
   → snapshot.dumps() 记录 paused_nodes

恢复时
   → state = GraphRuntimeState.from_snapshot(snapshot)
   → paused = state.consume_paused_nodes()  # 取出并清空待恢复节点
   → 把 paused 节点重新放入 ready_queue / 调度接力
```

---

## 高架仓库：VariablePool

再往里走是一座“高架仓库”（[api/core/workflow/runtime/variable_pool.py:1](../../api/core/workflow/runtime/variable_pool.py#L1)）。它把每个变量放到“货架层级路径”上：第一层是 node_id，第二层是变量名；再深一点可以取文件属性或对象子字段。

```python
class VariablePool(BaseModel):
    # 变量总表：第一层是节点 ID，第二层是变量名（哈希后作为 key），值是 Segment/Variable
    variable_dictionary: defaultdict[str, dict[str, VariableUnion]] = Field(default=defaultdict(dict))
    user_inputs: Mapping[str, Any] = Field(default_factory=dict)   # 主要供 StartNode 构造输入
    system_variables: SystemVariable = Field(default_factory=SystemVariable.empty)
    environment_variables: Sequence[VariableUnion] = Field(default_factory=list)
    conversation_variables: Sequence[VariableUnion] = Field(default_factory=list)

    def model_post_init(self, context: Any, /):
        # 入库：系统变量、环境变量、会话变量、RAG 变量统统摆到对应 node_id 名下
        self._add_system_variables(self.system_variables)
        for var in self.environment_variables:
            self.add((ENVIRONMENT_VARIABLE_NODE_ID, var.name), var)
        for var in self.conversation_variables:
            self.add((CONVERSATION_VARIABLE_NODE_ID, var.name), var)
```

加入、取用与模板替换，是仓库三件套：

```python
def add(self, selector: Sequence[str], value: Any, /):
    # 只收两段式地址：[node_id, variable_name]
    if len(selector) != SELECTORS_LENGTH:
        raise ValueError("Invalid selector ... expected 2 elements")
    # 不管你给的是 Variable、Segment 还是“小白盒子”，都会被正规化再入库
    ...

def get(self, selector: Sequence[str], /) -> Segment | None:
    # 两段：还你整箱货；三段以上：沿着小标签（文件属性/对象键）往里翻
    ...

def convert_template(self, template: str, /):
    # 把 "{{#node.var#}}" 这种小占位，替换成段落组（SegmentGroup）
    ...
```

模板替换小抄（正则见 `VARIABLE_PATTERN`）：

```
"Hello {{#llm1.structured_output.summary#}}!"
   └─► 分割成文字段 + 变量段，变量段由选择器解析出 Segment
       最终得到 SegmentGroup，供节点/模板引擎进一步渲染
```

选择器规则抄给你：

```
选择器基础：
  • [node_id, variable_name]               → 整个变量段（Segment）
  • [node_id, variable_name, "url"]       → 如果是文件段，取其 url/name/size 等属性
  • [node_id, variable_name, "foo", "bar"] → 如果是对象段，逐层取 foo.bar
```

货架示意：

```
VariablePool
  ├─ http1
  │    └─ output  → FileSegment
  │         ├─ url   (string)
  │         ├─ name  (string)
  │         └─ size  (number)
  ├─ llm1
  │    └─ structured_output → ObjectSegment
  │         └─ summary (string)
  └─ env (ENVIRONMENT_VARIABLE_NODE_ID)
       └─ api_key → Segment
```

更多仓库小功能：

```
get_by_prefix(prefix)  → 打包带走某个节点下的所有变量快照
get_file(selector)     → 若变量是文件段，直接拿到 FileSegment
remove(selector)       → 按 [node] 或 [node, name] 清仓
empty()                → 一键建个带系统变量的空仓库
```

### 变量搬运工：把用户输入放上货架

当我们单步/调试运行节点时，需要把用户的输入对齐到仓库对应的格子里，这活由 `WorkflowEntry.mapping_user_inputs_to_variable_pool()` 操作（[api/core/workflow/workflow_entry.py:364](../../api/core/workflow/workflow_entry.py#L364) 起）：

```python
for node_variable, variable_selector in variable_mapping.items():
    node_variable_list = node_variable.split(".")
    node_variable_key = ".".join(node_variable_list[1:])

    # 用户没带，仓库也没现货，就严肃提醒“找不到变量”
    if (node_variable_key not in user_inputs and node_variable not in user_inputs) \
       and not variable_pool.get(variable_selector):
        raise ValueError(...)

    # 环境变量早就上架了，不要再塞一份
    if variable_pool.get(variable_selector) and variable_selector[0] == ENVIRONMENT_VARIABLE_NODE_ID:
        continue

    # 支持把“文件占位描述”转成 File 对象（单个或列表）
    input_value = user_inputs.get(node_variable) or user_inputs.get(node_variable_key)
    if isinstance(input_value, dict) and {"type", "transfer_method"} <= set(input_value):
        input_value = file_factory.build_from_mapping(mapping=input_value, tenant_id=tenant_id)
    if isinstance(input_value, list) and all("type" in x and "transfer_method" in x for x in input_value):
        input_value = file_factory.build_from_mappings(mappings=input_value, tenant_id=tenant_id)

    # LLM 结构化输出的小特例：把 {structured_output, field} 重组为对象
    if len(variable_key_list) == 2 and variable_key_list[0] == "structured_output":
        input_value = {variable_key_list[1]: input_value}
        variable_key_list = variable_key_list[0:1]

    # 最后把货物推上高架：
    variable_pool.add([variable_node_id] + variable_key_list, input_value)
```

搬运路线示意：

```
user_inputs
  ├─ "llm1.structured_output.summary" : "nice!"
  └─ "http1.output" : { type: "image", transfer_method: "local_file", ... }
           │                                      │
           └─────────(files mapping)──────────────┘
                          │
                          v
           File instance(s) / plain value(s)
                          │
                          v
variable_pool.add(["llm1", "structured_output"], {"summary": "nice!"})
variable_pool.add(["http1", "output"], <File or File[]>)
```

---

## 小剧场：一条分支 + 文件属性 + 模板替换

我们把“客户提问 → 调用 HTTP 取图 → LLM 说明 → 输出链接”拼成一条支线，顺便展示文件属性和模板替换。

DSL（简化）：

```json
{
  "nodes": [
    {"id": "start",  "type": "custom", "data": {"type": "start"}},
    {"id": "http1",  "type": "custom", "data": {"type": "http_request"}},
    {"id": "llm1",   "type": "custom", "data": {"type": "llm"}},
    {"id": "end",    "type": "custom", "data": {"type": "end"}}
  ],
  "edges": [
    {"source": "start", "target": "http1", "sourceHandle": "source"},
    {"source": "http1", "target": "llm1",  "sourceHandle": "success"},
    {"source": "http1", "target": "end",   "sourceHandle": "failure"},
    {"source": "llm1",  "target": "end",   "sourceHandle": "source"}
  ]
}
```

ASCII：

```
start ─────▶ http1 ──(success)──▶ llm1 ───▶ end
                 └─(failure)────▶ end
```

运行片段：
1) `Graph.init()` 识别 `http1` 的两条出口（success/failure），两条边各归其位。
2) `http1` 成功时把下载到的图片文件入库在 `http1.output`，于是：
   - `variable_pool.get(["http1", "output", "url"])` 取文件 URL；
   - 模板 `The image: {{#http1.output.url#}}` 会被 `convert_template` 改写成段组。
3) `llm1` 用模板拼出说明，交给 `end` 收尾。

---

## 参观总结（贴墙上）

- Graph 是蓝图到机器的桥，`init()` 的九步曲把“清单”变“生产线”。
- 运行态三件套（ready_queue、graph_execution、response_coordinator）按需上岗，断电可恢复。
- VariablePool 是高架仓库，所有变量都遵循“[node, name, ...]”的路径；文件属性、对象字段均可深取。
- 单步/调试时，`mapping_user_inputs_to_variable_pool()` 扮演搬运工，把用户输入塞回正确货位。

预告：下一篇我们走进“夜班调度中心”，看 GraphEngine 如何一边接收命令（暂停/终止），一边驱动工位并行运转。
