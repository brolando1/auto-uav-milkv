cmd_src/modules/src/kalman_core/mm_flow.o := arm-none-eabi-gcc -Wp,-MD,src/modules/src/kalman_core/.mm_flow.o.d    -I/home/phheld/project/crazyflie-firmware/src/modules/src/kalman_core -Isrc/modules/src/kalman_core -D__firmware__ -fno-exceptions -Wall -Wmissing-braces -fno-strict-aliasing -ffunction-sections -fdata-sections -Wdouble-promotion -std=gnu11 -DCRAZYFLIE_FW   -I/home/phheld/project/crazyflie-firmware/vendor/CMSIS/CMSIS/Core/Include   -I/home/phheld/project/crazyflie-firmware/vendor/CMSIS/CMSIS/DSP/Include   -I/home/phheld/project/crazyflie-firmware/vendor/libdw1000/inc   -I/home/phheld/project/crazyflie-firmware/vendor/FreeRTOS/include   -I/home/phheld/project/crazyflie-firmware/vendor/FreeRTOS/portable/GCC/ARM_CM4F   -I/home/phheld/project/crazyflie-firmware/src/config   -I/home/phheld/project/crazyflie-firmware/src/platform/interface   -I/home/phheld/project/crazyflie-firmware/src/deck/interface   -I/home/phheld/project/crazyflie-firmware/src/deck/drivers/interface   -I/home/phheld/project/crazyflie-firmware/src/drivers/interface   -I/home/phheld/project/crazyflie-firmware/src/drivers/bosch/interface   -I/home/phheld/project/crazyflie-firmware/src/drivers/esp32/interface   -I/home/phheld/project/crazyflie-firmware/src/hal/interface   -I/home/phheld/project/crazyflie-firmware/src/modules/interface   -I/home/phheld/project/crazyflie-firmware/src/modules/interface/kalman_core   -I/home/phheld/project/crazyflie-firmware/src/modules/interface/lighthouse   -I/home/phheld/project/crazyflie-firmware/src/modules/interface/outlierfilter   -I/home/phheld/project/crazyflie-firmware/src/modules/interface/cpx   -I/home/phheld/project/crazyflie-firmware/src/modules/interface/p2pDTR   -I/home/phheld/project/crazyflie-firmware/src/modules/interface/controller   -I/home/phheld/project/crazyflie-firmware/src/modules/interface/estimator   -I/home/phheld/project/crazyflie-firmware/src/utils/interface   -I/home/phheld/project/crazyflie-firmware/src/utils/interface/kve   -I/home/phheld/project/crazyflie-firmware/src/utils/interface/lighthouse   -I/home/phheld/project/crazyflie-firmware/src/utils/interface/tdoa   -I/home/phheld/project/crazyflie-firmware/src/lib/FatFS   -I/home/phheld/project/crazyflie-firmware/src/lib/CMSIS/STM32F4xx/Include   -I/home/phheld/project/crazyflie-firmware/src/lib/STM32_USB_Device_Library/Core/inc   -I/home/phheld/project/crazyflie-firmware/src/lib/STM32_USB_OTG_Driver/inc   -I/home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc   -I/home/phheld/project/crazyflie-firmware/src/lib/vl53l1   -I/home/phheld/project/crazyflie-firmware/src/lib/vl53l1/core/inc   -I/home/phheld/project/tof-camera-logger/app-tof-logger-tof/build/include/generated -fno-delete-null-pointer-checks -Wno-unused-but-set-variable -Wno-unused-const-variable -fomit-frame-pointer -fno-var-tracking-assignments -Wno-pointer-sign -fno-strict-overflow -fconserve-stack -Werror=implicit-int -Werror=date-time -DCC_HAVE_ASM_GOTO -mcpu=cortex-m4 -mthumb -mfloat-abi=hard -mfpu=fpv4-sp-d16 -g3 -fno-math-errno -DARM_MATH_CM4 -D__FPU_PRESENT=1 -mfp16-format=ieee -Wno-array-bounds -Wno-stringop-overread -Wno-stringop-overflow -DSTM32F4XX -DSTM32F40_41xxx -DHSE_VALUE=8000000 -DUSE_STDPERIPH_DRIVER -Os -Werror  -I/home/phheld/project/crazyflie-firmware/src -Isrc   -c -o src/modules/src/kalman_core/mm_flow.o /home/phheld/project/crazyflie-firmware/src/modules/src/kalman_core/mm_flow.c

