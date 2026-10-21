/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef __VD55G1_CMOS_PARAM_H_
#define __VD55G1_CMOS_PARAM_H_

#ifdef __cplusplus
extern "C" {
#endif

#include <linux/cvi_type.h>
#include "cvi_sns_ctrl.h"
#include "vd55g1_cmos_ex.h"

/*
 * The ISP reads the raw frame with the width rounded up to 64 pixels while
 * the VI writes it unpadded, so the window width must be a multiple of 64.
 * 768 px RAW8 at 600 Mbit/s: 1800-clock line at 150 MHz = 12 us.
 */
#define VD55G1_LINE_NS_768	12000
#define VD55G1_VTS_60FPS	1389	/* 1 / (60 * 12 us) */

static const VD55G1_MODE_S g_astVd55g1_mode[VD55G1_MODE_NUM] = {
	[VD55G1_MODE_768X576P60] = {
		.name = "768x576p60",
		.astImg[0] = {
			.stSnsSize = { .u32Width = 768, .u32Height = 576 },
			.stWndRect = { .s32X = 0, .s32Y = 0, .u32Width = 768, .u32Height = 576 },
			.stMaxSize = { .u32Width = 768, .u32Height = 576 },
		},
		.f32MaxFps = 60,
		.f32MinFps = 1.28,	/* 1389 * 60 / 0xffff */
		.u32VtsDef = VD55G1_VTS_60FPS,
		.u32VtsMin = 576 + 86,
		.u32LineNs = VD55G1_LINE_NS_768,
	},
	[VD55G1_MODE_768X704P60] = {
		.name = "768x704p60",
		.astImg[0] = {
			.stSnsSize = { .u32Width = 768, .u32Height = 704 },
			.stWndRect = { .s32X = 0, .s32Y = 0, .u32Width = 768, .u32Height = 704 },
			.stMaxSize = { .u32Width = 768, .u32Height = 704 },
		},
		.f32MaxFps = 60,
		.f32MinFps = 1.28,
		.u32VtsDef = VD55G1_VTS_60FPS,
		.u32VtsMin = 704 + 86,
		.u32LineNs = VD55G1_LINE_NS_768,
	},
};

/*
 * RAW8 lands in the upper 8 bits of the ISP's 12-bit data. The sensor adds a
 * dark pedestal of 64 on its 10-bit scale, i.e. 16 on RAW8, 256 at 12 bit.
 */
#define VD55G1_BLC	256
static ISP_CMOS_BLACK_LEVEL_S g_stIspBlcCalibration = {
	.bUpdate = CVI_TRUE,
	.blcAttr = {
		.Enable = 1,
		.enOpType = OP_TYPE_AUTO,
		.stManual = { VD55G1_BLC, VD55G1_BLC, VD55G1_BLC, VD55G1_BLC, 0, 0, 0, 0 },
		.stAuto = {
			{ [0 ... 15] = VD55G1_BLC },
			{ [0 ... 15] = VD55G1_BLC },
			{ [0 ... 15] = VD55G1_BLC },
			{ [0 ... 15] = VD55G1_BLC },
			{ 0 }, { 0 }, { 0 }, { 0 },
		},
	},
};

/* J2 connector of the Milk-V Duo S: clock on lane 5, data on lane 3. */
static struct combo_dev_attr_s vd55g1_rx_attr = {
	.input_mode = INPUT_MODE_MIPI,
	.mac_clk = RX_MAC_CLK_400M,
	.mipi_attr = {
		.raw_data_type = RAW_DATA_8BIT,
		.lane_id = { 5, 3, -1, -1, -1 },
		.pn_swap = { 0, 0, 0, 0, 0 },	/* swapped in the sensor */
		.wdr_mode = CVI_MIPI_WDR_MODE_NONE,
		.dphy = { .enable = 1, .hs_settle = 8 },
	},
	.mclk = { .cam = 1, .freq = CAMPLL_FREQ_NONE },	/* sensor has its own oscillator */
	.devno = 0,
};

#ifdef __cplusplus
}
#endif

#endif /* __VD55G1_CMOS_PARAM_H_ */
