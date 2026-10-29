# Selection groups are independent cases; starting another never deletes history.
namespace eval ::bench {
    if {![info exists selectionRoot]} {variable selectionRoot $output}
    if {![info exists selectionCase]} {variable selectionCase 1}
}
proc ::bench::clearSelection {} {
    variable viewer
    variable selectedText
    variable lastLive
    variable status
    variable output
    variable current
    ::bench::globalcmd vactivate $viewer
    # Clear detection, then replace the selection with the empty detected set.
    ::bench::globalcmd vmoveto -reset
    ::bench::globalcmd vselect -replace
    if {[string trim [::bench::globalcmd vnbselected]] ne "0"} {
        error "Could not clear the viewer selection"
    }
    set selectedText "当前选中：无"
    set lastLive ""
    ::bench::writeFile [file join $output current_selection.json] "{\"case\":$current,\"shape\":[::bench::quote [format part_%02d $current]],\"face_indices\":\[\]}"
    set status "当前高亮已清空；本 case 已保存的记录保留。"
}
proc ::bench::newCase {} {
    variable busy
    variable selectionRoot
    variable selectionCase
    variable session
    variable latestPointer
    variable output
    variable current
    variable recorded
    variable lastLive
    variable status
    if {$busy} {return}
    set next [expr {$selectionCase + 1}]
    set directory [file join $selectionRoot cases [format case_%04d $next]]
    while {[file exists $directory]} {
        incr next
        set directory [file join $selectionRoot cases [format case_%04d $next]]
    }
    set previous $output
    file mkdir [file join $directory snapshots]
    if {[file exists [file join $selectionRoot source_manifest.json]]} {
        file copy [file join $selectionRoot source_manifest.json] [file join $directory source_manifest.json]
    }
    set metadata "{\"selection_case\":$next,\"session\":[::bench::quote $session],\"previous_output\":[::bench::quote $previous],\"part_rank\":$current,\"created_utc\":[::bench::quote [clock format [clock seconds] -gmt 1 -format {%Y-%m-%dT%H:%M:%SZ}]]}"
    ::bench::writeFile [file join $directory selection_case.json] $metadata
    ::bench::clearSelection
    set output $directory
    set selectionCase $next
    set recorded [dict create]
    set lastLive ""
    .benchmark.list delete 0 end
    .benchmark.title configure -text [format "toStudent_EM · 选面 case %04d" $selectionCase]
    .benchmark.path configure -text "记录目录：$output"
    set pointer "{\"session\":[::bench::quote $session],\"output\":[::bench::quote $output],\"selection_case\":$selectionCase,\"selection_root\":[::bench::quote $selectionRoot]}"
    ::bench::writeFile [file join $selectionRoot active_case.json] $pointer
    ::bench::writeFile $latestPointer $pointer
    ::bench::writeFile [file join $output current_selection.json] "{\"case\":$current,\"shape\":[::bench::quote [format part_%02d $current]],\"face_indices\":\[\]}"
    set status [format "新 case %04d 已就绪；之前的记录保留在原目录。请重新选面。" $selectionCase]
    return $output
}
proc ::bench::safeClearSelection {} {
    if {[catch {::bench::clearSelection} message]} {set ::bench::status "清空选择失败：$message"}
}
proc ::bench::safeNewCase {} {
    if {[catch {::bench::newCase} message]} {set ::bench::status "新建 case 失败：$message"}
}
proc ::bench::installCaseControls {} {
    if {![winfo exists .benchmark.caseActions]} {
        ttk::frame .benchmark.caseActions
        ttk::button .benchmark.caseActions.clear -text "清空当前选择" -command ::bench::safeClearSelection
        ttk::button .benchmark.caseActions.new -text "开始下一个 case" -command ::bench::safeNewCase
        pack .benchmark.caseActions.clear .benchmark.caseActions.new -side left -expand 1 -fill x -padx 3
        pack .benchmark.caseActions -after .benchmark.selected -anchor w -padx 13 -pady 7 -fill x
        .benchmark.list configure -height 4
    }
}
