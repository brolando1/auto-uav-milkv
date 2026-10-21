// SPDX-License-Identifier: GPL-2.0-only
/*
 * Register access and start-up sequence for the ST VD55G1 over Linux i2c-dev.
 * Used by the Sophgo sensor driver (vd55g1_cmos.c) and vd55g1_ctl.
 * Register map and start-up sequence ported from
 * STMicroelectronics/vd55g1-linux-driver (GPL-2.0).
 *
 * Register addresses are 16-bit, sent MSB first; register values are
 * little-endian (1, 2 or 4 bytes).
 */
#include "vd55g1.h"
#include "vd55g1_patch.h"

#include <errno.h>
#include <fcntl.h>
#include <linux/i2c.h>
#include <linux/i2c-dev.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

/* Register map (subset used here) */
#define REG_MODEL_ID			0x0000	/* 4 */
#define REG_FWPATCH_REVISION		0x0012	/* 2 */
#define REG_SYSTEM_FSM			0x001c	/* 1 */
#define REG_APPLIED_COARSE_EXPOSURE	0x00e8	/* 2 */
#define REG_BOOT			0x0200	/* 1 */
#define REG_STBY			0x0201	/* 1 */
#define REG_STREAMING			0x0202	/* 1 */
#define REG_EXT_CLOCK			0x0220	/* 4 */
#define REG_MIPI_DATA_RATE		0x0224	/* 4 */
#define REG_LINE_LENGTH			0x0300	/* 2 */
#define REG_ORIENTATION			0x0302	/* 1 */
#define REG_PATGEN_CTRL			0x0304	/* 2 */
#define REG_AE_FORCE_COLDSTART		0x0308	/* 1 */
#define REG_VT_CTRL			0x0309	/* 1 */
#define REG_FORMAT_CTRL			0x030a	/* 1 */
#define REG_OIF_CTRL			0x030c	/* 2 */
#define REG_OIF_IMG_CTRL		0x030f	/* 1 */
#define REG_EXPOSURE_USE_CASES		0x0312	/* 1 */
#define REG_ISL_ENABLE			0x0326	/* 2 */
#define REG_EXPOSURE_MAX_COARSE		0x0372	/* 2 */
#define REG_AE_COLDSTART_EXP_TIME	0x0374	/* 4 */
#define REG_DUSTER_CTRL			0x03ae	/* 1 */
#define REG_CTX_REPEAT_COUNT_CTX0	0x03dc	/* 2 */
#define REG_NEXT_CTX			0x03e4	/* 2 */
#define REG_AE_TARGET_PERCENTAGE	0x0486	/* 1 */
#define REG_READOUT_CTRL		0x052e	/* 1 */
#define REG_FWPATCH_START_ADDR		0x2000

/* Per-context registers: base + 0x50 * ctx */
#define CTX_OFFSET			0x50
#define REG_EXP_MODE(c)			(0x0500 + CTX_OFFSET * (c))	/* 1 */
#define REG_FRAME_LENGTH(c)		(0x050c + CTX_OFFSET * (c))	/* 4 */
#define REG_Y_START(c)			(0x0510 + CTX_OFFSET * (c))	/* 2 */
#define REG_Y_HEIGHT(c)			(0x0512 + CTX_OFFSET * (c))	/* 2 */
#define REG_X_START(c)			(0x0514 + CTX_OFFSET * (c))	/* 2 */
#define REG_X_WIDTH(c)			(0x0516 + CTX_OFFSET * (c))	/* 2 */
#define REG_GPIO_0_CTRL(c)		(0x051d + CTX_OFFSET * (c))	/* 1 */
#define REG_DARKCAL_PEDESTAL(c)		(0x0526 + CTX_OFFSET * (c))	/* 2 */
#define REG_VT_MODE(c)			(0x0536 + CTX_OFFSET * (c))	/* 1 */
#define REG_MASK_FRAME_CTRL(c)		(0x0537 + CTX_OFFSET * (c))	/* 1 */
#define AWU_CTX				3

