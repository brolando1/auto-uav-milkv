EXTRA_CFLAGS += -Isrc

# ToF frames go out over CPX/wifi instead of CRTP/radio. Comment this out to
# get the old radio path back.
EXTRA_CFLAGS += -DTOF_OVER_CPX

EXTRA_LDFLAGS += -specs=nosys.specs -Wl

CRAZYFLIE_BASE := $(HOME)/auto-uav/crazyflie-firmware

#
# We override the default OOT_CONFIG here, we could also name our config
# to oot-config and that would be the default.
#
OOT_CONFIG := $(PWD)/app-config

include $(CRAZYFLIE_BASE)/tools/make/oot.mk