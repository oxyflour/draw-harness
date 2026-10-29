# 建模经验

- DRAW 的 BRep 名字依赖当前 Tcl 作用域；RPC 从全局帧进入，eval 同样使用 TCL_EVAL_GLOBAL。局部 procedure 中的形状需要 `global name` 或显式在全局帧创建，才能用于后续调用。
- 布尔结果有时为 compound，但内部含一个 solid。不要把 `type != solid` 当成建模失败，检查唯一 solid 数和体积。
- `ah_inspect` 按几何计算 bbox（不含三角网格和容差膨胀）；volume 仅在有 solid 时计算，否则为 null。bbox 极值可能出现浮点误差，比较时使用容差。
- 用形状几何和中心定位边/面；索引属于该形状当前拓扑的 1-based MapShapes 顺序，后续编辑后不保证稳定。
- topology_graph 的节点按 TShape + 累积 Location 去重；definition_id 仅标记 TShape，uses 保留相对方向/Location 与重复引用。图 ID 不能直接用于 select，应使用 node.type_index。圆柱 seam 和闭合 edge 的重复引用不可丢弃；edge_faces 是唯一祖先列表，非流形边可超过两个面。
- 脚本失败不是事务回滚。checkpoint 保存列出的有效 BRep 及当时的任务记忆快照；restore 只恢复几何，返回旧记忆供比较，不覆盖当前记忆。
- 脚本超时会终止对应 DRAW 进程，并标记 invalid；不重放历史。新会话需要明确 start，再 restore 已保存检查点。
- STEP 导入可能改变拓扑结构或层次；往返验证应比较有效性、实体数、尺寸和体积。
- 模型尺寸遵循 mm 约定，OCCT 原始数值本身无单位；与外部格式交换时必须核对单位。STL 不携带单位。
- 此安装的 OCCT 7.7 `tcopy` 多输入输出对存在循环下标问题，可能覆盖后续输入；每次只传一对 `tcopy source destination`，并检查输出。安装源码 `BRepTest_BasicCommands.cxx` 的循环使用 `a[i+iFirst]`，没有按两倍步长读取。
- Windows DRAW 的默认 source 编码不一定是 UTF-8；读取含中文的脚本时使用 `source -encoding utf-8 /absolute/path/script.tcl`，否则可能出现乱码或误报缺少括号。
- 面移动的基线不能只检查实体有效性；还要检查刚性变换后的完整目标面在结果边界上的覆盖面积，以及原位置面是否消失。扫掠布尔可能产生有效实体，但目标面因外壁穿透被裁短或完全消失。若允许新增直纹连接面，须在 case 中注明该语义，不能当成只延伸/重裁既有邻接曲面的算法。
- 解析扫掠工具触发 PCurve 构造失败时，可以尝试仅将工具 `nurbsconvert` 后重做布尔；这是需要重新验证的回退，不保证所有模型都成功。保留失败响应并使用新输出名或确认旧输出不存在。
- 普通常规 BRepCheck 与 `checkshape -exact` 的结论可能不同。对导入模型同时记录输入与输出的严格检查缺陷；缺陷数量不增长不能证明缺陷身份完全相同。
- 当前 inspect 面积/体积实现启用了 UseTriangulation；显示模型后生成的三角网格会改变这些数值。基准几何测量应在独立的、尚未显示模型的会话中进行，显示对象仅用于查看。
