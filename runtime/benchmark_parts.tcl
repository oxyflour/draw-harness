# DRAW owns a global `grid` command. ttk::combobox's popup calls Tk `grid`
# and can therefore raise an OCCT access violation. Use only pack-based widgets.
proc ::bench::choosePart {} {
    variable chosen
    set list .benchmark.partSelector.list
    set selected [$list curselection]
    if {[llength $selected] == 1} {set chosen [$list get [lindex $selected 0]]}
}
proc ::bench::installPartSelector {} {
    variable cases
    variable current
    variable initial
    variable chosen
    set rank [expr {$current > 0 ? $current : $initial}]
    if {[info exists chosen] && $chosen ne ""} {
        scan [lindex [split $chosen |] 0] %d rank
    }
    if {[winfo exists .benchmark.case]} {destroy .benchmark.case}
    if {![winfo exists .benchmark.partSelector]} {
        ttk::frame .benchmark.partSelector
        listbox .benchmark.partSelector.list -height 4 -width 46 -selectmode browse -exportselection 0
        ttk::scrollbar .benchmark.partSelector.scroll -orient vertical -command {.benchmark.partSelector.list yview}
        .benchmark.partSelector.list configure -yscrollcommand {.benchmark.partSelector.scroll set}
        pack .benchmark.partSelector.scroll -side right -fill y
        pack .benchmark.partSelector.list -side left -fill both -expand 1
        pack .benchmark.partSelector -after .benchmark.help -anchor w -padx 16 -pady 7 -fill x
        bind .benchmark.partSelector.list <<ListboxSelect>> ::bench::choosePart
        bind .benchmark.partSelector.list <Double-Button-1> {::bench::choosePart; ::bench::safeLoad}
        bind .benchmark.partSelector.list <Return> {::bench::choosePart; ::bench::safeLoad}
    }
    set list .benchmark.partSelector.list
    $list delete 0 end
    set selected 0
    set row 0
    foreach itemRank [lsort -integer [dict keys $cases]] {
        set item [dict get $cases $itemRank]
        $list insert end [format "%02d | %d faces | solid %d" $itemRank [dict get $item faces] [dict get $item source_index]]
        if {$itemRank == $rank} {set selected $row}
        incr row
    }
    $list selection set $selected
    $list activate $selected
    $list see $selected
    ::bench::choosePart
    .benchmark.help configure -text "1. 下方列表选择零件，再点“载入所选零件”（或双击）。\n2. 左键选面，Shift+左键多选，随后记录。\n3. 下个 case 点击“开始下一个 case”；旧记录保留。"
    .benchmark.load configure -text "载入所选零件"
    .benchmark.list configure -height 4
}
