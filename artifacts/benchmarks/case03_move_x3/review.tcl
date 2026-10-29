# Run in interactive DRAW: source -encoding utf-8 /absolute/path/to/review.tcl
pload VISUALIZATION
namespace eval ::movebench {
    variable root [file dirname [file normalize [info script]]]
    variable view Driver1/MoveCases/FaceMove
    variable mode plus
    variable overlay 1
    variable shown {}
    variable status {}
    variable shapes [dict create original review_move_original plus review_move_plus minus review_move_minus]
}
restore [file join $::movebench::root input part_03.brep] review_move_original
restore [file join $::movebench::root plus_x3 candidate.brep] review_move_plus
restore [file join $::movebench::root minus_x3 candidate.brep] review_move_minus
foreach {tag folder} {plus plus_x3 minus minus_x3} {
    foreach i {6 727} {
        restore [file join $::movebench::root $folder target_face_$i.brep] review_target_${tag}_$i
    }
    compound review_target_${tag}_6 review_target_${tag}_727 review_targets_$tag
}
proc ::movebench::draw {args} {uplevel #0 $args}
proc ::movebench::show {which} {
    variable mode
    variable shapes
    variable view
    variable overlay
    variable status
    variable shown
    set mode $which
    ::movebench::draw vactivate $view
    foreach object $shown {
        catch {::movebench::draw verase -noupdate $object}
    }
    set object [dict get $shapes $which]
    ::movebench::draw vdisplay -dispMode 1 $object
    ::movebench::draw vsetcolor $object GOLDENROD
    set shown [list $object]
    if {$overlay && $which ne "original"} {
        ::movebench::draw vdisplay -dispMode 0 review_targets_$which
        ::movebench::draw vsetcolor review_targets_$which CYAN
        lappend shown review_targets_$which
    }
    ::movebench::draw vviewparams -eye -5 -120 16 -at -3 -84 0.16 -up 0 0 1 -size 20
    ::movebench::draw vzbufftrihedron
    set status [dict get [dict create original {原件：已记录面 6、727。} plus {+3 mm：两个目标面完整保留，新增过渡侧壁。} minus {-3 mm：槽口切穿；面 6 仅保留约 0.36%，面 727 消失。}] $which]
}
vinit -name $::movebench::view -left 580 -top 50 -width 680 -height 650
catch {destroy .movebench}
toplevel .movebench
wm title .movebench {面移动 benchmark：原件 / +3 mm / -3 mm}
wm geometry .movebench 540x460+25+50
ttk::label .movebench.title -text {Case 03 · 面 6、727 同时沿 X 移动} -font {SegoeUI 15 bold}
ttk::button .movebench.original -text {显示原件} -command {::movebench::show original}
ttk::button .movebench.plus -text {显示 +3 mm} -command {::movebench::show plus}
ttk::button .movebench.minus -text {显示 -3 mm} -command {::movebench::show minus}
ttk::checkbutton .movebench.overlay -text {显示目标面线框（青色）} -variable ::movebench::overlay -command {::movebench::show $::movebench::mode}
ttk::label .movebench.status -textvariable ::movebench::status -wraplength 500
ttk::label .movebench.note -text {这是允许新增侧壁的扫掠布尔基线。两个结果常规检查有效；原件和结果的严格检查均有缺陷，详见报告。} -wraplength 500
ttk::button .movebench.back -text {返回原来的选面窗口} -command {vactivate Driver1/Viewer1/BenchmarkCompact; catch {raise .benchmark}}
foreach child {title original plus minus overlay status note back} {
    pack .movebench.$child -padx 16 -pady 8 -anchor w -fill x
}
::movebench::show plus