/* Values */
#define MODEL_ID_CUT2			0x53354731
#define MODEL_ID_CUT3			0x53354733
#define FWPATCH_REVISION		0x0209	/* 2.9 */
#define BOOT_BOOT			1
#define BOOT_PATCH_AND_BOOT		2
#define STBY_START_STREAM		1
#define STREAMING_STOP_STREAM		1
#define EXP_MODE_AUTO			0
#define EXP_MODE_MANUAL			2
#define GPIO_MODE_IN			0x01
#define DUSTER_ON			0x13	/* ring | dynamic | enable */
#define PATGEN_ENABLE			0x01
#define PATGEN_TYPE_SHIFT		4
#define MIPI_DT_RAW8			0x2a
#define MIPI_DT_RAW10			0x2b
#define DARKCAL_PEDESTAL_DEF		0x40
#define AE_TARGET_DEF			27	/* percent */
#define EXPOSURE_MAX_COARSE_DEF		0x7fff

/* Timing constants from the ST driver */
#define LINE_LENGTH_MIN			1128
#define MIPI_MARGIN			900
#define VBLANK_MIN			86
#define EXPO_DEF			500	/* lines */
#define AGAIN_DEF			19
#define POLL_TIMEOUT_MS			500

static int i2c_xfer(struct vd55g1 *s, struct i2c_msg *msgs, int n)
{
	struct i2c_rdwr_ioctl_data data = { .msgs = msgs, .nmsgs = n };

	if (ioctl(s->fd, I2C_RDWR, &data) < 0)
		return -errno;
	return 0;
}

int vd55g1_read(struct vd55g1 *s, uint16_t reg, unsigned int len,
		uint32_t *val)
{
	uint8_t addr[2] = { reg >> 8, reg & 0xff };
	uint8_t buf[4] = { 0 };
	struct i2c_msg msgs[2] = {
		{ .addr = s->addr, .flags = 0, .len = 2, .buf = addr },
		{ .addr = s->addr, .flags = I2C_M_RD, .len = len, .buf = buf },
	};
	int ret;

	ret = i2c_xfer(s, msgs, 2);
	if (ret) {
		fprintf(stderr, "vd55g1: read 0x%04x failed: %s\n", reg,
			strerror(-ret));
		return ret;
	}
	*val = buf[0] | buf[1] << 8 | buf[2] << 16 | (uint32_t)buf[3] << 24;
	return 0;
}

static int write_block(struct vd55g1 *s, uint16_t reg, const uint8_t *data,
		       size_t len)
{
	uint8_t buf[2 + 256];
	struct i2c_msg msg = { .addr = s->addr, .flags = 0, .buf = buf };
	int ret;

	/* Chunked: the sensor auto-increments the register address. */
	while (len) {
		size_t n = len > 256 ? 256 : len;

		buf[0] = reg >> 8;
		buf[1] = reg & 0xff;
		memcpy(buf + 2, data, n);
		msg.len = 2 + n;
		ret = i2c_xfer(s, &msg, 1);
		if (ret) {
			fprintf(stderr, "vd55g1: write 0x%04x failed: %s\n",
				reg, strerror(-ret));
			return ret;
		}
		reg += n;
		data += n;
		len -= n;
	}
	return 0;
}

int vd55g1_write(struct vd55g1 *s, uint16_t reg, unsigned int len,
		 uint32_t val)
{
	uint8_t buf[4] = { val, val >> 8, val >> 16, val >> 24 };

	return write_block(s, reg, buf, len);
}

static void sleep_ms(unsigned int ms)
{
	struct timespec ts = { ms / 1000, (ms % 1000) * 1000000L };

	nanosleep(&ts, NULL);
}

/* Poll an 8-bit register until it equals @want, like regmap_read_poll_timeout. */
static int poll_reg(struct vd55g1 *s, uint16_t reg, uint8_t want)
{
	uint32_t val;
	int waited, ret;

	for (waited = 0; waited <= POLL_TIMEOUT_MS; waited += 2) {
		ret = vd55g1_read(s, reg, 1, &val);
		if (ret)
			return ret;
		if (val == want)
			return 0;
		sleep_ms(2);
	}
	fprintf(stderr, "vd55g1: timeout waiting for 0x%04x == 0x%02x (is 0x%02x)\n",
		reg, want, val);
	return -ETIMEDOUT;
}

