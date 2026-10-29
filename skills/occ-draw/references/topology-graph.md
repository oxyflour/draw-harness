# BRep 拓扑关系图（schema_version = 1）

需要完整包含关系、共享边/顶点或邻接查询时使用此接口。只查询边面几何和序号时仍可使用 `topology`。

## 入口

CLI：

```powershell
.\occ-harness.ps1 topology_graph part final_shape
.\occ-harness.ps1 topology_graph part final_shape --output C:/path/graph.json
```

MCP：`occ_topology_graph(session, shape, path?, overwrite?)`。

Native RPC：

```json
{"op":"topology_graph","shape":"final_shape"}
```

增加 `path`（绝对 JSON 路径）时，完整图写入文件，RPC 返回路径、字节数和节点/引用数量摘要。已有文件需要 `overwrite:true`；CLI 对应 `--overwrite`。目录必须已存在。文件内容为 UTF-8 的图对象，不包含 RPC 的 `ok/data` 外壳。

原生 Tcl：`ah_topology_graph shape ?absolute-json-path?`，直接返回图或文件摘要。通过 `exec` 调用时受到 eval 结果的 64 KiB 限制，较大图应传文件路径，或使用专用 RPC/CLI/MCP 接口。Tcl 简便入口不覆盖已有文件。

## 图对象

| 字段 | 语义 |
| --- | --- |
| `schema_version` | 当前为 1 |
| `shape` | 查询的 DRAW 实体名 |
| `root` | 根节点 ID，当前为 1 |
| `root_orientation` | 原始根实体方向：FORWARD / REVERSED / INTERNAL / EXTERNAL |
| `node_count` / `use_count` / `definition_count` | 节点、直接引用、底层 TShape 的数量 |
| `nodes` | 按 TShape + 累积 Location 去重的节点 |
| `uses` | 直接父子引用；保留重复引用、相对方向和相对 Location |
| `edge_faces` | 对每个边节点列出唯一祖先面 ID，键为边 ID 的十进制字符串 |
| `vertex_edges` | 对每个顶点节点列出唯一祖先边 ID，键为顶点 ID 的十进制字符串 |
| `id_scope` | ID 仅适用于当前形状快照，不是跨编辑持久 ID |

每个 node：

```json
{
  "id": 9,
  "type": "edge",
  "type_index": 1,
  "definition_id": 9,
  "location": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
}
```

- `type` 支持 compound、compsolid、solid、shell、face、wire、edge、vertex。
- `type_index` 是现有 `subshapes/select` 针对此根实体、此类型的 1-based 索引；选择时使用该值，不能直接使用 graph ID。若 OCCT 按类型的 Explorer 未暴露该节点（例如部分嵌套 compound），该值为 null。
- `definition_id` 只区分底层 TShape。两个实例可以 definition_id 相同、location 不同，从而有不同的 node ID。
- 重合但独立创建的几何不会按坐标合并。身份遵循 OCCT 的 TShape/Location 相同性。
- `location` 是此节点累积到世界坐标的 4×4 齐次变换；node 自身规范化为 FORWARD，引用方向单独保存在 uses。

每个 use：

```json
{
  "id": 12,
  "parent": 4,
  "child": 9,
  "ordinal": 1,
  "orientation": "REVERSED",
  "location": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
}
```

- 每个唯一父节点展开一次，保留它的全部直接 child 引用。多个父引用可以共享同一 child 节点，因此是包含关系图；不把所有根路径重复展开成树。
- `ordinal` 是该父节点内部的 1-based 存储顺序，不保证 wire 边按首尾相连顺序排列。
- `orientation` 是相对于规范化为 FORWARD 的父节点的引用方向。沿某条根路径求最终方向时，需要从 `root_orientation` 开始按 OCCT 的方向组合规则累积。
- use 的 `location` 是 child 相对父节点的局部变换。矩阵以行数组保存，作用于列向量，满足 `child.location = parent.location × use.location`；平移列使用模型单位。
- 相同的 `(parent,child)` 可以出现多次。圆柱 seam 通常在同一个 wire 中引用同一 edge 两次，方向相反；圆形闭合 edge 的两个端点引用也可以指向同一 vertex。不要对 uses 按父子节点去重。

## 邻接与边界

`edge_faces` 和 `vertex_edges` 只列唯一祖先，不记录使用次数；完整使用次数和方向从 uses 获取。自由边的面列表、孤立顶点的边列表为空数组。

一条边可以关联 0、1、2 或更多个面。只有一个祖先面的边可能是边界边或 seam，不能只根据列表长度判断。多个面的相邻关系可由共享边的 `edge_faces` 派生；非流形边的多个祖先面都会保留。

## 大小与会话

专用 RPC 的内联图上限为 3 MiB，超限返回普通操作错误并建议传 path，不截断图，也不终止会话。文件输出绕过 4 MiB 的传输上限，仅返回小摘要。单图最多支持 100000 个节点和 500000 条直接引用，超限报错。

图查询不会修改模型。输出 ID、definition_id 和 type_index 都不应在布尔、圆角等模型修改后复用。DLL 更新后，已运行的 DRAW 仍持有旧模块；先保存检查点并 stop/start，再恢复实体以使用新模块。

实现直接使用 OCCT 7.7 的 TopoDS_Iterator、TopTools_IndexedMapOfShape 和 TopExp::MapShapesAndUniqueAncestors；无需解析 dump 文本或按几何距离推测连接关系。
