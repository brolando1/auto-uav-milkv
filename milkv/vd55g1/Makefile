# VD55G1 driver for the Milk-V Duo S. Build on the board: make
#
#   build/libsns_vd55g1.so  sensor driver for the Sophgo ISP (stSnsVd55g1_Obj)
#   build/libvd55cam.so     capture library (sensor + VI + ISP + VPSS), used by camera.py
#   build/vd55cam_test      frame rate / exposure check, saves a PGM
#   build/vd55g1_ctl        I2C-only sensor check

CC      ?= gcc
CFLAGS  ?= -O2 -Wall -Wextra
CFLAGS  += -fPIC -Isensor -Icam -Isdk/mpi -Isdk/isp -Isdk/uapi \
           -DARCH_CV181X -D__CV181X__ -D__SOC_MARS__

# Sophgo media libraries installed on the board
SOPH_LIB := /mnt/system/usr/lib
SOPH_LDFLAGS := -L$(SOPH_LIB) -L$(SOPH_LIB)/3rd \
	-Wl,-rpath,$(SOPH_LIB) -Wl,-rpath,$(SOPH_LIB)/3rd \
	-Wl,--no-as-needed -Wl,--allow-shlib-undefined
SOPH_LIBS := -lsys -lvi -lvpss -lisp -lisp_algo -lae -lawb -lcvi_bin -lcvi_bin_isp -lmisc -lvo -lgdc -lini -lpthread -lm

B := build
SNS_OBJS := $(B)/vd55g1.o $(B)/vd55g1_cmos.o $(B)/vd55g1_sensor_ctl.o

all: $(B)/libsns_vd55g1.so $(B)/libvd55cam.so $(B)/vd55cam_test $(B)/vd55g1_ctl

$(B):
	mkdir -p $@

$(B)/%.o: sensor/%.c sensor/*.h | $(B)
	$(CC) $(CFLAGS) -c -o $@ $<

$(B)/vd55cam.o: cam/vd55cam.c cam/vd55cam.h sensor/*.h | $(B)
	$(CC) $(CFLAGS) -c -o $@ $<

# the ISP/AE/AWB symbols come from the process that loads the sensor library
$(B)/libsns_vd55g1.so: $(SNS_OBJS)
	$(CC) -shared -o $@ $^ -Wl,--allow-shlib-undefined

$(B)/libvd55cam.so: $(B)/vd55cam.o $(SNS_OBJS)
	$(CC) -shared -o $@ $^ $(SOPH_LDFLAGS) $(SOPH_LIBS)

$(B)/vd55cam_test: tools/vd55cam_test.c $(B)/libvd55cam.so
	$(CC) $(CFLAGS) -o $@ $< -L$(B) -lvd55cam $(SOPH_LIBS) -Wl,-rpath,'$$ORIGIN' $(SOPH_LDFLAGS)

$(B)/vd55g1_ctl: tools/vd55g1_ctl.c $(B)/vd55g1.o
	$(CC) $(CFLAGS) -o $@ $^

clean:
	rm -rf $(B)

.PHONY: all clean
