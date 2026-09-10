cmd_src/utils/src/pid.o := arm-none-eabi-gcc -Wp,-MD,src/utils/src/.pid.o.d    -I/home/broland/auto-uav/crazyflie-firmware/src/utils/src -Isrc/utils/src -D__firmware__ -fno-exceptions -Wall -Wmissing-braces -fno-strict-aliasing -ffunction-sections -fdata-sections -Wdouble-promotion -std=gnu11 -DCRAZYFLIE_FW   -I/home/broland/auto-uav/crazyflie-firmware/vendor/CMSIS/CMSIS/Core/Include   -I/home/broland/auto-uav/crazyflie-firmware/vendor/CMSIS/CMSIS/DSP/Include   -I/home/broland/auto-uav/crazyflie-firmware/vendor/libdw1000/inc   -I/home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include   -I/home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/portable/GCC/ARM_CM4F   -I/home/broland/auto-uav/crazyflie-firmware/src/config   -I/home/broland/auto-uav/crazyflie-firmware/src/platform/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/deck/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/deck/drivers/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/drivers/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/drivers/bosch/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/drivers/esp32/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/hal/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/kalman_core   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/lighthouse   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/outlierfilter   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/cpx   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/p2pDTR   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/controller   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/estimator   -I/home/broland/auto-uav/crazyflie-firmware/src/utils/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/utils/interface/kve   -I/home/broland/auto-uav/crazyflie-firmware/src/utils/interface/lighthouse   -I/home/broland/auto-uav/crazyflie-firmware/src/utils/interface/tdoa   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/FatFS   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/CMSIS/STM32F4xx/Include   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/STM32_USB_Device_Library/Core/inc   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/STM32_USB_OTG_Driver/inc   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/vl53l1   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/vl53l1/core/inc   -I/home/broland/Desktop/milkv-drone/app-tof-logger-tof/build/include/generated -fno-delete-null-pointer-checks -Wno-unused-but-set-variable -Wno-unused-const-variable -fomit-frame-pointer -fno-var-tracking-assignments -Wno-pointer-sign -fno-strict-overflow -fconserve-stack -Werror=implicit-int -Werror=date-time -DCC_HAVE_ASM_GOTO -mcpu=cortex-m4 -mthumb -mfloat-abi=hard -mfpu=fpv4-sp-d16 -g3 -fno-math-errno -DARM_MATH_CM4 -D__FPU_PRESENT=1 -mfp16-format=ieee -Wno-array-bounds -Wno-stringop-overread -Wno-stringop-overflow -DSTM32F4XX -DSTM32F40_41xxx -DHSE_VALUE=8000000 -DUSE_STDPERIPH_DRIVER -Os -Werror  -I/home/broland/auto-uav/crazyflie-firmware/src -Isrc -DTOF_OVER_CPX   -c -o src/utils/src/pid.o /home/broland/auto-uav/crazyflie-firmware/src/utils/src/pid.c

source_src/utils/src/pid.o := /home/broland/auto-uav/crazyflie-firmware/src/utils/src/pid.c

deps_src/utils/src/pid.o := \
    $(wildcard include/config/controller/pid/filter/all.h) \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/pid.h \
  /usr/lib/gcc/arm-none-eabi/10.3.1/include/stdbool.h \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/filter.h \
  /usr/lib/gcc/arm-none-eabi/10.3.1/include/stdint.h \
  /usr/include/newlib/math.h \
  /usr/include/newlib/sys/reent.h \
  /usr/include/newlib/_ansi.h \
  /usr/include/newlib/newlib.h \
  /usr/include/newlib/_newlib_version.h \
  /usr/include/newlib/sys/config.h \
    $(wildcard include/config/h//.h) \
  /usr/include/newlib/machine/ieeefp.h \
  /usr/include/newlib/sys/features.h \
  /usr/lib/gcc/arm-none-eabi/10.3.1/include/stddef.h \
  /usr/include/newlib/sys/_types.h \
  /usr/include/newlib/machine/_types.h \
  /usr/include/newlib/machine/_default_types.h \
  /usr/include/newlib/sys/lock.h \
  /usr/include/newlib/sys/cdefs.h \
  /usr/include/newlib/_ansi.h \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/num.h \
  /usr/lib/gcc/arm-none-eabi/10.3.1/include/float.h \

src/utils/src/pid.o: $(deps_src/utils/src/pid.o)

$(deps_src/utils/src/pid.o):
