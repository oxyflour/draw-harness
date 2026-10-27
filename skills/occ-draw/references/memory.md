# 运行记忆

当前安装的环境与已验证经验保存在 harness 项目的 `memory/environment.md` 和 `memory/modeling.md`；通过 `location.json.project_root` 或仓库 skill 目录定位项目。只有诊断或新建会话时需要读取这些文件。

每个任务的持久记忆通过 `memory` / `occ_memory` 读写，随 session 保存在 `.occ-harness/sessions/<name>/memory.json`。可保存结构化 JSON；推荐记录单位、主要尺寸、实体名字、最新检查点和交付文件。自动历史在 `history.jsonl`，`context` 只返回最近六条摘要以控制上下文长度。

活会话保留全部 Tcl 与 DRAW 内存状态，CLI 退出不会停止会话。stop 或进程崩溃后，重启仅保留磁盘记忆及检查点，实体需要 restore。不要假设历史已自动重放。