int vd55g1_get_state(struct vd55g1 *s, uint8_t *state)
{
	uint32_t val;
	int ret = vd55g1_read(s, REG_SYSTEM_FSM, 1, &val);

	*state = val;
	return ret;
}

const char *vd55g1_state_name(uint8_t state)
{
	switch (state) {
	case VD55G1_FSM_READY_TO_BOOT:	return "ready to boot";
	case VD55G1_FSM_SW_STBY:	return "standby";
	case VD55G1_FSM_STREAMING:	return "streaming";
	case 0x04:			return "auto-wake-up streaming";
	default:			return "unknown";
	}
}

int vd55g1_open(struct vd55g1 *s, const char *i2c_dev, uint8_t addr)
{
	memset(s, 0, sizeof(*s));
	s->addr = addr;
	s->fd = open(i2c_dev, O_RDWR);
	if (s->fd < 0) {
		fprintf(stderr, "vd55g1: cannot open %s: %s\n", i2c_dev,
			strerror(errno));
		return -errno;
	}
	return 0;
}

void vd55g1_close(struct vd55g1 *s)
{
	if (s->fd >= 0)
		close(s->fd);
	s->fd = -1;
}

int vd55g1_power_on(struct vd55g1 *s, uint32_t xclk_hz)
{
	uint32_t patch;
	uint8_t state;
	int ret;

	/* Step 1: the boot ROM must have reached "ready to boot". */
	ret = vd55g1_get_state(s, &state);
	if (ret)
		return ret;
	if (state == VD55G1_FSM_SW_STBY || state == VD55G1_FSM_STREAMING) {
		/* Already booted and patched by an earlier run. */
		ret = vd55g1_read(s, REG_MODEL_ID, 4, &s->model_id);
		s->xclk_hz = xclk_hz;
		return ret;
	}
	ret = poll_reg(s, REG_SYSTEM_FSM, VD55G1_FSM_READY_TO_BOOT);
	if (ret)
		return ret;

	/* Step 2: identify. */
	ret = vd55g1_read(s, REG_MODEL_ID, 4, &s->model_id);
	if (ret)
		return ret;
	if (s->model_id != MODEL_ID_CUT2 && s->model_id != MODEL_ID_CUT3) {
		fprintf(stderr, "vd55g1: unexpected model id 0x%08x\n",
			s->model_id);
		return -ENODEV;
	}

	/* Tell the sensor its input clock before it boots. */
	s->xclk_hz = xclk_hz;
	ret = vd55g1_write(s, REG_EXT_CLOCK, 4, xclk_hz);
	if (ret)
		return ret;

	/* Step 3: cut 2 needs the firmware patch, cut 3 boots as is. */
	if (s->model_id == MODEL_ID_CUT2) {
		ret = write_block(s, REG_FWPATCH_START_ADDR, vd55g1_patch_array,
				  sizeof(vd55g1_patch_array));
		if (ret)
			return ret;
		ret = vd55g1_write(s, REG_BOOT, 1, BOOT_PATCH_AND_BOOT);
		if (ret)
			return ret;
		ret = poll_reg(s, REG_BOOT, 0);
		if (ret)
			return ret;
		ret = vd55g1_read(s, REG_FWPATCH_REVISION, 2, &patch);
		if (ret)
			return ret;
		if (patch != FWPATCH_REVISION) {
			fprintf(stderr, "vd55g1: bad patch version %u.%u\n",
				patch >> 8, patch & 0xff);
			return -EIO;
		}
	} else {
		ret = vd55g1_write(s, REG_BOOT, 1, BOOT_BOOT);
		if (ret)
			return ret;
		ret = poll_reg(s, REG_BOOT, 0);
		if (ret)
			return ret;
	}

	return poll_reg(s, REG_SYSTEM_FSM, VD55G1_FSM_SW_STBY);
}

