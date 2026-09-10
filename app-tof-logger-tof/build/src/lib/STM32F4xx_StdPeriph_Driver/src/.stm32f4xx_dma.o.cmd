cmd_src/lib/STM32F4xx_StdPeriph_Driver/src/stm32f4xx_dma.o := arm-none-eabi-gcc -Wp,-MD,src/lib/STM32F4xx_StdPeriph_Driver/src/.stm32f4xx_dma.o.d    -I/home/broland/auto-uav/crazyflie-firmware/src/lib -Isrc/lib -D__firmware__ -fno-exceptions -Wall -Wmissing-braces -fno-strict-aliasing -ffunction-sections -fdata-sections -Wdouble-promotion -std=gnu11 -DCRAZYFLIE_FW   -I/home/broland/auto-uav/crazyflie-firmware/vendor/CMSIS/CMSIS/Core/Include   -I/home/broland/auto-uav/crazyflie-firmware/vendor/CMSIS/CMSIS/DSP/Include   -I/home/broland/auto-uav/crazyflie-firmware/vendor/libdw1000/inc   -I/home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/include   -I/home/broland/auto-uav/crazyflie-firmware/vendor/FreeRTOS/portable/GCC/ARM_CM4F   -I/home/broland/auto-uav/crazyflie-firmware/src/config   -I/home/broland/auto-uav/crazyflie-firmware/src/platform/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/deck/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/deck/drivers/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/drivers/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/drivers/bosch/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/drivers/esp32/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/hal/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/kalman_core   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/lighthouse   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/outlierfilter   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/cpx   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/p2pDTR   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/controller   -I/home/broland/auto-uav/crazyflie-firmware/src/modules/interface/estimator   -I/home/broland/auto-uav/crazyflie-firmware/src/utils/interface   -I/home/broland/auto-uav/crazyflie-firmware/src/utils/interface/kve   -I/home/broland/auto-uav/crazyflie-firmware/src/utils/interface/lighthouse   -I/home/broland/auto-uav/crazyflie-firmware/src/utils/interface/tdoa   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/FatFS   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/CMSIS/STM32F4xx/Include   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/STM32_USB_Device_Library/Core/inc   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/STM32_USB_OTG_Driver/inc   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/vl53l1   -I/home/broland/auto-uav/crazyflie-firmware/src/lib/vl53l1/core/inc   -I/home/broland/Desktop/milkv-drone/app-tof-logger-tof/build/include/generated -fno-delete-null-pointer-checks -Wno-unused-but-set-variable -Wno-unused-const-variable -fomit-frame-pointer -fno-var-tracking-assignments -Wno-pointer-sign -fno-strict-overflow -fconserve-stack -Werror=implicit-int -Werror=date-time -DCC_HAVE_ASM_GOTO -mcpu=cortex-m4 -mthumb -mfloat-abi=hard -mfpu=fpv4-sp-d16 -g3 -fno-math-errno -DARM_MATH_CM4 -D__FPU_PRESENT=1 -mfp16-format=ieee -Wno-array-bounds -Wno-stringop-overread -Wno-stringop-overflow -DSTM32F4XX -DSTM32F40_41xxx -DHSE_VALUE=8000000 -DUSE_STDPERIPH_DRIVER -Os -Werror  -I/home/broland/auto-uav/crazyflie-firmware/src -Isrc -DTOF_OVER_CPX   -c -o src/lib/STM32F4xx_StdPeriph_Driver/src/stm32f4xx_dma.o /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/src/stm32f4xx_dma.c

source_src/lib/STM32F4xx_StdPeriph_Driver/src/stm32f4xx_dma.o := /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/src/stm32f4xx_dma.c

deps_src/lib/STM32F4xx_StdPeriph_Driver/src/stm32f4xx_dma.o := \
    $(wildcard include/config/it.h) \
  /home/broland/auto-uav/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc/stm32f4xx_dma.h \
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

src/lib/STM32F4xx_StdPeriph_Driver/src/stm32f4xx_dma.o: $(deps_src/lib/STM32F4xx_StdPeriph_Driver/src/stm32f4xx_dma.o)

$(deps_src/lib/STM32F4xx_StdPeriph_Driver/src/stm32f4xx_dma.o):
