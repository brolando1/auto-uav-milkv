#!/bin/sh
# Prepare the Milk-V DuoS J2 (Raspberry Pi style) camera connector.
#
# The stock Debian image does not configure J2, so after every boot:
#   - the IIC2_SCL / IIC2_SDA pads must be switched from GPIO to I2C2
#   - CAM_PD1 (XGPIOA_4, J2 pin 5) must be driven high; on the ST PCB4189
#     board this pin enables the camera's power regulator.
# Pad values follow Milk-V's own u-boot cvi_board_init.c for the DuoS.
#
# Usage: vd55g1-power.sh on|off     (as root; vd55g1-power.service runs "on" at boot)

set -e

PINMUX_IIC2_SCL=0x030010b8   # function 0 = IIC2_SCL, 3 = PWR_GPIO_12
PINMUX_IIC2_SDA=0x030010bc   # function 0 = IIC2_SDA, 3 = PWR_GPIO_13
PINMUX_CAM_PD1=0x03001010    # function 3 = XGPIOA_4
CAM_EN_GPIO=484              # gpiochip0 (base 480) line 4 = XGPIOA_4
G=/sys/class/gpio

cam_en() {
	[ -d $G/gpio$CAM_EN_GPIO ] || echo $CAM_EN_GPIO > $G/export
	echo "$1" > $G/gpio$CAM_EN_GPIO/direction
}

case "$1" in
on)
	devmem $PINMUX_IIC2_SCL 32 0
	devmem $PINMUX_IIC2_SDA 32 0
	devmem $PINMUX_CAM_PD1 32 3
	cam_en low       # hold the camera off briefly for a clean reset
	sleep 0.05
	cam_en high      # power on; the sensor boots from its ROM in a few ms
	sleep 0.02
	echo "J2 camera: I2C2 routed, power on"
	;;
off)
	cam_en low
	devmem $PINMUX_IIC2_SCL 32 3
	devmem $PINMUX_IIC2_SDA 32 3
	echo "J2 camera: power off, I2C2 pads back to GPIO"
	;;
*)
	echo "usage: $0 on|off" >&2
	exit 1
	;;
esac
