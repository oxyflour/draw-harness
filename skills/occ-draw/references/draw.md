# 已在 OCCT 7.7 上验证的命令

## 原生 Tcl

```tcl
box base 80 50 12
pcylinder drill 6 20
ttranslate drill 40 25 -4
bcut plate_v1 base drill
```

在 XY 平面创建 80×50、厚 12 的板，沿 +Z；半径 6 的通孔位于 (40,25)。预期体积 `48000 - pi*6*6*12`，bbox `[0,0,0]..[80,50,12]`，一个 solid。布尔结果可能封装在 compound 中，因此检查 `topology.solid`。

`bfuse result a b` 合并；`bcommon result a b` 求交；`ttranslate shape dx dy dz` 原位移动。圆角语法：`blend result source radius edge_name`，先枚举并绑定目标边。所有陌生命令仍须查询 `help`，特别是 chamfer、prism、revol 和复杂导入参数。

脚本中可以 `ah_inspect shape` 得到原生 JSON。此命令检查有效性并计算 bbox、体积、面积、边总长和拓扑数量。CLI/MCP 的 inspect 会自动解析这些数据。

完整 BRep 关系图可用 `ah_topology_graph shape [absolute-json-path]`，或下列专用接口；结构说明见 [topology-graph.md](topology-graph.md)。

## CLI 命令

所有命令经 `scripts/occ.ps1`，所有位置参数中的实体名使用 ASCII 字母/数字/下划线。

```text
doctor
start <session>
context <session>
exec <session> --file <UTF-8.tcl> --check <shape> [shape...]
exec <session> --script <Tcl> --check <shape>
help <session> <DRAW-command>
inspect <session> <shape>
topology <session> <shape> edge|face [--offset 0 --limit 100]
topology_graph <session> <shape> [--output <absolute.json>] [--overwrite]
select <session> <shape> edge|face <1-based-index> <bound-name>
export <session> <shape> <absolute.step|brep|stl> [--overwrite]
import <session> <shape-name> <absolute.step|brep>
checkpoint <session> <checkpoint-name> <shape> [shape...]
restore <session> <checkpoint-name>
memory <session>
memory <session> --key goal --value <text>
memory <session> --key parameters --json <JSON>
stop <session>
```

JSON `ok=false` 对应 CLI 退出码 1。eval 的结果在 `data.result`，Tcl 输出在 `data.stdout`，C++ 输出在 `data.native_output`。检查结果在 `checks`。路径中有空格或中文也可使用；输出目录须已存在。几何导出不能替代检查点的任务记忆。

## MCP 对照

`occ_session(action=start/context/stop)`；`occ_exec(script,check)`；`occ_inspect(shape)`；`occ_topology(shape,type[,index,name])`；`occ_topology_graph(shape[,path,overwrite])`；`occ_file(action=import/export,shape,path,format)`；`occ_checkpoint(action=save/restore/list)`；`occ_memory(action=get/set)`；`occ_help(command)`。所有调用均指定 session。

操作前记录目标输出名，执行后检查实际几何；不要将未执行的 Tcl 计划描述为已完成实体。
