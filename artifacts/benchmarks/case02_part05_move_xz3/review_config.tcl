set ::holebench::center {-10.16315 -84.8 0.163776778586}
set ::holebench::cases [dict create]
dict set ::holebench::cases original [dict create file "input/part_05.brep" target "input/expanded_patch.brep" label "原件 · 05 号零件" status "用户选择 8、317；扩展到同一个阶梯孔的 7 个面。"]
dict set ::holebench::cases x_minus3 [dict create file "x_minus3/candidate.brep" target "x_minus3/expanded_targets.brep" label "X -3 mm" status "台阶连接完整。内孔出口被外形重新裁短。 核心外孔/锥面/内孔截面：100.0%, 100.0%, 100.0%。"]
dict set ::holebench::cases x_plus3 [dict create file "x_plus3/candidate.brep" target "x_plus3/expanded_targets.brep" label "X +3 mm" status "台阶连接完整。 核心外孔/锥面/内孔截面：100.0%, 100.0%, 100.0%。"]
dict set ::holebench::cases z_minus3 [dict create file "z_minus3/candidate.brep" target "z_minus3/expanded_targets.brep" label "Z -3 mm" status "孔壁与外形相交，台阶整圆检查未通过。 核心外孔/锥面/内孔截面：51.8%, 59.6%, 69.6%。 STEP 导回有效，但体积差约 85 ppm，未通过 10 ppm 门槛。"]
dict set ::holebench::cases z_plus3 [dict create file "z_plus3/candidate.brep" target "z_plus3/expanded_targets.brep" label "Z +3 mm" status "孔壁与外形相交，台阶整圆检查未通过。 核心外孔/锥面/内孔截面：75.8%, 83.3%, 54.2%。"]
