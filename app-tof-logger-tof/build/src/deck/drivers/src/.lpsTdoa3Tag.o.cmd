cmd_src/deck/drivers/src/lpsTdoa3Tag.o := arm-none-eabi-gcc -Wp,-MD,src/deck/drivers/src/.lpsTdoa3Tag.o.d    -I/home/broland/auto-uav/crazyflie-firmware/src/deck/drivers/src -Isrc/deck/drivers/src -D__firmware__ -fno-exceptions -Wall -Wmissing-braces -fno-strict-aliasing -ffunction-sections -fdata-sections -Wdouble-promotion -std=gnu11 -DCRAZYFLIE_FW   -I/home/broland/auto-uav/crazyflie-firmware/vendor/CMSIS/CMSIS/Core/Include   -I/home/broland/auto-uav/crazyflie-firmware/vendor/CMSIS/CMSIS/DSP/Include   -I/home/broland/auto-uav/crazyflie-firmware/vendor/libdw1000/inc   -I/home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include   -I/home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/portable/GCC/ARM_CM4F   -I/home/broland/auto-uav/crazyflie-firmware/src/config   -I/home/broland/auto-uav/crazyflie-firmware/src/platform/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/deck/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/deck/drivers/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/drivers/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/drivers/bosch/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/drivers/esp32/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/hal/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/kalman_core   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/lighthouse   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/outlierfilter   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/cpx   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/p2pDTR   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/controller   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/estimator   -I/home/broland/auto-uav/crazyflie-firmware/src/utils/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/utils/interface/kve   -I/home/broland/auto-uav/crazyflie-firmware/src/utils/interface/lighthouse   -I/home/broland/auto-uav/crazyflie-firmware/src/utils/interface/tdoa   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/FatFS   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/CMSIS/STM32F4xx/Include   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/STM32_USB_Device_Library/Core/inc   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/STM32_USB_OTG_Driver/inc   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/vl53l1   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/vl53l1/core/inc   -I/home/broland/Desktop/milkv-drone/app-tof-logger-tof/build/include/generated -fno-delete-null-pointer-checks -Wno-unused-but-set-variable -Wno-unused-const-variable -fomit-frame-pointer -fno-var-tracking-assignments -Wno-pointer-sign -fno-strict-overflow -fconserve-stack -Werror=implicit-int -Werror=date-time -DCC_HAVE_ASM_GOTO -mcpu=cortex-m4 -mthumb -mfloat-abi=hard -mfpu=fpv4-sp-d16 -g3 -fno-math-errno -DARM_MATH_CM4 -D__FPU_PRESENT=1 -mfp16-format=ieee -Wno-array-bounds -Wno-stringop-overread -Wno-stringop-overflow -DSTM32F4XX -DSTM32F40_41xxx -DHSE_VALUE=8000000 -DUSE_STDPERIPH_DRIVER -Os -Werror  -I/home/broland/auto-uav/crazyflie-firmware/src -Isrc -DTOF_OVER_CPX   -c -o src/deck/drivers/src/lpsTdoa3Tag.o /home/broland/auto-uav/crazyflie-firmware/src/deck/drivers/src/lpsTdoa3Tag.c

source_src/deck/drivers/src/lpsTdoa3Tag.o := /home/broland/auto-uav/crazyflie-firmware/src/deck/drivers/src/lpsTdoa3Tag.c

