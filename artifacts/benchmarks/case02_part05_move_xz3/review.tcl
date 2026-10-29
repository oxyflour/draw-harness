# source -encoding utf-8 /absolute/path/to/review.tcl
pload VISUALIZATION
namespace eval ::holebench {
    variable root [file dirname [file normalize [info script]]]
    variable view Driver1/HoleMoveCases/Case2
    variable mode original
    variable overlay 1
    variable shown {}
    variable loaded [dict create]
    variable status {}
}
source -encoding utf-8 [file join $::holebench::root review_config.tcl]
proc ::holebench::draw {args} {uplevel #0 $args}
proc ::holebench::show {mode} {
    variable cases
    variable root
    variable view
    variable overlay
    variable loaded
    variable shown
    variable status
    variable center
    set ::holebench::mode $mode
    set item [dict get $cases $mode]
    ::holebench::draw vactivate $view
    foreach object $shown {::holebench::draw verase -noupdate $object}
    set object "hole_case2_$mode"
    set target "hole_case2_targets_$mode"
    if {![dict exists $loaded $mode]} {
        ::holebench::draw restore [file join $root [dict get $item file]] $object
        ::holebench::draw restore [file join $root [dict get $item target]] $target
        dict set loaded $mode 1
    }
    ::holebench::draw vdisplay -dispMode 1 $object
    ::holebench::draw vsetcolor $object GOLDENROD
    set shown [list $object]
    if {$overlay} {
        ::holebench::draw vdisplay -dispMode 0 $target
        ::holebench::draw vsetcolor $target CYAN
        lappend shown $target
    }
    lassign $center x y z
    ::holebench::draw vviewparams -eye $x [expr {$y-35}] [expr {$z+7}] -at $x $y $z -up 0 0 1 -size 16
    ::holebench::draw vzbufftrihedron
    set status [dict get $item status]
}
vinit -name $::holebench::view -left 580 -top 50 -width 680 -height 650
catch {destroy .holebench}
toplevel .holebench
wm title .holebench {选面 case 0002 · 05 号阶梯孔 X/Z ±3 mm}
wm geometry .holebench 540x530+25+50
ttk::label .holebench.title -text {阶梯孔移动 · 7 面联动} -font {SegoeUI 16 bold}
pack .holebench.title -padx 16 -pady 10 -fill x
dict for {mode item} $::holebench::cases {
    ttk::button .holebench.$mode -text [dict get $item label] -command [list ::holebench::show $mode]
    pack .holebench.$mode -padx 16 -pady 6 -fill x
}
ttk::checkbutton .holebench.overlay -text {显示目标面线框（青色）} -variable ::holebench::overlay -command {::holebench::show $::holebench::mode}
ttk::label .holebench.status -textvariable ::holebench::status -wraplength 500
ttk::label .holebench.note -text {原选面 8、317；扩展到内孔、锥面、台阶共 7 面。检查细节和输入、输出缺陷见 report.json。} -wraplength 500
ttk::button .holebench.back -text {返回选面窗口} -command {vactivate $::bench::viewer; raise .benchmark}
foreach child {overlay status note back} {pack .holebench.$child -padx 16 -pady 8 -fill x}
::holebench::show original
