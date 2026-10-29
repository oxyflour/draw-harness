# Run in DRAW: source /absolute/path/to/replay.tcl
pload MODELING
set here [file dirname [file normalize [info script]]]
restore [file join $here .. input part_03.brep] base
explode base F
boptions -default
bnondestructive 1
tcopy base_6 target_6
ttranslate target_6 -3 0 0
prism swept_6 base_6 -3 0 0
tcopy base_727 target_727
ttranslate target_727 -3 0 0
prism swept_727 base_727 -3 0 0
bfuse tool swept_6 swept_727
# Analytic tool fails PCurve construction for the negative case.
nurbsconvert tool_nurbs tool
bcut result base tool_nurbs
checkshape result
save result [file join $here replayed.brep]
