# 建模经验

- DRAW 的 BRep 名字依赖当前 Tcl 作用域；RPC 从全局帧进入，eval 同样使用 TCL_EVAL_GLOBAL。局部 procedure 中的形状需要 `global name` 或显式在全局帧创建，才能用于后续调用。
- 布尔结果有时为 compound，但内部含一个 solid。不要把 `type != solid` 当成建模失败，检查唯一 solid 数和体积。
- `ah_inspect` 按几何计算 bbox（不含三角网格和容差膨胀）；volume 仅在有 solid 时计算，否则为 null。bbox 极值可能出现浮点误差，比较时使用容差。
- 用形状几何和中心定位边/面；索引属于该形状当前拓扑的 1-based MapShapes 顺序，后续编辑后不保证稳定。
- 脚本失败不是事务回滚。checkpoint 保存列出的有效 BRep 及当时的任务记忆快照；restore 只恢复几何，返回旧记忆供比较，不覆盖当前记忆。
- 脚本超时会终止对应 DRAW 进程，并标记 invalid；不重放历史。新会话需要明确 start，再 restore 已保存检查点。
- STEP 导入可能改变拓扑结构或层次；往返验证应比较有效性、实体数、尺寸和体积。
- 模型尺寸遵循 mm 约定，OCCT 原始数值本身无单位；与外部格式交换时必须核对单位。STL 不携带单位。
