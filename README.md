# OCCT DRAW Agent Harness

面向 **gpt-6-luna** 的 Windows 本地直接建模工具链，基于指定安装的 `draw.bat` / OCCT 7.7.0。已编译的原生模块为 `bin/occ_agent.dll`，Python 仅负责会话、记忆和协议，几何计算使用真实 OCCT 内核。

## 快速使用

在 PowerShell 中：

```powershell
cd C:\Projects\occ-harness
.\occ-harness.ps1 doctor
.\occ-harness.ps1 start part
.\occ-harness.ps1 exec part --script 'box block_v1 80 50 12' --check block_v1
.\occ-harness.ps1 inspect part block_v1
.\occ-harness.ps1 checkpoint part base block_v1
.\occ-harness.ps1 export part block_v1 C:/Projects/occ-harness/artifacts/block.step
.\occ-harness.ps1 stop part
```

`--state-dir <directory>`、`--timeout <seconds>` 为全局选项，位于子命令前。默认单次 RPC 超时为 180 秒，超时终止对应 DRAW 会话，不自动重试。命令返回 JSON，操作完成退出码为 0，执行失败为 1；几何验收是否接受另看 `data.accepted`。复杂 Tcl 使用 `exec part --file C:/path/model.tcl --check final_shape`。默认单位约定为 mm。

## 接入 gpt-6-luna

1. 执行 `scripts/install-skill.ps1`，将 `occ-draw` 安装到个人 skills 目录；本次已经安装。仓库的 `AGENTS.md` 也指向同一 skill。
2. 本项目 `.codex/config.toml` 已配置目标模型和本地 MCP 服务。客户端载入项目配置后可发现十四个 `occ_*` 工具；其他 MCP 客户端使用 `config/mcp.json.example`。新增工具需要刷新 MCP 连接；未刷新时可用 CLI 同名子命令。
3. 在选择 **gpt-6-luna** 的聊天中使用 `$occ-draw`，例如：“创建 100×70×10 安装板，中心凸台直径 36、高 12，中心通孔直径 16，四个直径 7 的安装孔，外角 R3；检查并导出 STEP。”

MCP 未连接时，skill 可直接调用自己的 `scripts/occ.ps1`。切换模型由客户端完成；`start --model` 仅记录元数据。该工具链不需要 OpenAI API key，也不自行调用模型 API。项目配置只影响本项目，未修改用户全局配置。

MCP 入口是 `occ-harness.ps1 mcp`，使用 UTF-8 换行 JSON-RPC，支持 2025-11-25 及较早的握手协议。`prompts/get` 的 `occ-modeling` 提供 [Luna 指令](agents/luna.md)。当前服务按顺序执行请求；请求超时由 harness 处理。

## 能力与结构

| 层 | 位置 | 作用 |
| --- | --- | --- |
| Skill | `skills/occ-draw/` | 建模循环、实际命令帮助、几何验证、恢复与交付 |
| 通用记忆 | `memory/` | 安装环境、DRAW 作用域、拓扑与单位经验 |
| 任务记忆 | `.occ-harness/sessions/<id>/memory.json` | 参数、目标、实体名及已验证事实，跨进程保存 |
| 原生模块 | `native/occ_agent.cpp` → `bin/occ_agent.dll` | Tcl 执行、BRep 检查与测量、边面枚举、选取、格式转换 |
| 本地运行层 | `occ_harness/`、`runtime/` | 命名会话、客户端锁、认证、历史、超时、CLI/MCP |
| 样例与测试 | `examples/`、`tests/` | 实际建模、直接编辑与真实内核验证 |

```text
gpt-6-luna + skill + task memory
               ↓ CLI or MCP
Python session client → authenticated loopback socket
               ↓
DRAWEXE -b -f server.tcl → occ_agent.dll → OCCT 7.7 BRep
```

启动时复用 `draw.bat` 所调用的 **同一 env.bat**，加载 MODELING 和自定义插件。官方 draw.bat 不转发 Tcl 参数，因此运行层直接启动该环境中的 DRAWEXE。原安装目录及启动文件未修改。

全部 DRAW Tcl 均可执行，不受预定义建模操作限制；`set`、`expr`、`foreach`、过程、原生布尔与圆角命令直接使用。几何协议另外提供结构化 inspect、topology/select，以及 STEP/BREP/STL 输出。STEP/BREP 支持导入；STL 导入、交互视窗、截图及 OCAF 历史不是当前接口的内置功能。可按需用 Tcl 加载额外 DRAW 插件。

## 直接编辑闭环（v0.3）

原件、选面、位移和明确的编辑规则是输入；孔参数、扩展范围和切削工具由运行过程计算。保留原生 Tcl 入口，新增五个结构化操作：

