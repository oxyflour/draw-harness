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

`--state-dir <directory>`、`--timeout <seconds>` 为全局选项，位于子命令前。命令返回 JSON，成功退出码为 0，失败为 1。复杂 Tcl 使用 `exec part --file C:/path/model.tcl --check final_shape`。默认单位约定为 mm。

## 接入 gpt-6-luna

1. 执行 `scripts/install-skill.ps1`，将 `occ-draw` 安装到个人 skills 目录；本次已经安装。仓库的 `AGENTS.md` 也指向同一 skill。
2. 本项目 `.codex/config.toml` 已配置目标模型和本地 MCP 服务。客户端载入项目配置后可发现八个 `occ_*` 工具；其他 MCP 客户端使用 `config/mcp.json.example`。
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

## 会话与恢复

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

11 项集成测试在真实 DRAW/OCCT 上通过：实体与 Tcl 跨调用保留、切孔体积、选边圆角、中文/空格路径的 BREP/STEP/STL 导出及往返、重启恢复、错误后的部分状态、超时停止且不重放、认证与并发、输出限幅、MCP 协议及工具调用、实际 PowerShell MCP 入口的中文传输。工具链已验证，尚未进行 gpt-6-luna 自主建模成功率评测。

完整演示输出在 [artifacts/demo/report.json](artifacts/demo/report.json)，包含有效的单实体安装板、R3 外角、五个孔及凸台，bbox **100×70×22 mm**，体积 **76232.45521534949 mm³**；同时提供 STEP、BREP、二进制 STL。`examples/demo.py` 会明确覆盖自己的演示输出。

## 参考来源

- [OCCT DRAW 官方手册](https://github.com/Open-Cascade-SAS/OCCT/wiki/draw_test_harness)：DRAW Tcl 与 C++ 插件机制；具体接口以本机 7.7.0 SDK 源码为准。
- [OpenAI Skills](https://developers.openai.com/plugins/concepts/skills) 与 [Codex 配置](https://learn.chatgpt.com/docs/config-file/config-reference)：skill 和 MCP 接入。
- [MCP stdio](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)、[工具协议](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)。

本项目不复制 OCCT SDK 或其运行库；运行依赖所指定的本地安装。OCCT 自身许可见该安装中的 LICENSE_LGPL_21.txt 与 OCCT_LGPL_EXCEPTION.txt。
