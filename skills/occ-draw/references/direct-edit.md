# 直接编辑：观察、扩展、执行、验收

## 形状与选面引用

`occ_inspect` 和 `occ_surface_info` 返回 `revision`。面引用是 `(shape, revision, face_index)`，不是永久拓扑 ID。revision 是排除三角网格后的 BRep 内容版本标记，不是密码学文件哈希；交换文件另用 SHA256。曲面参数与轴线均已应用 Location，单位仍按 mm 约定。

`occ_surface_info(shape, faces?)` 查询指定面，或用 offset/limit 分页。响应包含解析曲面参数、inward_wall、UV 范围、几何面积、容差以及每条 wire 的 edge_uses；seam 的重复引用保留。普通 inspect 的面积、长度和体积也不再使用显示三角网格。

`occ_patch_context(shape, faces, expected_revision, depth?, max_faces?)` 只展开局部邻接。响应 `truncated=true` 时不能把未返回的面当作不存在。图边引用的是原件 edge 类型索引；完整图仍用 topology_graph。

## 编辑意图

在执行前固定 policy，按用户目标设置：

- `target_mode=trimmed_patch`：平移后的有限面片应完整保留。
- `target_mode=support_geometry`：支撑曲面移动到位，允许外形重新裁剪有限面片。
- `allow_breakthrough`：是否允许孔的核心台阶截面不完整。false 时，无法识别特征或验收范围不足会返回 inconclusive，不能自动接受。
- `allow_new_supports`：是否允许结果出现无法映射回原支撑曲面或移动支撑曲面的面。true 也不代表其他检查自动通过。
- `require_exact`：是否要求候选通过 checkshape exact 方法；默认 false，输入与候选的严格检查结论均单独保留。

前三项必填。默认 linear_tolerance=1e-6、area_relative_tolerance=1e-5、max_tolerance_growth=1e-5、relative_volume_tolerance=1e-5。容差单位为模型单位；面积/体积阈值为相对值。不得为得到通过而悄悄放宽 policy。

## 同轴孔配方

`occ_expand_selection(shape, faces, expected_revision)` 从 inward 的解析圆柱/圆锥面出发，沿共享边扩展同轴孔壁，并跨过仅与这些孔壁相邻的环形平面台阶。返回 expanded_faces、boundary_faces、逐面理由和测得的 tool_segments/core_sections。

识别器当前支持连通的分段线性轴向孔轮廓，要求两端是圆柱。它还检查推断的完整孔体与原件无实体交集，以及原件核心截面是否整圆；仅有半圈孔壁、开放扇区或盲孔不会按完整通孔配方继续。它不声称通用特征识别；自由曲面孔壁、断开的选面、混合轴线、轴向重叠轮廓会明确拒绝。扩展结果是算法建议，保留原始用户选面与自动扩展面的区别。

`occ_edit_candidate(shape, faces, vector, policy, expected_revision)` 持有整个工作流的会话锁，分配新名字，在 `sessions/<session>/edits/<id>` 保存分支：

1. 保存原始 BRep，再独立导入，不覆盖原实体。
2. 根据识别结果执行 removefeatures，取补回的孔体与原件融合。
3. 根据测得轮廓用 DRAW pcylinder/pcone 建工具，旋转到实际轴向。
4. 在位移为零时重切，要求与原件的双向布尔差均为空。这一步用于拒绝不适用的补孔/穿孔假设。
5. 移动工具并重切，检查新实体，调用独立 native 验收器。
6. 导出 BREP/STEP 并导回 STEP，检查有效性、唯一 solid 数和体积差；保存 manifest、操作证据和 task memory。

每次 DRAW 输出必须有新名字且实际存在。配方不自动提高容差、不隐藏切换 NURBS 工具、不重放超时操作。失败时保留分支和阶段信息；原始实体继续保留。它是几何分支隔离，不是 Tcl 沙箱，也不会回滚会话中新增的名字或全局 Tcl 选项。

## 独立验收

`occ_validate_edit(source, candidate, faces, vector, policy, source_revision, candidate_revision)` 返回：

- 每个目标面与结果边界的面积覆盖、候选支撑面映射。
- 原选面内部的共享边关系是否延续，允许半圆柱合并成一个面。
- 台阶两侧、锥段内部的整圆截面，以及环形台阶的完整面积。
- 候选与整段移动孔体的实体交集必须为空，避免短盲孔仅凭中间整圆截面冒充通孔；端部圆柱工具会延长覆盖原件与候选的边界范围。
- 原孔体与移动孔体并集以外的边界必须双向保留；这会检测无关孔被填平、增加远处空腔或删除无关外形。
- 新增/未分类支撑面、最大容差增长、常规有效性和严格有效性。

核心截面以内部台阶定位，不用原外孔/内孔出口中部作为完整性的唯一依据。截面和邻接检查的范围有限，不证明整个孔或全局设计正确。一般 B 样条面先比较世界坐标支撑面数据，必要时比较候选完整面片与原未裁剪支撑面的交集面积；无法确认的面保留为未分类。

`ok=true` 表示验收计算已执行；`data.accepted` 才是当前 policy 下的判断。`policy_checks_failed` 是约束未满足，`inconclusive` 是证据范围不足；执行失败不等于几何要求不可能实现。自动接受目前要求有可验证的同轴孔影响范围；其他类型仍返回面片/邻接等诊断，不能据此声称获得通用直接编辑证明。单独调用此工具不执行 STEP 往返，编辑工作流会额外执行该检查。

## CLI 与恢复

新增 MCP 工具尚未刷新时，使用仓库入口的同名子命令：surface_info、patch_context、expand_selection、edit_candidate、validate_edit。CLI 用 `--faces`、`--expected-revision`、`--vector`；policy 从 `--policy` 的 JSON 文件读取。validate_edit 使用 `--source-revision` 与 `--candidate-revision`。

复杂原件可显式使用 `--timeout 180`。超时会使会话失效，先查看保存的 manifest；按用户意图明确启动新会话、导入分支原件或恢复 checkpoint，然后换策略。不要自动重试同一耗时命令。

## 独立复核输入

评测或复核给模型的输入限定为原始 BRep、所选面引用、位移和 policy。工具、扩展面和孔参数由模型通过 harness 获取或在执行中生成。验收器和参考答案独立保存，统计接受率、正确拒绝、执行失败、耗时与工具调用量。已有已求解包仅能证明可复现，不代表模型能独立处理新模型。