| 操作 / MCP 工具 | 输出 |
|---|---|
| `surface_info` / `occ_surface_info` | 世界坐标曲面参数、轴向/半径/锥角、UV 范围、wire 引用、几何面积/容差、revision |
| `patch_context` / `occ_patch_context` | 有界局部邻接、共享边、解析曲面关系、是否截断 |
| `expand_selection` / `occ_expand_selection` | 同轴孔候选范围、边界面、逐面扩展理由和测得的分段孔轮廓 |
| `edit_candidate` / `occ_edit_candidate` | 独立 BRep 分支、补孔/建工具/原位校准/移动重切、验收及 STEP 往返 |
| `validate_edit` / `occ_validate_edit` | 目标面覆盖/支撑面映射、邻接、核心截面、完整孔体为空、影响范围外边界保留、新支撑面、严格有效性和容差增长 |

面引用必须绑定 `(shape, revision, face_index)`。revision 排除显示网格和内部缓存标记，不是密码学哈希；修改几何或拓扑后重新查询。inspect 的面积、体积和长度也已禁止使用显示三角网格。

policy 必须明确 `target_mode`（有限面片完整保留或支撑曲面移动后重裁剪）、`allow_breakthrough` 和 `allow_new_supports`。`ok=true` 表示操作完成，`data.accepted` 才表示声明的检查通过；执行失败、约束失败和证据不足分别保留。截面检查只覆盖识别出的解析孔核心，不证明全局设计正确。

内置配方当前支持连通的 inward 圆柱/圆锥孔壁和环形台阶，要求圆柱端部、原件孔体为空、核心整圆截面，且原位重建必须与原件双向布尔差为空；自由曲面孔壁、开放扇区、混合轴线或复杂轴向轮廓明确返回不支持。一般形状仍可用 Tcl 建模并获取独立诊断；自动验收当前要求可验证的同轴孔影响范围。原始实体不被替换；分支、manifest、操作证据和 task memory 保存在被忽略的 `.occ-harness/sessions/<session>/edits/<id>/`。

```powershell
# 仅从原件与两面选择重建四个独立 case；输出目录须为空。
python examples/run_direct_edit_cases.py --case examples/cases/part05_hole_moves.json --output .occ-harness/raw-part05-run
```

此脚本是确定性 harness 回归，不调用模型 API，也不代表 Luna 的自主成功率。完整接口、阈值和恢复说明见 [直接编辑 skill](skills/occ-draw/references/direct-edit.md)。

本次回归摘要见 [真实原件验证](artifacts/validation/direct_edit_v03.json)，独立模型检查见 [3 个 Luna 的复核记录](artifacts/validation/luna_reviews_v03.md)。其中旧 case03 是开放圆柱扇区，当前整孔配方会提前拒绝；不把它计入自动建模成功。

## BRep 拓扑关系图

`topology_graph` 操作返回 `nodes`、`uses`、`edge_faces` 和 `vertex_edges`，包含共享边、方向、局部/累积 Location、重复引用及非流形邻接。图节点按 TShape + 累积 Location 去重，`node.type_index` 对应现有 select 索引，图 ID 仅适用于当前快照。

```powershell
.\occ-harness.ps1 topology_graph part block_v1
.\occ-harness.ps1 topology_graph part block_v1 --output C:/Projects/occ-harness/artifacts/graph.json
```

MCP 为 `occ_topology_graph(session,shape,path?,overwrite?)`；Tcl 为 `ah_topology_graph shape [absolute-json-path]`。内联上限 3 MiB，文件方式返回摘要并写入完整 UTF-8 JSON，不受传输的 4 MiB 上限限制。字段及 seam/实例语义见 [关系图接口说明](skills/occ-draw/references/topology-graph.md)。升级 DLL 后需保存检查点并重启已有会话。

## 会话与恢复

### 交互选面

`python examples/launch_benchmark_picker.py --initial 3` 会启动原安装的 `draw.bat`，通过其 `CSF_DrawAppliInit` 扩展点加载图形选面面板。默认读取 toStudent_EM_top10 的 manifest，也可传 `--manifest`。面板可切换零件、按面选择并记录；当前选择在 `current_selection.json`，正式选择在 `selections.jsonl`。

记录保存同一会话中的面索引、源 STEP SHA256、完整零件 BREP 快照和实际面 BREP。窗口拾取与 native 索引使用同一 TopExp 去重顺序；后续以冻结的 BREP 和面几何复核，不能套用其他软件或重新导入 STEP 后的面号。启动验证数据写入独立的 validation 子目录，不作为用户选面。

GUI 会话仍支持 RPC。它复用 DRAW 自己的 Tcl/Tk 事件循环，批处理会话继续使用独立事件循环。

零件选择使用可滚动列表：单击条目后点“载入所选零件”，或直接双击条目。此界面使用 `pack` 布局，避开 DRAW 的全局 `grid` 命令覆盖 Tk 同名命令、导致 ttk 下拉弹窗异常的问题。

