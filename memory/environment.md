# 已知环境

- Windows x64，OCCT 7.7.0 SDK 来自 `C:/Programs/OpenCASCADE-7.7.0-vc14-64/opencascade-7.7.0`。
- `draw.bat` 只调用 `env.bat` 并启动 DRAWEXE，不能把 Tcl 文件当参数传给 draw.bat。harness 复用同一个 env.bat，再启动 `DRAWEXE.exe -b -f runtime/server.tcl`。
- 本项目 `bin/occ_agent.dll` 是 MSVC x64 Release 原生 DRAW 插件，通过 `pload -AgentPlugin AGENT` 加载。保持 OCCT/Tcl 位数和 ABI 兼容。
- `harness.json` 的模型默认值是 gpt-6-luna；实际模型由客户端设置，harness 不发送模型 API 请求。
- harness 可从任意项目目录运行；默认状态目录是调用方 cwd 下的 `.occ-harness`，可通过 `--state-dir` 或 `OCC_HARNESS_STATE_DIR` 固定。
- DRAW/Tcl 是受信本地代码执行，不是沙箱。仅回环监听及随机 token 用于防止其他连接误用；token 存于本机 session.json，不应提交或粘贴到报告中。
