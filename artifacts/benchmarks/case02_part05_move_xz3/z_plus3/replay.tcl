pload MODELING
set here [file dirname [file normalize [info script]]]
restore [file join $here .. input filled_part.brep] filled
restore [file join $here .. input hole_tool.brep] tool
boptions -default
bnondestructive 1
ttranslate tool 0 0 3
bcut result filled tool
checkshape result
save result [file join $here replayed.brep]