“清空当前选择”只取消高亮，保留本 case 已保存的面。“开始下一个 case”清空选择和当前列表，切换到独立的 `cases/case_0002` 等记录目录；旧记录、面 BREP 和零件快照仍保留。新 case 可以重复选择相同的面，不会被上一轮的去重状态跳过。`.occ-harness/latest_benchmark_picker.json` 指向当前 case 的记录目录。

阶梯孔移动的四方向样例见 [选面 case 0002](artifacts/benchmarks/case02_part05_move_xz3/README.md)。`examples/relocate_hole_benchmark.py --package <样例目录>` 从已准备的填孔体、阶梯孔工具和参数独立生成 X/Z ±3 mm 候选；`--audit-existing` 只复核已有候选的核心截面。它是该样例的复现实验，还没有实现通用孔特征识别或自动选面扩展。

样例分别记录常规实体有效性、支撑面邻接、核心截面、原面片覆盖和 STEP 往返结果。允许外形重裁剪不代表允许孔穿透外壁；应按任务语义解释这些指标。重放生成的 `replayed.brep` 不纳入版本控制。

### 持久会话

CLI 退出后 DRAW 会话继续存在，同名 start 会重用活会话。`context` 返回存活状态、任务记忆、最近六条操作摘要和检查点列表；完整输入/输出在 `history.jsonl`，DRAW 诊断在 `draw.log`。不同会话彼此隔离，同一会话的 CLI/MCP 调用通过文件锁串行执行。

`checkpoint part before_edit shape_a shape_b` 将选定实体保存为 BREP，并记录任务记忆快照；`restore part before_edit` 覆盖这些名字的几何。恢复不会删除其他实体、恢复 Tcl 变量/过程或覆盖当前任务记忆。停止后重新 start，再 restore 即可继续实体编辑。

Tcl 错误不会回滚已完成的命令。一些 DRAW 算法失败时仍返回 Tcl 成功，必须检查输出实体和尺寸/体积；建议使用新结果名防止把旧实体当成新结果。默认 RPC 截止时间 30 秒，超时或传输断开会终止身份匹配的 DRAW 进程、标记会话 invalid，记录结果状态未知，不自动重试或重放。

这是受信任的本地 Tcl 执行环境，具备当前用户权限；回环地址与随机 token 用于连接认证，并非 Tcl 沙箱。不要提交 `.occ-harness/`。默认输出不会覆盖已有文件，须显式 `--overwrite`。STL 不保存单位，STEP/BREP 往返仍应核对几何。

## 构建与验证

需要 Windows x64、MSVC 2022、CMake 3.20+、Python 3.10+，以及安装中的 OCCT/Tcl/RapidJSON SDK。运行不需要额外 pip 包。入口自动寻找 Python，也可设置 `OCC_HARNESS_PYTHON`。OCCT 路径在 `harness.json`；运行时可用 `OCC_HARNESS_OCCT_ROOT` 覆盖。

```powershell
.\scripts\build.ps1
# 自定义 SDK：.\scripts\build.ps1 -OcctRoot C:/path/to/opencascade-7.7.0
python -m unittest discover -s tests -v
python examples/demo.py
```

本机 Python 如未在 PATH，可使用 `C:/Users/oxyfl/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`。

18 项集成测试在真实 DRAW/OCCT 上通过：原有建模、交换、记忆、恢复、并发、超时、MCP/PowerShell 中文传输，以及关系图的共享边、seam、闭合边、实例变换、重合独立实体、根方向、自由边、孤立顶点、非流形邻接、选择索引一致性、中文路径及超过 4 MiB 的图文件。工具链已验证，尚未进行 gpt-6-luna 自主建模成功率评测。

完整演示输出在 [artifacts/demo/report.json](artifacts/demo/report.json)，包含有效的单实体安装板、R3 外角、五个孔及凸台，bbox **100×70×22 mm**，体积 **76232.45521534949 mm³**；同时提供 STEP、BREP、二进制 STL 和 [拓扑关系图 JSON](artifacts/demo/topology_graph.json)。`examples/demo.py` 会明确覆盖自己的演示输出。

## 参考来源

- [OCCT DRAW 官方手册](https://github.com/Open-Cascade-SAS/OCCT/wiki/draw_test_harness)：DRAW Tcl 与 C++ 插件机制；具体接口以本机 7.7.0 SDK 源码为准。
- [OpenAI Skills](https://developers.openai.com/plugins/concepts/skills) 与 [Codex 配置](https://learn.chatgpt.com/docs/config-file/config-reference)：skill 和 MCP 接入。
- [MCP stdio](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)、[工具协议](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)。

本项目不复制 OCCT SDK 或其运行库；运行依赖所指定的本地安装。OCCT 自身许可见该安装中的 LICENSE_LGPL_21.txt 与 OCCT_LGPL_EXCEPTION.txt。
