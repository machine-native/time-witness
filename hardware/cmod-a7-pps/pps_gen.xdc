## Cmod A7-35T: the 12 MHz crystal in, one pulse per second out on DIP pin 1 and LED 1.
## Package pins from Digilent's Cmod-A7-Master.xdc (rev. B), digilent-xdc commit
## 00a3404901f35aa9567b01ecb3f2c233b6efe9f4; copy and digest in reference/receivers/.

set_property -dict { PACKAGE_PIN L17  IOSTANDARD LVCMOS33 } [get_ports { clk }];
create_clock -add -name sys_clk_pin -period 83.33 -waveform {0 41.66} [get_ports { clk }];

## pio1 (DIP pin 1): to the receiver's EXTINT input. Common ground required.
set_property -dict { PACKAGE_PIN M3   IOSTANDARD LVCMOS33  DRIVE 8  SLEW FAST } [get_ports { pps }];

## LD1 mirrors the pulse.
set_property -dict { PACKAGE_PIN A17  IOSTANDARD LVCMOS33 } [get_ports { led }];