source_src/modules/src/kalman_core/mm_flow.o := /home/phheld/project/crazyflie-firmware/src/modules/src/kalman_core/mm_flow.c

deps_src/modules/src/kalman_core/mm_flow.o := \
  /home/phheld/project/crazyflie-firmware/src/modules/interface/kalman_core/mm_flow.h \
  /home/phheld/project/crazyflie-firmware/src/modules/interface/kalman_core/kalman_core.h \
  /home/phheld/project/crazyflie-firmware/src/utils/interface/cf_math.h \
  /home/phheld/project/crazyflie-firmware/vendor/CMSIS/CMSIS/DSP/Include/arm_math.h \
  /home/phheld/project/crazyflie-firmware/vendor/CMSIS/CMSIS/Core/Include/cmsis_compiler.h \
  /usr/lib/gcc/arm-none-eabi/13.2.1/include/stdint.h \
  /home/phheld/project/crazyflie-firmware/vendor/CMSIS/CMSIS/Core/Include/cmsis_gcc.h \
  /usr/include/newlib/string.h \
  /usr/include/newlib/_ansi.h \
  /usr/include/newlib/newlib.h \
  /usr/include/newlib/_newlib_version.h \
  /usr/include/newlib/sys/config.h \
    $(wildcard include/config/h//.h) \
  /usr/include/newlib/machine/ieeefp.h \
  /usr/include/newlib/sys/features.h \
  /usr/include/newlib/sys/reent.h \
  /usr/include/newlib/_ansi.h \
  /usr/lib/gcc/arm-none-eabi/13.2.1/include/stddef.h \
  /usr/include/newlib/sys/cdefs.h \
  /usr/include/newlib/machine/_default_types.h \
  /usr/include/newlib/sys/_types.h \
  /usr/include/newlib/machine/_types.h \
  /usr/include/newlib/sys/lock.h \
  /usr/include/newlib/sys/_locale.h \
  /usr/include/newlib/strings.h \
  /usr/include/newlib/sys/string.h \
  /usr/include/newlib/math.h \
  /usr/lib/gcc/arm-none-eabi/13.2.1/include/float.h \
  /usr/lib/gcc/arm-none-eabi/13.2.1/include/limits.h \
  /home/phheld/project/crazyflie-firmware/src/utils/interface/cfassert.h \
  /usr/lib/gcc/arm-none-eabi/13.2.1/include/stdbool.h \
  /home/phheld/project/crazyflie-firmware/src/modules/interface/stabilizer_types.h \
  /home/phheld/project/crazyflie-firmware/src/hal/interface/imu_types.h \
  /home/phheld/project/crazyflie-firmware/src/utils/interface/lighthouse/lighthouse_types.h \
  /home/phheld/project/crazyflie-firmware/src/modules/interface/log.h \
    $(wildcard include/config/debug/log/enable.h) \
  /home/phheld/project/crazyflie-firmware/src/platform/interface/platform_defaults.h \
    $(wildcard include/config/platform/cf2.h) \
    $(wildcard include/config/platform/cf21bl.h) \
    $(wildcard include/config/platform/bolt.h) \
    $(wildcard include/config/platform/tag.h) \
    $(wildcard include/config/platform/flapper.h) \
    $(wildcard include/config/modify/cf/mass.h) \
    $(wildcard include/config/modified/cf/mass.h) \
    $(wildcard include/config/deck/bigquad.h) \
    $(wildcard include/config/motors/require/arming.h) \
    $(wildcard include/config/motors/default/idle/thrust.h) \
  /home/phheld/project/crazyflie-firmware/src/platform/interface/platform_defaults_cf2.h \
    $(wildcard include/config/crazyflie/thrust/upgrade/kit.h) \
    $(wildcard include/config/enable/thrust/bat/compensated.h) \
    $(wildcard include/config/crazyflie/21/plus.h) \
    $(wildcard include/config/crazyflie/legacy/propellers.h) \
  /home/phheld/project/crazyflie-firmware/src/modules/interface/param.h \
  /home/phheld/project/crazyflie-firmware/src/modules/interface/param_logic.h \
  /home/phheld/project/crazyflie-firmware/src/modules/interface/crtp.h \

src/modules/src/kalman_core/mm_flow.o: $(deps_src/modules/src/kalman_core/mm_flow.o)

$(deps_src/modules/src/kalman_core/mm_flow.o):
