cmd_src/platform/built-in.o :=  arm-none-eabi-gcc -mcpu=cortex-m4 -mthumb -mfloat-abi=hard -mfpu=fpv4-sp-d16  -r -o src/platform/built-in.o src/platform/src/built-in.o
