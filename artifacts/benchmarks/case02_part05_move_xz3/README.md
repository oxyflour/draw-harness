# 选面 case 0002：05 号件的阶梯孔沿 X/Z 平移 ±3 mm

用户原选面：8、317。沿同一孔的邻接关系扩展为 6、7、8、317、318、319、320，共 7 面。
扩展包括外径圆柱壁、环形台阶、锥面及内径圆柱壁；邻接外表面 30、83、84 保持原支撑曲面，由布尔运算重新裁剪。
四个 case 均从同一原件独立开始。先补旧孔，再平移完整阶梯孔工具重切；原位置重建的双向布尔差为空（OCCT 容差内）。
candidate.stp / candidate.brep 是候选实体；expanded_targets.step 是刚性平移后的 7 个参考面，后者不是实体答案。

| Case | 常规有效单实体 | 台阶连接完整 | 7 个裁剪面完整保留 | STEP 往返 |
|---|---|---|---|---|
| [x_minus3](x_minus3/candidate.stp) | True | True | False | True |
| [x_plus3](x_plus3/candidate.stp) | True | True | False | True |
| [z_minus3](z_minus3/candidate.stp) | True | False | False | False |
| [z_plus3](z_plus3/candidate.stp) | True | False | False | True |

“台阶连接完整”要求有效单实体、外孔→台阶→锥面→内孔邻接链，以及台阶两侧和锥面中部的整圆截面均保留。它只检查孔的核心连接，不证明出口范围或全局质量。
原孔壁中部的平移截面另存 representative_circular_sections，仅用于比较裁剪变化，不作为核心连接的通过条件。
X−3 mm 的台阶仍连接完整，内孔出口被外形重新裁短；X+3 mm 的原始代表截面均保留。Z±3 mm 均与外壁相交，局部孔壁变为开口。
“7 个裁剪面完整保留”要求原有有限面片平移后仍完整存在；邻接面重新裁剪会改变面片范围。X 方向外圆柱面面积覆盖接近 100%，仍按固定的严格阈值报告。
Z−3 mm 的 STEP 导回后仍是常规有效单实体，但体积相对差约 85 ppm，超过 10 ppm 阈值；双向布尔差均为空（OCCT 容差内）。体积门槛保留为未通过，详见 report.json 和 roundtrip_boolean_*.json。
源件和每个结果的 checkshape -exact 均有缺陷，单列于 report.json；普通有效性通过不能替代严格检查。

复现：在 DRAW 中 source -encoding utf-8 各 case 的 replay.tcl。input/prepare.tcl 记录从原件生成共用填孔体和工具的流程。
准备流程和四个 case 已在独立无界面会话重放；验证见 diagnostics/preparation_replay.json 和各 case 的 replay_verification.json。
查看：在已启用图形界面的 DRAW 中 source -encoding utf-8 本目录 review.tcl；金色为结果，青色线框为平移参考面。

重新生成候选：python examples/relocate_hole_benchmark.py --package <本目录>。
只复核现有候选的台阶连接截面：加 --audit-existing；不会重写几何。
