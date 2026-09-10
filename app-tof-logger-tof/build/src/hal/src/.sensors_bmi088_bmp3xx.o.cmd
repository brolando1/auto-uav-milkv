cmd_src/hal/src/sensors_bmi088_bmp3xx.o := arm-none-eabi-gcc -Wp,-MD,src/hal/src/.sensors_bmi088_bmp3xx.o.d    -I/home/broland/auto-uav/crazyflie-firmware/src/hal/src -Isrc/hal/src -D__firmware__ -fno-exceptions -Wall -Wmissing-braces -fno-strict-aliasing -ffunction-sections -fdata-sections -Wdouble-promotion -std=gnu11 -DCRAZYFLIE_FW   -I/home/broland/auto-uav/crazyflie-firmware/vendor/CMSIS/CMSIS/Core/Include   -I/home/broland/auto-uav/crazyflie-firmware/vendor/CMSIS/CMSIS/DSP/Include   -I/home/broland/auto-uav/crazyflie-firmware/vendor/libdw1000/inc   -I/home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include   -I/home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/portable/GCC/ARM_CM4F   -I/home/broland/auto-uav/crazyflie-firmware/src/config   -I/home/broland/auto-uav/crazyflie-firmware/src/platform/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/deck/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/deck/drivers/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/drivers/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/drivers/bosch/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/drivers/esp32/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/hal/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/kalman_core   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/lighthouse   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/outlierfilter   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/cpx   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/p2pDTR   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/controller   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/estimator   -I/home/broland/auto-uav/crazyflie-firmware/src/utils/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/utils/interface/kve   -I/home/broland/auto-uav/crazyflie-firmware/src/utils/interface/lighthouse   -I/home/broland/auto-uav/crazyflie-firmware/src/utils/interface/tdoa   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/FatFS   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/CMSIS/STM32F4xx/Include   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/STM32_USB_Device_Library/Core/inc   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/STM32_USB_OTG_Driver/inc   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/vl53l1   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/vl53l1/core/inc   -I/home/broland/Desktop/milkv-drone/app-tof-logger-tof/build/include/generated -fno-delete-null-pointer-checks -Wno-unused-but-set-variable -Wno-unused-const-variable -fomit-frame-pointer -fno-var-tracking-assignments -Wno-pointer-sign -fno-strict-overflow -fconserve-stack -Werror=implicit-int -Werror=date-time -DCC_HAVE_ASM_GOTO -mcpu=cortex-m4 -mthumb -mfloat-abi=hard -mfpu=fpv4-sp-d16 -g3 -fno-math-errno -DARM_MATH_CM4 -D__FPU_PRESENT=1 -mfp16-format=ieee -Wno-array-bounds -Wno-stringop-overread -Wno-stringop-overflow -DSTM32F4XX -DSTM32F40_41xxx -DHSE_VALUE=8000000 -DUSE_STDPERIPH_DRIVER -Os -Werror  -I/home/broland/auto-uav/crazyflie-firmware/src -Isrc -DTOF_OVER_CPX   -c -o src/hal/src/sensors_bmi088_bmp3xx.o /home/broland/auto-uav/crazyflie-firmware/src/hal/src/sensors_bmi088_bmp3xx.c

source_src/hal/src/sensors_bmi088_bmp3xx.o := /home/broland/auto-uav/crazyflie-firmware/src/hal/src/sensors_bmi088_bmp3xx.c

