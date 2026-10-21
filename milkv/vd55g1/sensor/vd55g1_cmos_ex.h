/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * ST VD55G1 sensor driver for the Sophgo (CV181x / SG200x) ISP.
 * Shared between vd55g1_cmos.c (ISP/AE callbacks) and vd55g1_sensor_ctl.c
 * (I2C, power-up, streaming).
 */
#ifndef __VD55G1_CMOS_EX_H_
#define __VD55G1_CMOS_EX_H_

#ifdef __cplusplus
extern "C" {
#endif

#include <linux/cvi_type.h>
#include "cvi_sns_ctrl.h"

/* Registers the ISP rewrites every frame, one byte each (the sensor takes
 * little-endian values, the ISP I2C sync sends MSB first for multi-byte data). */
enum vd55g1_linear_regs_e {
	LINEAR_EXP_L,
	LINEAR_EXP_H,
	LINEAR_AGAIN,
	LINEAR_DGAIN0_L,
	LINEAR_DGAIN0_H,
	LINEAR_DGAIN1_L,
	LINEAR_DGAIN1_H,
	LINEAR_DGAIN2_L,
	LINEAR_DGAIN2_H,
	LINEAR_DGAIN3_L,
	LINEAR_DGAIN3_H,
	LINEAR_FL_L,
	LINEAR_FL_H,
	LINEAR_REGS_NUM
};

typedef enum _VD55G1_MODE_E {
	VD55G1_MODE_768X576P60 = 0,	/* 4:3, centre of the array */
	VD55G1_MODE_768X704P60,		/* full height */
	VD55G1_MODE_LINEAR_NUM,
	VD55G1_MODE_NUM
} VD55G1_MODE_E;

typedef struct _VD55G1_MODE_S {
	ISP_WDR_SIZE_S astImg[2];
	CVI_FLOAT f32MaxFps;
	CVI_FLOAT f32MinFps;
	CVI_U32 u32VtsDef;	/* frame length at f32MaxFps */
	CVI_U32 u32VtsMin;	/* height + minimum vblank */
	CVI_U32 u32LineNs;	/* line time, vd55g1.c: line_length_min() */
	char name[32];
} VD55G1_MODE_S;

extern ISP_SNS_STATE_S *g_pastVd55g1[VI_MAX_PIPE_NUM];
extern ISP_SNS_COMMBUS_U g_aunVd55g1_BusInfo[];
extern const CVI_U8 vd55g1_i2c_addr;
extern const CVI_U32 vd55g1_addr_byte;
extern const CVI_U32 vd55g1_data_byte;

extern void vd55g1_init(VI_PIPE ViPipe);
extern void vd55g1_exit(VI_PIPE ViPipe);
extern void vd55g1_standby(VI_PIPE ViPipe);
extern void vd55g1_restart(VI_PIPE ViPipe);
extern int  vd55g1_write_register(VI_PIPE ViPipe, int addr, int data);
extern int  vd55g1_read_register(VI_PIPE ViPipe, int addr);
extern void vd55g1_mirror_flip(VI_PIPE ViPipe, ISP_SNS_MIRRORFLIP_TYPE_E eSnsMirrorFlip);
extern int  vd55g1_probe(VI_PIPE ViPipe);
extern const ISP_WDR_SIZE_S *vd55g1_mode_size(CVI_U8 u8Mode);
extern CVI_U32 vd55g1_line_ns(VI_PIPE ViPipe);
extern void vd55g1_sync_state(VI_PIPE ViPipe, CVI_U32 *pu32Fl, CVI_U32 *pu32Expo,
			      CVI_U32 *pu32Again, CVI_U32 *pu32Dgain);

#define VD55G1_XCLK_HZ		12000000	/* oscillator on the ST PCB4189 */
#define VD55G1_MIPI_RATE	600000000
#define VD55G1_SWAP_PN		1		/* PCB4189: lane P/N swapped in the sensor */
#define VD55G1_FULL_LINES_MAX	0xffff

#ifdef __cplusplus
}
#endif

#endif /* __VD55G1_CMOS_EX_H_ */
