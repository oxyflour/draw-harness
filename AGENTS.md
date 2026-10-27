本仓库是 OCCT DRAW 建模 agent harness，目标模型为 gpt-6-luna。

处理建模任务时读取 `skills/occ-draw/SKILL.md`；运行本地 `occ-harness.ps1`。环境事实在 `memory/environment.md`，建模经验在 `memory/modeling.md`。任务事实用 `memory` 命令保存，不把动态实体名或拓扑索引写入通用 skill。

修改原生代码后运行 `scripts/build.ps1`；修改运行协议后运行真实 SDK 集成测试：`python -m unittest discover -s tests -v`。Python 入口支持 `OCC_HARNESS_PYTHON`，无额外 pip 依赖。不要提交 `.occ-harness` 内的 token 和日志。
