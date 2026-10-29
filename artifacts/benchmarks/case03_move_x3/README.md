# Case 03：面 6、727 同时沿 X 平移 ±3 mm

输入编号以 input/part_03.brep 的冻结快照为准。两个 case 都从原件开始，互不累计。
target_faces.step 是两个独立目标面的参考，不能当作完整实体。candidate.stp / candidate.brep 是扫掠加料/去料基线。
这套基线允许新增直纹过渡面；没有强制保留所有邻接支撑曲面，因此不能替代仅延伸/重裁邻面的直接编辑算法。

| Case | 位移 mm | 常规有效单实体 | 面 6 保留率 | 面 727 保留率 | 完整目标面平移基线 |
|---|---|---|---|---|---|
| [plus_x3](plus_x3/candidate.stp) | +3 | True | 100.000000% | 100.000000% | True |
| [minus_x3](minus_x3/candidate.stp) | -3 | True | 0.359685% | 0.000000% | False |

−3 mm 的去料会打通局部外壁，面 727 消失，面 6 只保留极小一片。有效实体不能被误判为完整保面平移成功。
−3 mm 的解析扫掠工具触发 OCCT 7.7 参数曲线构造失败；转换工具为 NURBS 后得到去料结果。没有放大布尔容差。

严格检查另行报告：原件 370 个 Invalid Curve on Surface、224 个 Unorientable Shape；+3 mm 数量相同，−3 mm 为 364 / 222。
这只是数量比较，不证明所有缺陷身份相同；两个基线均未通过严格检查。普通 BRepCheck、双面边关联及 STEP 往返结果见各 case 的 report.json。

在交互 DRAW 中 `source -encoding utf-8 /absolute/path/to/review.tcl` 可切换原件与两个结果，青色线框表示目标面。

在 DRAW 中 source 各 case 的 replay.tcl 可重建 BREP。Python 重新生成几何与验证报告：

```powershell
python examples/move_face_benchmark.py --selections <selections.jsonl> --output <output-directory>
```

case.json 记录输入散列、面索引、位移和验收约束；attempts.json 保存真实命令及响应；没有将失败的解析布尔操作当作成功。
