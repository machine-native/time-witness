# Build AND program the free-running 1 PPS generator on a Cmod A7-35T.
#
#     cd hardware/cmod-a7-pps
#     vivado -mode batch -source build.tcl
#
# NOT YET RUN: written on a machine without Vivado; the design is simulated
# (tb_pps_gen.v). Same flow as chronology-protocol's fpga/build_pinprobe.tcl, which
# has built and programmed this board.

set part   xc7a35tcpg236-1
set top    pps_gen
set outdir [file normalize ./build]
file mkdir $outdir

create_project -in_memory -part $part
read_verilog ./pps_gen.v
read_xdc     ./pps_gen.xdc

synth_design -top $top -part $part
opt_design
place_design
route_design
report_timing_summary -file $outdir/timing.rpt
write_bitstream -force $outdir/${top}.bit
puts "\nbitstream : $outdir/${top}.bit"

open_hw_manager
connect_hw_server
if {[llength [get_hw_targets]] == 0} {
    puts "\nERROR: no JTAG target found -- is the board plugged in?\n"
    disconnect_hw_server
    exit 1
}
open_hw_target
set dev [lindex [get_hw_devices] 0]
current_hw_device $dev
refresh_hw_device -update_hw_probes false $dev
set_property PROGRAM.FILE $outdir/${top}.bit $dev
program_hw_devices $dev
refresh_hw_device -update_hw_probes false $dev
set done [get_property REGISTER.IR.BIT5_DONE $dev]
close_hw_target
disconnect_hw_server
close_hw_manager

if {$done ne "1"} {
    puts "\n=== PROGRAMMING FAILED === DONE did not assert.\n"
    exit 1
}
puts "\n=== 1 PPS RUNNING === LD1 blinks once a second, 100 ms on."
puts "DIP pin 1 carries the edge; wire it to the receiver's EXTINT, grounds joined."
puts "The bitstream lives in FPGA RAM: unplugging the board stops it.\n"
exit 0
