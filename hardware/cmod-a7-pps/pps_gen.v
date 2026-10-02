// A free-running one-pulse-per-second edge from the Cmod A7's own 12 MHz crystal.
//
// WHY THIS EXISTS
//
// A time witness in OSC mode time-marks an edge the receiver does not make: the
// GNSS receiver's EXTINT input stamps each rising edge (UBX-TIM-TM2) against GNSS
// time, and the sequence of stamps measures the oscillator behind the edge. The
// design calls for an atomic reference there. Until one is bought, this board's
// crystal stands in: it is free-running -- nothing steers it toward GNSS time, so
// the receiver measures it rather than disciplining it -- and it is already owned.
//
// It is a poor clock and that is the point of measuring it. A plain crystal drifts
// by parts per million, so its edges walk away from the GNSS second by microseconds
// per second; a rubidium reference later drops into the same wiring and the same
// analysis. Nothing here claims the crystal is good.
//
// WHAT IT DOES
//
// Counts DIVIDE clock cycles per period (12,000,000 at 12 MHz) and drives `pps`
// high for the first HIGH_CYCLES of each period (100 ms). The rising edge is the
// timed event; it is registered, so it is aligned to a crystal edge with no
// combinational glitch. The LED mirrors the pulse so the board shows it is alive.
// Nothing is received and nothing is configured: no input can move the edges.

module pps_gen #(
    parameter integer DIVIDE      = 12_000_000,   // crystal cycles per second
    parameter integer HIGH_CYCLES = 1_200_000     // 100 ms high
) (
    input  wire clk,
    output reg  pps = 1'b0,
    output wire led
);
    localparam integer W = $clog2(DIVIDE);
    reg  [W-1:0] count = DIVIDE - 1;             // so the first edge is a whole period too
    wire [W-1:0] next  = (count == DIVIDE - 1) ? {W{1'b0}} : count + 1'b1;

    always @(posedge clk) begin
        count <= next;
        pps   <= (next < HIGH_CYCLES);           // high for counts 0 .. HIGH_CYCLES-1
    end

    assign led = pps;
endmodule
