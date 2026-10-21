/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Register access and start-up sequence for the ST VD55G1 over Linux i2c-dev.
 * Used by the Sophgo sensor driver (vd55g1_cmos.c) and vd55g1_ctl.
 * Register map and start-up sequence ported from
 * STMicroelectronics/vd55g1-linux-driver (GPL-2.0).
 */
#ifndef VD55G1_H
#define VD55G1_H

#include <stdbool.h>
#include <stdint.h>

#define VD55G1_I2C_ADDR		0x10
#define VD55G1_NATIVE_WIDTH	804
#define VD55G1_NATIVE_HEIGHT	704

/* Registers the ISP writes every frame (values little-endian) */
#define VD55G1_REG_MANUAL_ANALOG_GAIN		0x0501	/* 1: gain = 32 / (32 - val) */
#define VD55G1_REG_MANUAL_COARSE_EXPOSURE	0x0502	/* 2: lines */
#define VD55G1_REG_MANUAL_DIGITAL_GAIN(ch)	(0x0504 + 2 * (ch))	/* 2: 8.8 */
#define VD55G1_REG_FRAME_LENGTH_CTX0		0x050c	/* 4: lines */
#define VD55G1_REG_APPLIED_COARSE_EXPOSURE	0x00e8	/* 2 */
#define VD55G1_REG_APPLIED_ANALOG_GAIN		0x00ea	/* 2 */
#define VD55G1_REG_APPLIED_DIGITAL_GAIN		0x00ec	/* 2 */

#define VD55G1_AGAIN_MAX	28	/* 8x */
#define VD55G1_DGAIN_1X		256
#define VD55G1_EXPO_MAX_TERM	64	/* exposure <= frame length - 64 */
#define VD55G1_VBLANK_MIN	86

/* SYSTEM_FSM states */
#define VD55G1_FSM_READY_TO_BOOT	0x01
#define VD55G1_FSM_SW_STBY		0x02
#define VD55G1_FSM_STREAMING		0x03

enum vd55g1_pattern {
	VD55G1_PATTERN_OFF = 0,
	VD55G1_PATTERN_GREY_RAMP,	/* diagonal grey scale */
	VD55G1_PATTERN_NOISE,		/* pseudo-random noise */
};

struct vd55g1 {
	int fd;
	uint8_t addr;
	uint32_t model_id;
	uint32_t xclk_hz;
	uint32_t pixel_clock_hz;
	uint32_t line_length;
};

struct vd55g1_config {
	uint16_t width;		/* <= 804, centred in the pixel array */
	uint16_t height;	/* <= 704 */
	uint8_t bpp;		/* 8 (RAW8) or 10 (RAW10) */
	uint32_t mipi_rate;	/* bit/s per lane, 250-1200 Mbit/s */
	bool swap_pn;		/* invert clock + data lane polarity */
	uint32_t frame_length;	/* lines per frame; sets the frame rate */
	enum vd55g1_pattern pattern;
	/* false: the sensor's own auto-exposure; true: expo/again/dgain below,
	 * updated later by whoever drives the exposure (the Sophgo AE) */
	bool manual_exposure;
	uint16_t expo_lines;
	uint8_t again;		/* 0..VD55G1_AGAIN_MAX */
	uint16_t dgain;		/* 8.8, VD55G1_DGAIN_1X = 1x */
};

int vd55g1_open(struct vd55g1 *s, const char *i2c_dev, uint8_t addr);
void vd55g1_close(struct vd55g1 *s);

int vd55g1_read(struct vd55g1 *s, uint16_t reg, unsigned int len,
		uint32_t *val);
int vd55g1_write(struct vd55g1 *s, uint16_t reg, unsigned int len,
		 uint32_t val);

/* Steps 1-3: wait for boot ROM, identify, upload patch, reach SW standby. */
int vd55g1_power_on(struct vd55g1 *s, uint32_t xclk_hz);
/* Step 4: configure output, sensor stays in standby. */
int vd55g1_configure(struct vd55g1 *s, const struct vd55g1_config *cfg);
/* Step 6: start streaming. */
int vd55g1_stream_on(struct vd55g1 *s);
/* Steps 4 + 6. */
int vd55g1_start(struct vd55g1 *s, const struct vd55g1_config *cfg);
/* Line time of the last configuration, in ns. */
uint32_t vd55g1_line_time_ns(const struct vd55g1 *s);
/* Step 8: stop streaming, back to SW standby. */
int vd55g1_stop(struct vd55g1 *s);

int vd55g1_get_state(struct vd55g1 *s, uint8_t *state);
const char *vd55g1_state_name(uint8_t state);

#endif
