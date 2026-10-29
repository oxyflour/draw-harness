# Rebuild the shared inputs from the immutable original part.
pload MODELING
set here [file dirname [file normalize [info script]]]
restore [file join $here part_05.brep] base
explode base F
boptions -default
bnondestructive 1
removefeatures healed base base_6 base_7 base_8 base_317 base_318 base_319 base_320
bcut plug healed base
bfuse filled base plug
checkshape filled
save filled [file join $here filled_part.brep]
pcylinder bore_outer 0.98824000000000001 1.8366791244525444
trotate bore_outer 0 0 0 1 0 0 -90
ttranslate bore_outer -10.16315 -86.440995443832549 0.16377677858600001
pcone bore_taper 0.89839999999999998 0.75802499999999995 0.24313663211000858
trotate bore_taper 0 0 0 1 0 0 -90
ttranslate bore_taper -10.16315 -84.604316319380004 0.16377677858600001
pcylinder bore_inner 0.75802499999999995 6.6806884678964735
trotate bore_inner 0 0 0 1 0 0 -90
ttranslate bore_inner -10.16315 -84.361179687269995 0.16377677858600001
bfuse bore_stage bore_outer bore_taper
bfuse hole_tool bore_stage bore_inner
checkshape hole_tool
save hole_tool [file join $here hole_tool.brep]
