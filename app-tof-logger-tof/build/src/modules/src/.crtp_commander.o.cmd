cmd_src/modules/src/crtp_commander.o := arm-none-eabi-gcc -Wp,-MD,src/modules/src/.crtp_commander.o.d    -I/home/phheld/project/crazyflie-firmware/src/modules/src -Isrc/modules/src -D__firmware__ -fno-exceptions -Wall -Wmissing-braces -fno-strict-aliasing -ffunction-sections -fdata-sections -Wdouble-promotion -std=gnu11 -DCRAZYFLIE_FW   -I/home/phheld/project/crazyflie-firmware/vendor/CMSIS/CMSIS/Core/Include   -I/home/phheld/project/crazyflie-firmware/vendor/CMSIS/CMSIS/DSP/Include   -I/home/phheld/project/crazyflie-firmware/vendor/libdw1000/inc   -I/home/phheld/project/crazyflie-firmware/vendor/FreeRTOS/include   -I/home/phheld/project/crazyflie-firmware/vendor/FreeRTOS/portable/GCC/ARM_CM4F   -I/home/phheld/project/crazyflie-firmware/src/config   -I/home/phheld/project/crazyflie-firmware/src/platform/interface   -I/home/phheld/project/crazyflie-firmware/src/deck/interface   -I/home/phheld/project/crazyflie-firmware/src/deck/drivers/interface   -I/home/phheld/project/crazyflie-firmware/src/drivers/interface   -I/home/phheld/project/crazyflie-firmware/src/drivers/bosch/interface   -I/home/phheld/project/crazyflie-firmware/src/drivers/esp32/interface   -I/home/phheld/project/crazyflie-firmware/src/hal/interface   -I/home/phheld/project/crazyflie-firmware/src/modules/interface   -I/home/phheld/project/crazyflie-firmware/src/modules/interface/kalman_core   -I/home/phheld/project/crazyflie-firmware/src/modules/interface/lighthouse   -I/home/phheld/project/crazyflie-firmware/src/modules/interface/outlierfilter   -I/home/phheld/project/crazyflie-firmware/src/modules/interface/cpx   -I/home/phheld/project/crazyflie-firmware/src/modules/interface/p2pDTR   -I/home/phheld/project/crazyflie-firmware/src/modules/interface/controller   -I/home/phheld/project/crazyflie-firmware/src/modules/interface/estimator   -I/home/phheld/project/crazyflie-firmware/src/utils/interface   -I/home/phheld/project/crazyflie-firmware/src/utils/interface/kve   -I/home/phheld/project/crazyflie-firmware/src/utils/interface/lighthouse   -I/home/phheld/project/crazyflie-firmware/src/utils/interface/tdoa   -I/home/phheld/project/crazyflie-firmware/src/lib/FatFS   -I/home/phheld/project/crazyflie-firmware/src/lib/CMSIS/STM32F4xx/Include   -I/home/phheld/project/crazyflie-firmware/src/lib/STM32_USB_Device_Library/Core/inc   -I/home/phheld/project/crazyflie-firmware/src/lib/STM32_USB_OTG_Driver/inc   -I/home/phheld/project/crazyflie-firmware/src/lib/STM32F4xx_StdPeriph_Driver/inc   -I/home/phheld/project/crazyflie-firmware/src/lib/vl53l1   -I/home/phheld/project/crazyflie-firmware/src/lib/vl53l1/core/inc   -I/home/phheld/project/tof-camera-logger/app-tof-logger-tof/build/include/generated -fno-delete-null-pointer-checks -Wno-unused-but-set-variable -Wno-unused-const-variable -fomit-frame-pointer -fno-var-tracking-assignments -Wno-pointer-sign -fno-strict-overflow -fconserve-stack -Werror=implicit-int -Werror=date-time -DCC_HAVE_ASM_GOTO -mcpu=cortex-m4 -mthumb -mfloat-abi=hard -mfpu=fpv4-sp-d16 -g3 -fno-math-errno -DARM_MATH_CM4 -D__FPU_PRESENT=1 -mfp16-format=ieee -Wno-array-bounds -Wno-stringop-overread -Wno-stringop-overflow -DSTM32F4XX -DSTM32F40_41xxx -DHSE_VALUE=8000000 -DUSE_STDPERIPH_DRIVER -Os -Werror  -I/home/phheld/project/crazyflie-firmware/src -Isrc   -c -o src/modules/src/crtp_commander.o /home/phheld/project/crazyflie-firmware/src/modules/src/crtp_commander.c

source_src/modules/src/crtp_commander.o := /home/phheld/project/crazyflie-firmware/src/modules/src/crtp_commander.c

deps_src/modules/src/crtp_commander.o := \
  /usr/lib/gcc/arm-none-eabi/13.2.1/include/stdbool.h \
  /usr/lib/gcc/arm-none-eabi/13.2.1/include/stddef.h \
  /home/phheld/project/crazyflie-firmware/src/modules/interface/crtp_commander.h \
  /usr/lib/gcc/arm-none-eabi/13.2.1/include/stdint.h \
  /home/phheld/project/crazyflie-firmware/src/modules/interface/stabilizer_types.h \
  /home/phheld/project/crazyflie-firmware/src/hal/interface/imu_types.h \
  /home/phheld/project/crazyflie-firmware/src/utils/interface/lighthouse/lighthouse_types.h \
  /home/phheld/project/crazyflie-firmware/src/modules/interface/crtp.h \
  /home/phheld/project/crazyflie-firmware/src/utils/interface/cfassert.h \
  /home/phheld/project/crazyflie-firmware/src/modules/interface/commander.h \
  /home/phheld/project/crazyflie-firmware/src/config/config.h \
    $(wildcard include/config/h/.h) \
    $(wildcard include/config/block/address.h) \
  /home/phheld/project/crazyflie-firmware/src/drivers/interface/nrf24l01.h \
  /home/phheld/project/crazyflie-firmware/src/drivers/interface/nRF24L01reg.h \
  /home/phheld/project/crazyflie-firmware/src/config/trace.h \
  /home/phheld/project/crazyflie-firmware/src/hal/interface/usec_time.h \
  /home/phheld/project/crazyflie-firmware/src/modules/interface/crtp.h \

src/modules/src/crtp_commander.o: $(deps_src/modules/src/crtp_commander.o)

$(deps_src/modules/src/crtp_commander.o):
