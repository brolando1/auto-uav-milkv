EXTRA_CFLAGS += -Isrc

EXTRA_LDFLAGS += -specs=nosys.specs -Wl

CRAZYFLIE_BASE := ../../crazyflie-firmware

#
# We override the default OOT_CONFIG here, we could also name our config
# to oot-config and that would be the default.
#
OOT_CONFIG := $(PWD)/app-config

include $(CRAZYFLIE_BASE)/tools/make/oot.mk