/* Same clock tree derivation as vd55g1_prepare_clock_tree(). */
static uint32_t pixel_clock(uint32_t mipi_rate)
{
	uint64_t sys_clk;
	uint32_t mipi_div, pixel_div;

	if (mipi_rate <= 300000000)
		mipi_div = 4;
	else if (mipi_rate <= 600000000)
		mipi_div = 2;
	else
		mipi_div = 1;
	sys_clk = (uint64_t)mipi_rate * mipi_div;

	if (sys_clk <= 780000000)
		pixel_div = 5;
	else if (sys_clk <= 900000000)
		pixel_div = 6;
	else
		pixel_div = 8;

	return sys_clk / pixel_div;
}

/* Same as vd55g1_get_hblank_min() + width: the shortest legal line. */
static uint32_t line_length_min(uint32_t width, uint32_t bpp,
				uint32_t mipi_rate, uint32_t pix_clk)
{
	/* rounded up: a line shorter than the MIPI transfer puts the sensor in
	 * its error state (768 px RAW8 at 600 Mbit/s needs 11.74 us) */
	uint32_t mipi_line_us = (width * bpp + MIPI_MARGIN + mipi_rate / 1000000 - 1) /
				(mipi_rate / 1000000);
	uint32_t mipi_line_len = (uint64_t)mipi_line_us * pix_clk / 1000000;

	return mipi_line_len > LINE_LENGTH_MIN ? mipi_line_len : LINE_LENGTH_MIN;
}