deps_src/deck/drivers/src/lpsTdoa3Tag.o := \
    $(wildcard include/config/deck/loco/tdoa3/hybrid/mode.h) \
    $(wildcard include/config/deck/loco/2d/position.h) \
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
  /usr/lib/gcc/arm-none-eabi/10.3.1/include/stddef.h \
  /usr/include/newlib/sys/_types.h \
  /usr/include/newlib/machine/_types.h \
  /usr/include/newlib/machine/_default_types.h \
  /usr/include/newlib/sys/lock.h \
  /usr/include/newlib/sys/cdefs.h \
  /usr/include/newlib/sys/_locale.h \
  /usr/include/newlib/strings.h \
  /usr/include/newlib/sys/string.h \
  /usr/include/newlib/stdlib.h \
  /usr/include/newlib/machine/stdlib.h \
  /usr/include/newlib/alloca.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include/FreeRTOS.h \
  /usr/lib/gcc/arm-none-eabi/10.3.1/include/stdint.h \
  /home/broland/auto-uav/crazyflie-firmware/src/config/FreeRTOSConfig.h \
    $(wildcard include/config/h.h) \
    $(wildcard include/config/debug/queue/monitor.h) \
  /home/broland/auto-uav/crazyflie-firmware/src/config/config.h \
    $(wildcard include/config/h/.h) \
    $(wildcard include/config/block/address.h) \
  /home/broland/auto-uav/crazyflie-firmware/src/drivers/interface/nrf24l01.h \
  /usr/lib/gcc/arm-none-eabi/10.3.1/include/stdbool.h \
  /home/broland/auto-uav/crazyflie-firmware/src/drivers/interface/nRF24L01reg.h \
  /home/broland/auto-uav/crazyflie-firmware/src/config/trace.h \
  /home/broland/auto-uav/crazyflie-firmware/src/hal/interface/usec_time.h \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/cfassert.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include/projdefs.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include/portable.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include/deprecated_definitions.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/portable/GCC/ARM_CM4F/portmacro.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include/mpu_wrappers.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include/task.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include/list.h \
  /home/broland/auto-uav/crazyflie-firmware/src/deck/drivers/interface/lpsTdoa3Tag.h \
  /home/broland/auto-uav/crazyflie-firmware/src/deck/drivers/interface/locodeck.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/libdw1000/inc/libdw1000.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/libdw1000/inc/libdw1000Spi.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/libdw1000/inc/dw1000.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/libdw1000/inc/libdw1000Types.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/stabilizer_types.h \
  /home/broland/auto-uav/crazyflie-firmware/src/hal/interface/imu_types.h \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/lighthouse/lighthouse_types.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/tdoaEngineInstance.h \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/tdoa/tdoaEngine.h \
    $(wildcard include/config/deck/loco/longer/range.h) \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/tdoa/tdoaStorage.h \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/clockCorrectionEngine.h \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/tdoa/tdoaStats.h \
  /usr/include/newlib/inttypes.h \
  /usr/include/newlib/sys/_intsup.h \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/statsCnt.h \
    $(wildcard include/config/debug/log/enable.h) \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/log.h \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/tdoa/tdoaStats.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/estimator/estimator.h \
    $(wildcard include/config/estimator/kalman/enable.h) \
    $(wildcard include/config/estimator/ukf/enable.h) \
    $(wildcard include/config/estimator/oot.h) \
  /home/broland/auto-uav/crazyflie-firmware/src/deck/drivers/interface/mac.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/param.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/param_logic.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/crtp.h \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/cf_math.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/CMSIS/CMSIS/DSP/Include/arm_math.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/CMSIS/CMSIS/Core/Include/cmsis_compiler.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/CMSIS/CMSIS/Core/Include/cmsis_gcc.h \
  /usr/include/newlib/math.h \
  /usr/lib/gcc/arm-none-eabi/10.3.1/include/float.h \
  /usr/lib/gcc/arm-none-eabi/10.3.1/include-fixed/limits.h \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/cfassert.h \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/physicalConstants.h \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/debug.h \
    $(wildcard include/config/debug/print/on/uart1.h) \
  /home/broland/auto-uav/crazyflie-firmware/src/config/config.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/console.h \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/eprintf.h \
  /usr/lib/gcc/arm-none-eabi/10.3.1/include/stdarg.h \

src/deck/drivers/src/lpsTdoa3Tag.o: $(deps_src/deck/drivers/src/lpsTdoa3Tag.o)

$(deps_src/deck/drivers/src/lpsTdoa3Tag.o):