deps_src/hal/src/sensors_bmi088_bmp3xx.o := \
    $(wildcard include/config/sensors/ignore/barometer/fail.h) \
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
  /home/broland/auto-uav/crazyflie-firmware/src/hal/interface/sensors_bmi088_bmp3xx.h \
  /home/broland/auto-uav/crazyflie-firmware/src/hal/interface/sensors.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/stabilizer_types.h \
  /usr/lib/gcc/arm-none-eabi/10.3.1/include/stdint.h \
  /usr/lib/gcc/arm-none-eabi/10.3.1/include/stdbool.h \
  /home/broland/auto-uav/crazyflie-firmware/src/hal/interface/imu_types.h \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/lighthouse/lighthouse_types.h \
  /home/broland/auto-uav/crazyflie-firmware/src/config/stm32fxxx.h \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/CMSIS/STM32F4xx/Include/stm32f4xx.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/CMSIS/CMSIS/Core/Include/core_cm4.h \
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
  /home/broland/auto-uav/crazyflie-firmware/src/hal/interface/imu.h \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/filter.h \
  /home/broland/auto-uav/crazyflie-firmware/src/hal/interface/imu_types.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include/FreeRTOS.h \
  /home/broland/auto-uav/crazyflie-firmware/src/config/FreeRTOSConfig.h \
    $(wildcard include/config/h.h) \
    $(wildcard include/config/debug/queue/monitor.h) \
  /home/broland/auto-uav/crazyflie-firmware/src/config/config.h \
    $(wildcard include/config/h/.h) \
    $(wildcard include/config/block/address.h) \
  /home/broland/auto-uav/crazyflie-firmware/src/drivers/interface/nrf24l01.h \
  /home/broland/auto-uav/crazyflie-firmware/src/drivers/interface/nRF24L01reg.h \
  /home/broland/auto-uav/crazyflie-firmware/src/config/trace.h \
  /home/broland/auto-uav/crazyflie-firmware/src/hal/interface/usec_time.h \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/cfassert.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include/projdefs.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include/portable.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include/deprecated_definitions.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/portable/GCC/ARM_CM4F/portmacro.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include/mpu_wrappers.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include/semphr.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include/queue.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include/task.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include/list.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include/task.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/system.h \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/configblock.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/param.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/param_logic.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/crtp.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/log.h \
    $(wildcard include/config/debug/log/enable.h) \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/debug.h \
    $(wildcard include/config/debug/print/on/uart1.h) \
  /home/broland/auto-uav/crazyflie-firmware/src/config/config.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/console.h \
  /home/broland/auto-uav/crazyflie-firmware/src/utils/interface/eprintf.h \
  /usr/lib/gcc/arm-none-eabi/10.3.1/include/stdarg.h \
  /home/broland/auto-uav/crazyflie-firmware/src/config/nvicconf.h \
  /home/broland/auto-uav/crazyflie-firmware/src/hal/interface/ledseq.h \
  /home/broland/auto-uav/crazyflie-firmware/src/drivers/interface/led.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/sound.h \
  /home/broland/auto-uav/crazyflie-firmware/src/drivers/interface/i2cdev.h \
    $(wildcard include/config/deck/backend/deckctrl/max/decks.h) \
  /home/broland/auto-uav/crazyflie-firmware/src/drivers/interface/i2c_drv.h \
  /home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include/queue.h \
  /home/broland/auto-uav/crazyflie-firmware/src/drivers/bosch/interface/bmi088.h \
  /home/broland/auto-uav/crazyflie-firmware/src/drivers/bosch/interface/bmi088_defs.h \
    $(wildcard include/config/0/reg.h) \
    $(wildcard include/config/1/reg.h) \
    $(wildcard include/config/stream/error.h) \
    $(wildcard include/config/stream/size.h) \
    $(wildcard include/config/0/mask.h) \
    $(wildcard include/config/1/mask.h) \
    $(wildcard include/config/check.h) \
  /home/broland/auto-uav/crazyflie-firmware/src/drivers/bosch/interface/bmp3.h \
  /home/broland/auto-uav/crazyflie-firmware/src/drivers/bosch/interface/bmp3_defs.h \
    $(wildcard include/config/1/addr.h) \
    $(wildcard include/config/2/addr.h) \
  /home/broland/auto-uav/crazyflie-firmware/src/drivers/bosch/interface/bstdr_types.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/static_mem.h \
  /home/broland/auto-uav/crazyflie-firmware/src/modules/interface/estimator/estimator.h \
    $(wildcard include/config/estimator/kalman/enable.h) \
    $(wildcard include/config/estimator/ukf/enable.h) \
    $(wildcard include/config/estimator/oot.h) \
  /home/broland/auto-uav/crazyflie-firmware/src/hal/src/sensors_bmi088_common.h \
  /home/broland/auto-uav/crazyflie-firmware/src/platform/interface/platform_defaults.h \
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
  /home/broland/auto-uav/crazyflie-firmware/src/platform/interface/platform_defaults_cf2.h \
    $(wildcard include/config/crazyflie/thrust/upgrade/kit.h) \
    $(wildcard include/config/enable/thrust/bat/compensated.h) \
    $(wildcard include/config/crazyflie/21/plus.h) \
    $(wildcard include/config/crazyflie/legacy/propellers.h) \

src/hal/src/sensors_bmi088_bmp3xx.o: $(deps_src/hal/src/sensors_bmi088_bmp3xx.o)

$(deps_src/hal/src/sensors_bmi088_bmp3xx.o):
