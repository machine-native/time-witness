// Testbench: the rising edge comes exactly every DIVIDE cycles, and stays high
// HIGH_CYCLES cycles. Scaled down (DIVIDE = 1200, HIGH = 120) so it runs in a
// moment; the arithmetic is the same at 12,000,000.
//
//     iverilog -g2012 -o tb.vvp pps_gen.v tb_pps_gen.v && vvp tb.vvp
`timescale 1ns/1ps
module tb_pps_gen;
    localparam integer DIV = 1200, HIGH = 120;
    reg clk = 0;
    always #41.667 clk = ~clk;                    // 12 MHz
    wire pps, led;
    pps_gen #(.DIVIDE(DIV), .HIGH_CYCLES(HIGH)) dut (.clk(clk), .pps(pps), .led(led));

    integer cycle = 0, last_rise = -1, rises = 0, high_len = 0, errors = 0;
    reg prev = 0;
    always @(posedge clk) begin
        cycle <= cycle + 1;
        prev <= pps;
        if (pps && !prev) begin
            if (last_rise >= 0 && cycle - last_rise != DIV) begin
                $display("FAIL: period %0d cycles, want %0d", cycle - last_rise, DIV);
                errors = errors + 1;
            end
            last_rise <= cycle;
            rises <= rises + 1;
            high_len <= 1;
        end else if (pps) high_len <= high_len + 1;
        if (!pps && prev && high_len != HIGH) begin
            $display("FAIL: high for %0d cycles, want %0d", high_len, HIGH);
            errors = errors + 1;
        end
        if (led !== pps) begin
            $display("FAIL: led does not mirror pps");
            errors = errors + 1;
        end
    end

    initial begin
        repeat (DIV * 5 + 10) @(posedge clk);
        if (rises < 5) begin
            $display("FAIL: %0d rising edges in 5 periods", rises);
            errors = errors + 1;
        end
        if (errors == 0) $display("PASS: %0d edges, every period %0d cycles, high %0d", rises, DIV, HIGH);
        $finish;
    end
endmodule
