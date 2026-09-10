cmd_src/modules/src/estimator/estimator.o := arm-none-eabi-gcc -Wp,-MD,src/modules/src/estimator/.estimator.o.d    -I/home/broland/auto-uav/crazyflie-firmware/src/modules/src/estimator -Isrc/modules/src/estimator -D__firmware__ -fno-exceptions -Wall -Wmissing-braces -fno-strict-aliasing -ffunction-sections -fdata-sections -Wdouble-promotion -std=gnu11 -DCRAZYFLIE_FW   -I/home/broland/auto-uav/crazyflie-firmware/vendor/CMSIS/CMSIS/Core/Include   -I/home/broland/auto-uav/crazyflie-firmware/vendor/CMSIS/CMSIS/DSP/Include   -I/home/broland/auto-uav/crazyflie-firmware/vendor/libdw1000/inc   -I/home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include   -I/home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/portable/GCC/ARM_CM4F   -I/home/broland/auto-uav/crazyflie-firmware/src/config   -I/home/broland/auto-uav/crazyflie-firmware/src/platform/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/deck/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/deck/drivers/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/drivers/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/drivers/bosch/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/drivers/esp32/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/hal/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/kalman_core   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/lighthouse   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/outlierfilter   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/cpx   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/p2pDTR   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/controller   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/estimator   -I/home/broland/auto-uav/crazyflie-firmware/src/utils/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/utils/interface/kve   -I/home/broland/auto-uav/crazyflie-firmware/src/utils/interface/lighthouse   -I/home/broland/auto-uav/crazyflie-firmware/src/utils/interface/tdoa   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/FatFS   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/CMSIS/STM32F4xx/Include   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/STM32_USB_Device_Library/Core/inc   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/STM32_USB_OTG_Driver/inc   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/vl53l1   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/vl53l1/core/inc   -I/home/broland/Desktop/milkv-drone/app-tof-logger-tof/build/include/generated -fno-delete-null-pointer-checks -Wno-unused-but-set-variable -Wno-unused-const-variable -fomit-frame-pointer -fno-var-tracking-assignments -Wno-pointer-sign -fno-strict-overflow -fconserve-stack -Werror=implicit-int -Werror=date-time -DCC_HAVE_ASM_GOTO -mcpu=cortex-m4 -mthumb -mfloat-abi=hard -mfpu=fpv4-sp-d16 -g3 -fno-math-errno -DARM_MATH_CM4 -D__FPU_PRESENT=1 -mfp16-format=ieee -Wno-array-bounds -Wno-stringop-overread -Wno-stringop-overflow -DSTM32F4XX -DSTM32F40_41xxx -DHSE_VALUE=8000000 -DUSE_STDPERIPH_DRIVER -Os -Werror  -I/home/broland/auto-uav/crazyflie-firmware/src -Isrc -DTOF_OVER_CPX   -c -o src/modules/src/estimator/estimator.o /home/broland/auto-uav/crazyflie-firmware/src/modules/src/estimator/estimator.c

source_src/modules/src/estimator/estimator.o := /home/broland/auto-uav/crazyflie-firmware/src/modules/src/estimator/estimator.c

deps_src/modules/src/estimator/estimator.o := \
    $(wildcard include/config/estimator/kalman/enable.h) \
    $(wildcard include/config/estimator/ukf/enable.h) \
    $(wildcard include/config/estimator/oot.h) \
    $(wildcard include/config/estimator/kalman.h) \
    $(wildcard include/config/estimator/ukf.h) \
    $(wildcard include/config/estimator/complementary.h) \
    $(wildcard include/config/deck/loco/2d/position.h) \
  /home/broland/auto-uav/crazyflie-firmware/src/config/stm32fxxx.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/CMSIS/STM32F4xx/Include/stm32f4xx.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/CMSIS/CMSIS/Core/Include/core_cm4.h \
  /usr/lib/gcc/arm-none-eabi/10.3.1/include/stdint.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/CMSIS/CMSIS/Core/Include/cmsis_version.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/CMSIS/CMSIS/Core/Include/cmsis_compiler.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/CMSIS/CMSIS/Core/Include/cmsis_gcc.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/CMSIS/CMSIS/Core/Include/mpu_armv7.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/CMSIS/STM32F4xx/Include/system_stm32f4xx.h \
  /home/broland/auto-uav/crazyflie-firmware/src/config/stm32f4xx_conf.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_adc.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_crc.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_dbgmcu.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_dma.h \
    $(wildcard include/config/it.h) \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_exti.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_flash.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_gpio.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_i2c.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_iwdg.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_pwr.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_rcc.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_rtc.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_sdio.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_spi.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_syscfg.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_tim.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_usart.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_wwdg.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_misc.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_cryp.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_hash.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_rng.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_can.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_dac.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_dcmi.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_fsmc.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include/FreeRTOS.h \
  /usr/lib/gcc/arm-none-eabi/10.3.1/include/stddef.h \
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
  /home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include/queue.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include/task.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include/list.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/static_mem.h \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/debug.h \
    $(wildcard include/config/debug/print/on/uart1.h) \
  /home/broland/auto-uav/crazyflie-firmware/src/config/config.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/console.h \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/eprintf.h \
  /usr/lib/gcc/arm-none-eabi/10.3.1/include/stdarg.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/estimator/estimator.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/stabilizer_types.h \
  /home/broland/auto-uav/crazyflie-firmware/src/hal/interface/imu_types.h \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/lighthouse/lighthouse_types.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/estimator/estimator_complementary.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/estimator/estimator_kalman.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/estimator/estimator_ukf.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/log.h \
    $(wildcard include/config/debug/log/enable.h) \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/statsCnt.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/eventtrigger.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/quatcompress.h \
  /usr/include/newlib/math.h \
  /usr/include/newlib/sys/reent.h \
  /usr/include/newlib/_ansi.h \
  /usr/include/newlib/newlib.h \
  /usr/include/newlib/_newlib_version.h \
  /usr/include/newlib/sys/config.h \
    $(wildcard include/config/h//.h) \
  /usr/include/newlib/machine/ieeefp.h \
  /usr/include/newlib/sys/features.h \
  /usr/include/newlib/sys/_types.h \
  /usr/include/newlib/machine/_types.h \
  /usr/include/newlib/machine/_default_types.h \
  /usr/include/newlib/sys/lock.h \
  /usr/include/newlib/sys/cdefs.h \
  /usr/include/newlib/_ansi.h \

src/modules/src/estimator/estimator.o: $(deps_src/modules/src/estimator/estimator.o)

$(deps_src/modules/src/estimator/estimator.o):
