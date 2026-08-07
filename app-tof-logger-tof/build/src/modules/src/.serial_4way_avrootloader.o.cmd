cmd_src/modules/src/serial_4way_avrootloader.o := arm-none-eabi-gcc -Wp,-MD,src/modules/src/.serial_4way_avrootloader.o.d    -I/home/phheld/project/crazyflie-firmware/src/modules/src -Isrc/modules/src -D__firmware__ -fno-exceptions -Wall -Wmissing-braces -fno-strict-aliasing -ffunction-sections -fdata-sections -Wdouble-promotion -std=gnu11 -DCRAZYFLIE_FW   -I/home/phheld/project/crazyflie-firmware/vendor/CMSIS/CMSIS/Core/Include   -I/home/phheld/project/crazyflie-firmware/vendor/CMSIS/CMSIS/DSP/Include   -I/home/phheld/project/crazyflie-firmware/vendor/libdw1000/inc   -I/home/phheld/project/crazyflie-firmware/vendor/FreeRTOS/include   -I/home/phheld/project/crazyflie-firmware/vendor/FreeRTOS/portable/GCC/ARM_CM4F   -I/home/phheld/project/crazyflie-firmware/src/config   -I/home/phheld/project/crazyflie-firmware/src/platform/interface   -I/home/phheld/project/crazyflie-firmware/src/deck/interface   -I/home/phheld/project/crazyflie-firmware/src/deck/drivers/interface   -I/home/phheld/project/crazyflie-firmware/src/drivers/interface   -I/home/phheld/project/crazyflie-firmware/src/drivers/bosch/interface   -I/home/phheld/project/crazyflie-firmware/src/drivers/esp32/interface   -I/home/phheld/project/crazyflie-firmware/src/hal/interface   -I/home/phheld/project/crazyflie-firmware/src/modules/interface   -I/home/phheld/project/crazyflie-firmware/src/modules/interface/kalman_core   -I/home/phheld/project/crazyflie-firmware/src/modules/interface/lighthouse   -I/home/phheld/project/crazyflie-firmware/src/modules/interface/outlierfilter   -I/home/phheld/project/crazyflie-firmware/src/modules/interface/cpx   -I/home/phheld/project/crazyflie-firmware/src/modules/interface/p2pDTR   -I/home/phheld/project/crazyflie-firmware/src/modules/interface/controller   -I/home/phheld/project/crazyflie-firmware/src/modules/interface/estimator   -I/home/phheld/project/crazyflie-firmware/src/utils/interface   -I/home/phheld/project/crazyflie-firmware/src/utils/interface/kve   -I/home/phheld/project/crazyflie-firmware/src/utils/interface/lighthouse   -I/home/phheld/project/crazyflie-firmware/src/utils/interface/tdoa   -I/home/phheld/project/crazyflie-firmware/src/lib/FatFS   -I/home/phheld/project/crazyflie-firmware/src/lib/CMSIS/STM32F4xx/Include   -I/home/phheld/project/crazyflie-firmware/src/lib/STM32_USB_Device_Library/Core/inc   -I/home/phheld/project/crazyflie-firmware/src/lib/STM32_USB_OTG_Driver/inc   -I/home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc   -I/home/phheld/project/crazyflie-firmware/src/lib/vl53l1   -I/home/phheld/project/crazyflie-firmware/src/lib/vl53l1/core/inc   -I/home/phheld/project/tof-camera-logger/app-tof-logger-tof/build/include/generated -fno-delete-null-pointer-checks -Wno-unused-but-set-variable -Wno-unused-const-variable -fomit-frame-pointer -fno-var-tracking-assignments -Wno-pointer-sign -fno-strict-overflow -fconserve-stack -Werror=implicit-int -Werror=date-time -DCC_HAVE_ASM_GOTO -mcpu=cortex-m4 -mthumb -mfloat-abi=hard -mfpu=fpv4-sp-d16 -g3 -fno-math-errno -DARM_MATH_CM4 -D__FPU_PRESENT=1 -mfp16-format=ieee -Wno-array-bounds -Wno-stringop-overread -Wno-stringop-overflow -DSTM32F4XX -DSTM32F40_41xxx -DHSE_VALUE=8000000 -DUSE_STDPERIPH_DRIVER -Os -Werror  -I/home/phheld/project/crazyflie-firmware/src -Isrc   -c -o src/modules/src/serial_4way_avrootloader.o /home/phheld/project/crazyflie-firmware/src/modules/src/serial_4way_avrootloader.c

source_src/modules/src/serial_4way_avrootloader.o := /home/phheld/project/crazyflie-firmware/src/modules/src/serial_4way_avrootloader.c

