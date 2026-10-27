# Millimeters; plate in XY, thickness along +Z, boss centered on the top face.
box base 100 70 10
pcylinder boss 18 12
ttranslate boss 50 35 10
bfuse stock base boss
pcylinder bore 8 30
ttranslate bore 50 35 -2
bcut plate_v0 stock bore
set previous plate_v0
set i 0
foreach {x y} {12 12 88 12 88 58 12 58} {
    incr i
    pcylinder drill_$i 3.5 14
    ttranslate drill_$i $x $y -2
    bcut plate_v$i $previous drill_$i
    set previous plate_v$i
}
puts "Created plate_v4: 100 x 70 x 10; boss diameter 36, height 12; bore diameter 16; four diameter 7 holes."