int vd55g1_configure(struct vd55g1 *s, const struct vd55g1_config *cfg)
{
	uint16_t left = (VD55G1_NATIVE_WIDTH - cfg->width) / 2;
	uint16_t top = (VD55G1_NATIVE_HEIGHT - cfg->height) / 2;
	uint32_t frame_length = cfg->frame_length;
	uint32_t line_us, expo_us, pattern;
	int ctx, io, ret = 0;

	if (cfg->width > VD55G1_NATIVE_WIDTH ||
	    cfg->height > VD55G1_NATIVE_HEIGHT ||
	    (cfg->bpp != 8 && cfg->bpp != 10) ||
	    cfg->mipi_rate < 250000000 || cfg->mipi_rate > 1200000000)
		return -EINVAL;

	s->pixel_clock_hz = pixel_clock(cfg->mipi_rate);
	s->line_length = line_length_min(cfg->width, cfg->bpp, cfg->mipi_rate,
					 s->pixel_clock_hz);
	if (frame_length < cfg->height + (uint32_t)VBLANK_MIN)
		frame_length = cfg->height + VBLANK_MIN;

#define W(reg, len, val) do { if (!ret) ret = vd55g1_write(s, reg, len, val); } while (0)

	/* MIPI output: rate, lane polarity (bit 3 clock, bit 6 data lane). */
	W(REG_MIPI_DATA_RATE, 4, cfg->mipi_rate);
	W(REG_OIF_CTRL, 2, cfg->swap_pn ? (1 << 3) | (1 << 6) : 0);
	W(REG_ISL_ENABLE, 2, 0);

	/* Pixel format and readout window (contexts 0, 1 and auto-wake-up). */
	W(REG_FORMAT_CTRL, 1, cfg->bpp);
	W(REG_OIF_IMG_CTRL, 1, cfg->bpp == 8 ? MIPI_DT_RAW8 : MIPI_DT_RAW10);
	W(REG_READOUT_CTRL, 1, 0);	/* no binning */
	for (ctx = 0; ctx < 4; ctx++) {
		if (ctx == 2)
			continue;
		W(REG_X_START(ctx), 2, left);
		W(REG_X_WIDTH(ctx), 2, cfg->width);
		W(REG_Y_START(ctx), 2, top);
		W(REG_Y_HEIGHT(ctx), 2, cfg->height);
	}

	/* Sensor GPIOs unused: inputs. */
	for (io = 0; io < 4; io++)
		W(REG_GPIO_0_CTRL(0) + io, 1, GPIO_MODE_IN);

	/* Auto-exposure starting point (driver defaults: 500 lines, gain ~2x). */
	line_us = ((uint64_t)s->line_length * 1000000 + s->pixel_clock_hz - 1) /
		  s->pixel_clock_hz;
	expo_us = EXPO_DEF * 1 * ((32 + (32 - AGAIN_DEF) / 2) / (32 - AGAIN_DEF)) *
		  line_us;
	W(REG_AE_FORCE_COLDSTART, 1, 1);
	W(REG_AE_COLDSTART_EXP_TIME, 4, expo_us);

	/* Defaults the ST driver applies through its V4L2 controls. */
	W(REG_ORIENTATION, 1, 0);
	pattern = cfg->pattern == VD55G1_PATTERN_GREY_RAMP ? 0x22 :
		  cfg->pattern == VD55G1_PATTERN_NOISE ? 0x28 : 0;
	W(REG_DUSTER_CTRL, 1, pattern ? 0 : DUSTER_ON);
	W(REG_PATGEN_CTRL, 2, pattern ?
	  (pattern << PATGEN_TYPE_SHIFT) | PATGEN_ENABLE : 0);
	if (cfg->manual_exposure) {
		uint32_t expo_max = frame_length - VD55G1_EXPO_MAX_TERM;
		uint32_t expo = cfg->expo_lines < expo_max ? cfg->expo_lines : expo_max;

		W(REG_EXP_MODE(0), 1, EXP_MODE_MANUAL);
		W(VD55G1_REG_MANUAL_COARSE_EXPOSURE, 2, expo);
		W(VD55G1_REG_MANUAL_ANALOG_GAIN, 1,
		  cfg->again > VD55G1_AGAIN_MAX ? VD55G1_AGAIN_MAX : cfg->again);
		for (io = 0; io < 4; io++)
			W(VD55G1_REG_MANUAL_DIGITAL_GAIN(io), 2,
			  cfg->dgain ? cfg->dgain : VD55G1_DGAIN_1X);
	} else {
		W(REG_EXP_MODE(0), 1, EXP_MODE_AUTO);
	}
	W(REG_AE_TARGET_PERCENTAGE, 1, AE_TARGET_DEF);
	W(REG_FRAME_LENGTH(0), 4, frame_length);
	W(REG_VT_CTRL, 1, 0);
	W(REG_DARKCAL_PEDESTAL(0), 2, DARKCAL_PEDESTAL_DEF);
	W(REG_DARKCAL_PEDESTAL(1), 2, DARKCAL_PEDESTAL_DEF);
	/* HDR off */
	W(REG_EXPOSURE_MAX_COARSE, 2, EXPOSURE_MAX_COARSE_DEF);
	W(REG_EXPOSURE_USE_CASES, 1, 0);
	W(REG_NEXT_CTX, 2, 0);
	W(REG_CTX_REPEAT_COUNT_CTX0, 2, 0);
	W(REG_VT_MODE(0), 1, 0);
	W(REG_MASK_FRAME_CTRL(0), 1, 0);

	W(REG_LINE_LENGTH, 2, s->line_length);
#undef W
	return ret;
}

int vd55g1_stream_on(struct vd55g1 *s)
{
	int ret;

	ret = vd55g1_write(s, REG_STBY, 1, STBY_START_STREAM);
	if (!ret)
		ret = poll_reg(s, REG_STBY, 0);
	if (!ret)
		ret = poll_reg(s, REG_SYSTEM_FSM, VD55G1_FSM_STREAMING);
	return ret;
}

int vd55g1_start(struct vd55g1 *s, const struct vd55g1_config *cfg)
{
	int ret = vd55g1_configure(s, cfg);

	return ret ? ret : vd55g1_stream_on(s);
}

uint32_t vd55g1_line_time_ns(const struct vd55g1 *s)
{
	if (!s->pixel_clock_hz)
		return 0;
	return (uint64_t)s->line_length * 1000000000ULL / s->pixel_clock_hz;
}

int vd55g1_stop(struct vd55g1 *s)
{
	int ret;

	ret = vd55g1_write(s, REG_STREAMING, 1, STREAMING_STOP_STREAM);
	if (!ret)
		ret = poll_reg(s, REG_STREAMING, 0);
	if (!ret)
		ret = poll_reg(s, REG_SYSTEM_FSM, VD55G1_FSM_SW_STBY);
	return ret;
}
