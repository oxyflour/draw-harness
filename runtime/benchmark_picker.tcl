# Loaded by the existing DRAW DrawAppliInit hook. Configuration comes from launcher.
pload VISUALIZATION
namespace eval ::bench {
    variable current 0
    variable chosen ""
    variable status "请选择零件并载入。"
    variable selectedText "当前选中：无"
    variable busy 0
    variable loaded [dict create]
    variable recorded [dict create]
    variable lastLive ""
    variable testMode 0
}
proc ::bench::globalcmd {args} {uplevel #0 $args}
proc ::bench::quote {value} {
    return "\"[string map [list \\ \\\\ \" \\\" \n \\n \r \\r \t \\t] $value]\""
}
proc ::bench::rpc {fields} {
    set result [uplevel #0 [list ah_rpc "{\"token\":\"gui-local\",$fields}" gui-local]]
    if {![regexp {^\{"ok":true,} $result]} {error $result}
    return $result
}
proc ::bench::writeFile {path content} {
    set file [open "$path.tmp" w]
    fconfigure $file -encoding utf-8 -translation lf
    puts $file $content
    close $file
    file rename -force "$path.tmp" $path
}
proc ::bench::faces {} {
    variable current
    if {$current == 0} {return {}}
    set parent ""
    set result {}
    foreach line [split [vstate] \n] {
        if {[regexp {^Locally selected sub-shapes within ([A-Za-z0-9_]+):$} $line -> name]} {
            set parent $name
        } elseif {$parent eq [format "part_%02d" $current] && [regexp {^\s*Face\s+#([0-9]+)} $line -> index]} {
            lappend result $index
        }
    }
    return [lsort -integer -unique $result]
}
proc ::bench::poll {} {
    variable current
    variable busy
    variable selectedText
    variable lastLive
    variable output
    if {!$busy && $current != 0} {
        if {![catch {::bench::faces} faces]} {
            set selectedText [expr {[llength $faces] ? "当前选中：[join $faces {, }]" : "当前选中：无"}]
            set live "{\"case\":$current,\"shape\":[::bench::quote [format part_%02d $current]],\"face_indices\":\[[join $faces ,]\]}"
            if {$live ne $lastLive} {
                ::bench::writeFile [file join $output current_selection.json] $live
                set lastLive $live
            }
        }
    }
    if {[winfo exists .benchmark]} {after 350 ::bench::poll}
}
proc ::bench::loadCase {{rank ""}} {
    variable chosen
    variable cases
    variable output
    variable current
    variable loaded
    variable busy
    variable status
    if {$busy} {return}
    if {$rank eq ""} {set rank [lindex [split $chosen |] 0]; scan $rank %d rank}
    set busy 1
    set status [format "正在载入 %02d 号，请稍候……" $rank]
    update idletasks
    set code [catch {
        set item [dict get $cases $rank]
        set shape [format "part_%02d" $rank]
        if {![dict exists $loaded $rank]} {
            ::bench::rpc "\"op\":\"import\",\"shape\":[::bench::quote $shape],\"path\":[::bench::quote [dict get $item path]],\"format\":\"step\""
            set snapshot [file join $output snapshots "$shape.brep"]
            ::bench::rpc "\"op\":\"export\",\"shape\":[::bench::quote $shape],\"path\":[::bench::quote $snapshot],\"format\":\"brep\""
            dict set loaded $rank $snapshot
        }
        ::bench::globalcmd vactivate $::bench::viewer
        ::bench::globalcmd vclear
        ::bench::globalcmd vdisplay -dispMode 1 $shape
        ::bench::globalcmd vselmode $shape Face on -set
        ::bench::globalcmd vaxo
        ::bench::globalcmd vfit
        set current $rank
        set status [format "%02d 号已载入（%d 面）。点选面后点击“记录选中面”。" $rank [dict get $item faces]]
        ::bench::writeFile [file join $output loaded.json] "{\"case\":$rank,\"shape\":[::bench::quote $shape],\"snapshot\":[::bench::quote [dict get $loaded $rank]]}"
    } message]
    set busy 0
    if {$code} {set status "载入失败：$message"; error $message}
}
proc ::bench::record {} {
    variable current
    variable cases
    variable output
    variable loaded
    variable recorded
    variable status
    variable busy
    variable testMode
    variable selectionCase
    if {$busy} {return}
    set faces [::bench::faces]
    if {![llength $faces]} {set status "尚未选中面，请先在图形窗口点选。"; return}
    set busy 1
    set code [catch {
        set target [expr {$testMode ? [file join $output validation] : $output}]
        file mkdir [file join $target faces]
        set shape [format "part_%02d" $current]
        set item [dict get $cases $current]
        foreach index $faces {
            set id [format "case%02d_face%04d" $current $index]
            if {[dict exists $recorded "$testMode:$id"]} {continue}
            set inspection [::bench::rpc "\"op\":\"select\",\"shape\":[::bench::quote $shape],\"type\":\"face\",\"index\":$index,\"name\":[::bench::quote $id]"]
            set path [file join $target faces "$id.brep"]
            set exported [::bench::rpc "\"op\":\"export\",\"shape\":[::bench::quote $id],\"path\":[::bench::quote $path],\"format\":\"brep\""]
            set json "{\"id\":[::bench::quote $id],\"selection_case\":$selectionCase,\"case\":$current,\"face_index\":$index,\"shape\":[::bench::quote $shape],\"source_step\":[::bench::quote [dict get $item path]],\"source_sha256\":[::bench::quote [dict get $item sha256]],\"part_snapshot\":[::bench::quote [dict get $loaded $current]],\"face_brep\":[::bench::quote $path],\"inspection_rpc\":$inspection,\"export_rpc\":$exported}"
            set file [open [file join $target selections.jsonl] a]
            fconfigure $file -encoding utf-8 -translation lf
            puts $file $json
            close $file
            dict set recorded "$testMode:$id" 1
            if {!$testMode} {.benchmark.list insert end "$id  （已保存面 BRep）"}
        }
        set status "已记录：[join $faces {, }]。可以继续选面或切换零件。"
    } message options]
    set busy 0
    if {$code} {set status "记录失败：$message"; return -options $options $message}
}
proc ::bench::safeLoad {} {catch {::bench::loadCase}}
proc ::bench::safeRecord {} {catch {::bench::record}}
source -encoding utf-8 [file join [file dirname [info script]] benchmark_cases.tcl]
source -encoding utf-8 [file join [file dirname [info script]] benchmark_parts.tcl]

toplevel .benchmark
wm title .benchmark "Benchmark 选面记录 — OCCT DRAW"
wm geometry .benchmark 540x650+25+50
ttk::label .benchmark.title -text "toStudent_EM · 面选择" -font {SegoeUI 16 bold}
ttk::label .benchmark.help -text "1. 选择零件并载入。\n2. 左键点选面，Shift+左键可多选。\n3. 点击“记录选中面”，再切换零件。\n滚轮缩放；鼠标拖动旋转；F 可适配视图。" -justify left
ttk::button .benchmark.load -text "载入零件" -command ::bench::safeLoad
ttk::label .benchmark.selected -textvariable ::bench::selectedText -wraplength 500
ttk::button .benchmark.record -text "记录选中面" -command ::bench::safeRecord
ttk::label .benchmark.status -textvariable ::bench::status -wraplength 500
listbox .benchmark.list -height 8 -width 65
ttk::label .benchmark.path -text "记录目录：$::bench::output" -wraplength 500
foreach child {title help load selected record status list path} {pack .benchmark.$child -anchor w -padx 16 -pady 7 -fill x}
bind .benchmark <F5> ::bench::safeRecord
set ::bench::viewer [string trim [vinit -name BenchmarkPick -left 580 -top 50 -width 680 -height 650]]
::bench::installCaseControls
::bench::installPartSelector
::bench::writeFile $::env(OCC_GUI_INFO) "{\"pid\":[pid],\"output\":[::bench::quote $::bench::output]}"
after 350 ::bench::poll
after 500 ::bench::safeLoad