deps_src/modules/src/serial_4way_avrootloader.o := \
  /usr/lib/gcc/arm-none-eabi/13.2.1/include/stdbool.h \
  /usr/lib/gcc/arm-none-eabi/13.2.1/include/stdint.h \
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
  /home/phheld/project/crazyflie-firmware/vendor/FreeRTOS/include/FreeRTOS.h \
  /home/phheld/project/crazyflie-firmware/src/config/FreeRTOSConfig.h \
    $(wildcard include/config/h.h) \
    $(wildcard include/config/debug/queue/monitor.h) \
  /home/phheld/project/crazyflie-firmware/src/config/config.h \
    $(wildcard include/config/h/.h) \
    $(wildcard include/config/block/address.h) \
  /home/phheld/project/crazyflie-firmware/src/drivers/interface/nrf24l01.h \
  /home/phheld/project/crazyflie-firmware/src/drivers/interface/nRF24L01reg.h \
  /home/phheld/project/crazyflie-firmware/src/config/trace.h \
  /home/phheld/project/crazyflie-firmware/src/hal/interface/usec_time.h \
  /home/phheld/project/crazyflie-firmware/src/utils/interface/cfassert.h \
  /home/phheld/project/crazyflie-firmware/vendor/FreeRTOS/include/projdefs.h \
  /home/phheld/project/crazyflie-firmware/vendor/FreeRTOS/include/portable.h \
  /home/phheld/project/crazyflie-firmware/vendor/FreeRTOS/include/deprecated_definitions.h \
  /home/phheld/project/crazyflie-firmware/vendor/FreeRTOS/portable/GCC/ARM_CM4F/portmacro.h \
  /home/phheld/project/crazyflie-firmware/vendor/FreeRTOS/include/mpu_wrappers.h \
  /home/phheld/project/crazyflie-firmware/vendor/FreeRTOS/include/task.h \
  /home/phheld/project/crazyflie-firmware/vendor/FreeRTOS/include/list.h \
  /home/phheld/project/crazyflie-firmware/src/platform/interface/platform.h \
    $(wildcard include/config/sensors/bmi088/bmp3xx.h) \
    $(wildcard include/config/sensors/bmi088/spi.h) \
    $(wildcard include/config/sensors/mpu9250/lps25h.h) \
    $(wildcard include/config/sensors/bosch.h) \
  /home/phheld/project/crazyflie-firmware/src/drivers/interface/motors.h \
    $(wildcard include/config/motors/esc/protocol/oneshot125.h) \
    $(wildcard include/config/motors/esc/protocol/oneshot42.h) \
    $(wildcard include/config/motors/esc/protocol/dshot.h) \
    $(wildcard include/config/motors/dshot/pwm/150khz.h) \
    $(wildcard include/config/motors/dshot/pwm/300khz.h) \
    $(wildcard include/config/motors/dshot/pwm/600khz.h) \
  /home/phheld/project/crazyflie-firmware/src/config/config.h \
  /home/phheld/project/crazyflie-firmware/src/config/stm32fxxx.h \
  /home/phheld/project/crazyflie-firmware/src/lib/CMSIS/STM32F4xx/Include/stm32f4xx.h \
  /home/phheld/project/crazyflie-firmware/vendor/CMSIS/CMSIS/Core/Include/core_cm4.h \
  /home/phheld/project/crazyflie-firmware/vendor/CMSIS/CMSIS/Core/Include/cmsis_version.h \
  /home/phheld/project/crazyflie-firmware/vendor/CMSIS/CMSIS/Core/Include/cmsis_compiler.h \
  /home/phheld/project/crazyflie-firmware/vendor/CMSIS/CMSIS/Core/Include/cmsis_gcc.h \
  /home/phheld/project/crazyflie-firmware/vendor/CMSIS/CMSIS/Core/Include/mpu_armv7.h \
  /home/phheld/project/crazyflie-firmware/src/lib/CMSIS/STM32F4xx/Include/system_stm32f4xx.h \
  /home/phheld/project/crazyflie-firmware/src/config/stm32f4xx_conf.h \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_adc.h \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_crc.h \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_dbgmcu.h \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_dma.h \
    $(wildcard include/config/it.h) \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_exti.h \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_flash.h \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_gpio.h \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_i2c.h \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_iwdg.h \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_pwr.h \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_rcc.h \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_rtc.h \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_sdio.h \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_spi.h \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_syscfg.h \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_tim.h \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_usart.h \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_wwdg.h \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_misc.h \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_cryp.h \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_hash.h \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_rng.h \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_can.h \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_dac.h \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_dcmi.h \
  /home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_fsmc.h \
  /home/phheld/project/crazyflie-firmware/src/drivers/interface/watchdog.h \
  /home/phheld/project/crazyflie-firmware/src/modules/interface/serial_4way.h \
  /home/phheld/project/crazyflie-firmware/src/modules/interface/serial_4way_impl.h \
  /home/phheld/project/crazyflie-firmware/src/modules/interface/serial_4way_avrootloader.h \

src/modules/src/serial_4way_avrootloader.o: $(deps_src/modules/src/serial_4way_avrootloader.o)

$(deps_src/modules/src/serial_4way_avrootloader.o):
