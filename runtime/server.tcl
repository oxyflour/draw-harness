# Real DRAWEXE hosts every command and owns the BRep directory.
pload MODELING
pload -AgentPlugin AGENT
namespace eval ::occ_harness {
    variable capturing 0
    variable output ""
    variable shutdown 0
    variable busy 0
}
rename ::puts ::occ_harness::original_puts
proc ::puts {args} {
    if {$::occ_harness::capturing} {
        set values $args
        set newline "\n"
        if {[lindex $values 0] eq "-nonewline"} {
            set newline ""
            set values [lrange $values 1 end]
        }
        if {[llength $values] == 1 || ([llength $values] == 2 && [lindex $values 0] in {stdout stderr})} {
            set remaining [expr {65536 - [string length $::occ_harness::output]}]
            if {$remaining > 0} {
                append ::occ_harness::output [string range "[lindex $values end]$newline" 0 [expr {$remaining-1}]]
            }
            return
        }
    }
    tailcall ::occ_harness::original_puts {*}$args
}
proc ::occ_harness::accept {channel address port} {
    fconfigure $channel -blocking 0 -buffering line -encoding utf-8 -translation lf
    fileevent $channel readable [list ::occ_harness::read $channel]
}
proc ::occ_harness::read {channel} {
    if {[catch {gets $channel line} n] || [eof $channel]} {catch {close $channel}; return}
    if {$n < 0} {return}
    if {$::occ_harness::busy} {
        puts $channel {"ok":false,"error":"Session busy"}
        flush $channel
        return
    }
    set ::occ_harness::busy 1
    # DBRep resolves DRAW variables in the current Tcl frame: always use global scope.
    if {[catch {uplevel #0 [list ah_rpc $line $::env(OCC_HARNESS_TOKEN)]} result]} {
        set result {"ok":false,"error":"Native protocol failure; see draw.log"}
    }
    set ::occ_harness::busy 0
    catch {puts $channel $result; flush $channel}
    catch {close $channel}
    if {$::occ_harness::shutdown} {after 50 {set ::occ_harness::done 1}}
}
set listener [socket -server ::occ_harness::accept -myaddr 127.0.0.1 0]
set port [lindex [fconfigure $listener -sockname] end]
set ready [open "$::env(OCC_HARNESS_READY).tmp" w]
fconfigure $ready -encoding utf-8 -translation lf
puts $ready $port
close $ready
file rename -force "$::env(OCC_HARNESS_READY).tmp" $::env(OCC_HARNESS_READY)
vwait ::occ_harness::done
close $listener
