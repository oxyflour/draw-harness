# DRAW 交互选面

在图形窗口左键点选面，Shift+左键多选。面板显示当前会话中的面号。

点击“记录选中面”保存；切换零件前先记录。也可保留选中状态，在聊天里说“记录”，由 agent 从同一 DRAW 会话读取。

selections.jsonl 为正式选择记录；faces/ 保存每个被选中的实际面 BRep；snapshots/ 保存完整零件 BRep。记录含零件编号、面索引、源 STEP SHA256 和几何检查结果，不依赖外部软件面号。

validation/ 仅为启动时拾取与恢复验证，不属于正式 benchmark 选择。

会话：`benchmark_gui_1793195218695757100`
