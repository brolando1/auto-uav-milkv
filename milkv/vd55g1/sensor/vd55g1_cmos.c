// SPDX-License-Identifier: GPL-2.0-only
/*
 * ST VD55G1 sensor driver for the Sophgo (CV181x / SG200x) ISP: modes,
 * exposure/gain callbacks for the Sophgo AE and the sensor object
 * (stSnsVd55g1_Obj) that the VI/ISP setup registers, like any libsns_*.so.
 *
 * The sensor runs in manual exposure mode; the Sophgo AE sets exposure,
 * analog and digital gain every frame through the ISP's I2C sync.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <syslog.h>
#include <errno.h>

#include <linux/cvi_type.h>
#include <linux/cvi_comm_video.h>
#include "cvi_debug.h"
#include "cvi_comm_sns.h"
#include "cvi_sns_ctrl.h"
#include "cvi_ae_comm.h"
#include "cvi_awb_comm.h"
#include "cvi_ae.h"
#include "cvi_awb.h"
#include "cvi_isp.h"

#include "vd55g1.h"
#include "vd55g1_cmos_ex.h"
#include "vd55g1_cmos_param.h"

#define DIV_0_TO_1_FLOAT(a) ((((a) < 1E-10) && ((a) > -1E-10)) ? 1 : (a))
#define VD55G1_ID 551

ISP_SNS_STATE_S *g_pastVd55g1[VI_MAX_PIPE_NUM] = { CVI_NULL };

#define VD55G1_SENSOR_GET_CTX(dev, pstCtx)	(pstCtx = g_pastVd55g1[dev])
#define VD55G1_SENSOR_SET_CTX(dev, pstCtx)	(g_pastVd55g1[dev] = pstCtx)
#define VD55G1_SENSOR_RESET_CTX(dev)		(g_pastVd55g1[dev] = CVI_NULL)

ISP_SNS_COMMBUS_U g_aunVd55g1_BusInfo[VI_MAX_PIPE_NUM] = {
	[0] = { .s8I2cDev = 2 },	/* J2 connector */
	[1 ... VI_MAX_PIPE_NUM - 1] = { .s8I2cDev = -1 }
};

static CVI_U32 g_au32InitExposure[VI_MAX_PIPE_NUM];

/* analog gain register g -> 32 / (32 - g), in 1/1024 */
static CVI_U32 again_lin(CVI_U32 g)
{
	return (32 * 1024 + (32 - g) / 2) / (32 - g);
}

/* digital gain: sensor 8.8, AE 1/1024; kept at <= 4x */
#define DGAIN_LIN_MIN	1024
#define DGAIN_LIN_MAX	4096

static CVI_S32 cmos_get_ae_default(VI_PIPE ViPipe, AE_SENSOR_DEFAULT_S *pstAeSnsDft)
{
	const VD55G1_MODE_S *pstMode;
	ISP_SNS_STATE_S *pstSnsState = CVI_NULL;

	CMOS_CHECK_POINTER(pstAeSnsDft);
	VD55G1_SENSOR_GET_CTX(ViPipe, pstSnsState);
	CMOS_CHECK_POINTER(pstSnsState);
	pstMode = &g_astVd55g1_mode[pstSnsState->u8ImgMode];

	pstAeSnsDft->u32FullLinesStd = pstSnsState->u32FLStd;
	pstAeSnsDft->u32FlickerFreq = 50 * 256;
	pstAeSnsDft->u32FullLinesMax = VD55G1_FULL_LINES_MAX;
	pstAeSnsDft->u32HmaxTimes = 1000000 / (pstSnsState->u32FLStd * pstMode->f32MaxFps);

	pstAeSnsDft->stIntTimeAccu.enAccuType = AE_ACCURACY_LINEAR;
	pstAeSnsDft->stIntTimeAccu.f32Accuracy = 1;
	pstAeSnsDft->stIntTimeAccu.f32Offset = 0;
	pstAeSnsDft->stAgainAccu.enAccuType = AE_ACCURACY_TABLE;
	pstAeSnsDft->stAgainAccu.f32Accuracy = 1;
	pstAeSnsDft->stDgainAccu.enAccuType = AE_ACCURACY_TABLE;
	pstAeSnsDft->stDgainAccu.f32Accuracy = 1;

	pstAeSnsDft->u32ISPDgainShift = 8;
	pstAeSnsDft->u32MinISPDgainTarget = 1 << pstAeSnsDft->u32ISPDgainShift;
	pstAeSnsDft->u32MaxISPDgainTarget = 2 << pstAeSnsDft->u32ISPDgainShift;

	pstAeSnsDft->u32LinesPer500ms = 500000000 / pstMode->u32LineNs;
	pstAeSnsDft->u32SnsStableFrame = 0;

	switch (pstSnsState->enWDRMode) {
	case WDR_MODE_NONE:
		pstAeSnsDft->f32Fps = pstMode->f32MaxFps;
		pstAeSnsDft->f32MinFps = pstMode->f32MinFps;
		pstAeSnsDft->au8HistThresh[0] = 0xd;
		pstAeSnsDft->au8HistThresh[1] = 0x28;
		pstAeSnsDft->au8HistThresh[2] = 0x60;
		pstAeSnsDft->au8HistThresh[3] = 0x80;

		pstAeSnsDft->u32MinAgain = again_lin(0);
		pstAeSnsDft->u32MaxAgain = again_lin(VD55G1_AGAIN_MAX);
		pstAeSnsDft->u32MinAgainTarget = pstAeSnsDft->u32MinAgain;
		pstAeSnsDft->u32MaxAgainTarget = pstAeSnsDft->u32MaxAgain;

		pstAeSnsDft->u32MinDgain = DGAIN_LIN_MIN;
		pstAeSnsDft->u32MaxDgain = DGAIN_LIN_MAX;
		pstAeSnsDft->u32MinDgainTarget = pstAeSnsDft->u32MinDgain;
		pstAeSnsDft->u32MaxDgainTarget = pstAeSnsDft->u32MaxDgain;

		pstAeSnsDft->u8AeCompensation = 40;
		pstAeSnsDft->u32InitAESpeed = 64;
		pstAeSnsDft->u32InitAETolerance = 5;
		pstAeSnsDft->u32AEResponseFrame = 4;
		pstAeSnsDft->enAeExpMode = AE_EXP_HIGHLIGHT_PRIOR;
		pstAeSnsDft->u32InitExposure = g_au32InitExposure[ViPipe] ?
			g_au32InitExposure[ViPipe] : 76151;

		pstAeSnsDft->u32MinIntTime = 1;
		pstAeSnsDft->u32MaxIntTime = pstSnsState->u32FLStd - VD55G1_EXPO_MAX_TERM;
		pstAeSnsDft->u32MinIntTimeTarget = pstAeSnsDft->u32MinIntTime;
		pstAeSnsDft->u32MaxIntTimeTarget = pstAeSnsDft->u32MaxIntTime;
		break;
	default:
		CVI_TRACE_SNS(CVI_DBG_ERR, "Not support WDR: %d\n", pstSnsState->enWDRMode);
		return CVI_FAILURE;
	}

	return CVI_SUCCESS;
}

static CVI_S32 cmos_fps_set(VI_PIPE ViPipe, CVI_FLOAT f32Fps, AE_SENSOR_DEFAULT_S *pstAeSnsDft)
{
	ISP_SNS_STATE_S *pstSnsState = CVI_NULL;
	ISP_SNS_REGS_INFO_S *pstSnsRegsInfo;
	const VD55G1_MODE_S *pstMode;
	CVI_U32 u32Vts;

	CMOS_CHECK_POINTER(pstAeSnsDft);
	VD55G1_SENSOR_GET_CTX(ViPipe, pstSnsState);
	CMOS_CHECK_POINTER(pstSnsState);
	pstMode = &g_astVd55g1_mode[pstSnsState->u8ImgMode];
	pstSnsRegsInfo = &pstSnsState->astSyncInfo[0].snsCfg;

	if (f32Fps > pstMode->f32MaxFps || f32Fps < pstMode->f32MinFps) {
		CVI_TRACE_SNS(CVI_DBG_ERR, "Not support Fps: %f\n", f32Fps);
		return CVI_FAILURE;
	}
	u32Vts = pstMode->u32VtsDef * pstMode->f32MaxFps / DIV_0_TO_1_FLOAT(f32Fps);
	if (u32Vts > VD55G1_FULL_LINES_MAX)
		u32Vts = VD55G1_FULL_LINES_MAX;
	if (u32Vts < pstMode->u32VtsMin)
		u32Vts = pstMode->u32VtsMin;

	pstSnsState->u32FLStd = u32Vts;
	pstSnsRegsInfo->astI2cData[LINEAR_FL_L].u32Data = u32Vts & 0xff;
	pstSnsRegsInfo->astI2cData[LINEAR_FL_H].u32Data = (u32Vts >> 8) & 0xff;

	pstAeSnsDft->f32Fps = f32Fps;
	pstAeSnsDft->u32LinesPer500ms = 500000000 / pstMode->u32LineNs;
	pstAeSnsDft->u32FullLinesStd = u32Vts;
	pstAeSnsDft->u32MaxIntTime = u32Vts - VD55G1_EXPO_MAX_TERM;
	pstSnsState->au32FL[0] = u32Vts;
	pstAeSnsDft->u32FullLines = u32Vts;
	pstAeSnsDft->u32HmaxTimes = 1000000 / (u32Vts * DIV_0_TO_1_FLOAT(f32Fps));

	return CVI_SUCCESS;
}

static CVI_S32 cmos_inttime_update(VI_PIPE ViPipe, CVI_U32 *u32IntTime)
{
	ISP_SNS_STATE_S *pstSnsState = CVI_NULL;
	ISP_SNS_REGS_INFO_S *pstSnsRegsInfo;
	CVI_U32 u32Max, u32Lines;

	VD55G1_SENSOR_GET_CTX(ViPipe, pstSnsState);
	CMOS_CHECK_POINTER(pstSnsState);
	CMOS_CHECK_POINTER(u32IntTime);
	pstSnsRegsInfo = &pstSnsState->astSyncInfo[0].snsCfg;

	if (pstSnsState->enWDRMode != WDR_MODE_NONE) {
		CVI_TRACE_SNS(CVI_DBG_ERR, "Not support WDR: %d\n", pstSnsState->enWDRMode);
		return CVI_FAILURE;
	}
	u32Max = pstSnsState->au32FL[0] - VD55G1_EXPO_MAX_TERM;
	u32Lines = u32IntTime[0] > u32Max ? u32Max : u32IntTime[0];
	if (u32Lines < 1)
		u32Lines = 1;

	pstSnsRegsInfo->astI2cData[LINEAR_EXP_L].u32Data = u32Lines & 0xff;
	pstSnsRegsInfo->astI2cData[LINEAR_EXP_H].u32Data = (u32Lines >> 8) & 0xff;

	return CVI_SUCCESS;
}

/* AE linear gain -> register index; the index is what gains_update gets */
static CVI_S32 cmos_again_calc_table(VI_PIPE ViPipe, CVI_U32 *pu32AgainLin, CVI_U32 *pu32AgainDb)
{
	CVI_S32 g;

	(void)ViPipe;
	CMOS_CHECK_POINTER(pu32AgainLin);
	CMOS_CHECK_POINTER(pu32AgainDb);

	for (g = VD55G1_AGAIN_MAX; g > 0; g--)
		if (*pu32AgainLin >= again_lin(g))
			break;
	*pu32AgainDb = g;
	*pu32AgainLin = again_lin(g);

	return CVI_SUCCESS;
}

static CVI_S32 cmos_dgain_calc_table(VI_PIPE ViPipe, CVI_U32 *pu32DgainLin, CVI_U32 *pu32DgainDb)
{
	CVI_U32 lin;

	(void)ViPipe;
	CMOS_CHECK_POINTER(pu32DgainLin);
	CMOS_CHECK_POINTER(pu32DgainDb);

	lin = *pu32DgainLin;
	if (lin < DGAIN_LIN_MIN)
		lin = DGAIN_LIN_MIN;
	if (lin > DGAIN_LIN_MAX)
		lin = DGAIN_LIN_MAX;
	*pu32DgainDb = lin >> 2;	/* 1/1024 -> 8.8 */
	*pu32DgainLin = *pu32DgainDb << 2;

	return CVI_SUCCESS;
}

static CVI_S32 cmos_gains_update(VI_PIPE ViPipe, CVI_U32 *pu32Again, CVI_U32 *pu32Dgain)
{
	ISP_SNS_STATE_S *pstSnsState = CVI_NULL;
	ISP_I2C_DATA_S *d;
	CVI_U32 again, dgain;
	int ch;

	VD55G1_SENSOR_GET_CTX(ViPipe, pstSnsState);
	CMOS_CHECK_POINTER(pstSnsState);
	CMOS_CHECK_POINTER(pu32Again);
	CMOS_CHECK_POINTER(pu32Dgain);
	d = pstSnsState->astSyncInfo[0].snsCfg.astI2cData;

	if (pstSnsState->enWDRMode != WDR_MODE_NONE) {
		CVI_TRACE_SNS(CVI_DBG_ERR, "Not support WDR: %d\n", pstSnsState->enWDRMode);
		return CVI_FAILURE;
	}
	again = pu32Again[0] > VD55G1_AGAIN_MAX ? VD55G1_AGAIN_MAX : pu32Again[0];
	dgain = pu32Dgain[0];
	if (dgain < DGAIN_LIN_MIN >> 2)
		dgain = DGAIN_LIN_MIN >> 2;
	if (dgain > DGAIN_LIN_MAX >> 2)
		dgain = DGAIN_LIN_MAX >> 2;

	d[LINEAR_AGAIN].u32Data = again;
	for (ch = 0; ch < 4; ch++) {
		d[LINEAR_DGAIN0_L + 2 * ch].u32Data = dgain & 0xff;
		d[LINEAR_DGAIN0_H + 2 * ch].u32Data = dgain >> 8;
	}

	return CVI_SUCCESS;
}

static CVI_S32 cmos_init_ae_exp_function(AE_SENSOR_EXP_FUNC_S *pstExpFuncs)
{
	CMOS_CHECK_POINTER(pstExpFuncs);

	memset(pstExpFuncs, 0, sizeof(AE_SENSOR_EXP_FUNC_S));
	pstExpFuncs->pfn_cmos_get_ae_default    = cmos_get_ae_default;
	pstExpFuncs->pfn_cmos_fps_set           = cmos_fps_set;
	pstExpFuncs->pfn_cmos_inttime_update    = cmos_inttime_update;
	pstExpFuncs->pfn_cmos_gains_update      = cmos_gains_update;
	pstExpFuncs->pfn_cmos_again_calc_table  = cmos_again_calc_table;
	pstExpFuncs->pfn_cmos_dgain_calc_table  = cmos_dgain_calc_table;

	return CVI_SUCCESS;
}

/* Monochrome sensor: all white-balance gains 1x. */
static CVI_S32 cmos_get_awb_default(VI_PIPE ViPipe, AWB_SENSOR_DEFAULT_S *pstAwbSnsDft)
{
	(void)ViPipe;
	CMOS_CHECK_POINTER(pstAwbSnsDft);

	memset(pstAwbSnsDft, 0, sizeof(AWB_SENSOR_DEFAULT_S));
	pstAwbSnsDft->u16InitRgain = 1024;
	pstAwbSnsDft->u16InitGgain = 1024;
	pstAwbSnsDft->u16InitBgain = 1024;
	pstAwbSnsDft->u8AWBRunInterval = 1;

	return CVI_SUCCESS;
}

static CVI_S32 cmos_init_awb_exp_function(AWB_SENSOR_EXP_FUNC_S *pstExpFuncs)
{
	CMOS_CHECK_POINTER(pstExpFuncs);

	memset(pstExpFuncs, 0, sizeof(AWB_SENSOR_EXP_FUNC_S));
	pstExpFuncs->pfn_cmos_get_awb_default = cmos_get_awb_default;

	return CVI_SUCCESS;
}

static CVI_S32 cmos_get_isp_default(VI_PIPE ViPipe, ISP_CMOS_DEFAULT_S *pstDef)
{
	(void)ViPipe;
	memset(pstDef, 0, sizeof(ISP_CMOS_DEFAULT_S));
	return CVI_SUCCESS;
}

static CVI_S32 cmos_get_blc_default(VI_PIPE ViPipe, ISP_CMOS_BLACK_LEVEL_S *pstBlc)
{
	(void)ViPipe;
	CMOS_CHECK_POINTER(pstBlc);
	memcpy(pstBlc, &g_stIspBlcCalibration, sizeof(ISP_CMOS_BLACK_LEVEL_S));
	return CVI_SUCCESS;
}

static CVI_S32 cmos_get_wdr_size(VI_PIPE ViPipe, ISP_SNS_ISP_INFO_S *pstIspCfg)
{
	ISP_SNS_STATE_S *pstSnsState = CVI_NULL;

	VD55G1_SENSOR_GET_CTX(ViPipe, pstSnsState);
	CMOS_CHECK_POINTER(pstSnsState);

	pstIspCfg->frm_num = 1;
	memcpy(&pstIspCfg->img_size[0], &g_astVd55g1_mode[pstSnsState->u8ImgMode].astImg[0],
	       sizeof(ISP_WDR_SIZE_S));

	return CVI_SUCCESS;
}

static CVI_S32 cmos_set_wdr_mode(VI_PIPE ViPipe, CVI_U8 u8Mode)
{
	ISP_SNS_STATE_S *pstSnsState = CVI_NULL;

	VD55G1_SENSOR_GET_CTX(ViPipe, pstSnsState);
	CMOS_CHECK_POINTER(pstSnsState);

	pstSnsState->bSyncInit = CVI_FALSE;
	if (u8Mode != WDR_MODE_NONE) {
		CVI_TRACE_SNS(CVI_DBG_ERR, "NOT support this mode!\n");
		return CVI_FAILURE;
	}
	pstSnsState->enWDRMode = WDR_MODE_NONE;
	pstSnsState->u32FLStd = g_astVd55g1_mode[pstSnsState->u8ImgMode].u32VtsDef;
	pstSnsState->au32FL[0] = pstSnsState->u32FLStd;
	pstSnsState->au32FL[1] = pstSnsState->au32FL[0];
	memset(pstSnsState->au32WDRIntTime, 0, sizeof(pstSnsState->au32WDRIntTime));

	return CVI_SUCCESS;
}

static CVI_U32 sensor_cmp_wdr_size(ISP_SNS_ISP_INFO_S *a, ISP_SNS_ISP_INFO_S *b)
{
	CVI_U32 i;

	if (a->frm_num != b->frm_num)
		return 1;
	for (i = 0; i < 2; i++) {
		if (a->img_size[i].stSnsSize.u32Width != b->img_size[i].stSnsSize.u32Width ||
		    a->img_size[i].stSnsSize.u32Height != b->img_size[i].stSnsSize.u32Height ||
		    a->img_size[i].stWndRect.s32X != b->img_size[i].stWndRect.s32X ||
		    a->img_size[i].stWndRect.s32Y != b->img_size[i].stWndRect.s32Y ||
		    a->img_size[i].stWndRect.u32Width != b->img_size[i].stWndRect.u32Width ||
		    a->img_size[i].stWndRect.u32Height != b->img_size[i].stWndRect.u32Height)
			return 1;
	}
	return 0;
}

static const CVI_U32 g_au32SyncRegAddr[LINEAR_REGS_NUM] = {
	[LINEAR_EXP_L]    = VD55G1_REG_MANUAL_COARSE_EXPOSURE,
	[LINEAR_EXP_H]    = VD55G1_REG_MANUAL_COARSE_EXPOSURE + 1,
	[LINEAR_AGAIN]    = VD55G1_REG_MANUAL_ANALOG_GAIN,
	[LINEAR_DGAIN0_L] = VD55G1_REG_MANUAL_DIGITAL_GAIN(0),
	[LINEAR_DGAIN0_H] = VD55G1_REG_MANUAL_DIGITAL_GAIN(0) + 1,
	[LINEAR_DGAIN1_L] = VD55G1_REG_MANUAL_DIGITAL_GAIN(1),
	[LINEAR_DGAIN1_H] = VD55G1_REG_MANUAL_DIGITAL_GAIN(1) + 1,
	[LINEAR_DGAIN2_L] = VD55G1_REG_MANUAL_DIGITAL_GAIN(2),
	[LINEAR_DGAIN2_H] = VD55G1_REG_MANUAL_DIGITAL_GAIN(2) + 1,
	[LINEAR_DGAIN3_L] = VD55G1_REG_MANUAL_DIGITAL_GAIN(3),
	[LINEAR_DGAIN3_H] = VD55G1_REG_MANUAL_DIGITAL_GAIN(3) + 1,
	[LINEAR_FL_L]     = VD55G1_REG_FRAME_LENGTH_CTX0,
	[LINEAR_FL_H]     = VD55G1_REG_FRAME_LENGTH_CTX0 + 1,
};

static CVI_S32 cmos_get_sns_regs_info(VI_PIPE ViPipe, ISP_SNS_SYNC_INFO_S *pstSnsSyncInfo)
{
	ISP_SNS_STATE_S *pstSnsState = CVI_NULL;
	ISP_SNS_SYNC_INFO_S *pstCfg0, *pstCfg1;
	ISP_I2C_DATA_S *pstI2c;
	CVI_U32 i;

	CMOS_CHECK_POINTER(pstSnsSyncInfo);
	VD55G1_SENSOR_GET_CTX(ViPipe, pstSnsState);
	CMOS_CHECK_POINTER(pstSnsState);
	pstCfg0 = &pstSnsState->astSyncInfo[0];
	pstCfg1 = &pstSnsState->astSyncInfo[1];
	pstI2c = pstCfg0->snsCfg.astI2cData;

	if (pstSnsState->bSyncInit == CVI_FALSE || pstSnsSyncInfo->snsCfg.bConfig == CVI_FALSE) {
		pstCfg0->snsCfg.enSnsType = SNS_I2C_TYPE;
		pstCfg0->snsCfg.unComBus.s8I2cDev = g_aunVd55g1_BusInfo[ViPipe].s8I2cDev;
		pstCfg0->snsCfg.u8Cfg2ValidDelayMax = 2;
		pstCfg0->snsCfg.use_snsr_sram = CVI_TRUE;
		pstCfg0->snsCfg.u32RegNum = LINEAR_REGS_NUM;

		for (i = 0; i < LINEAR_REGS_NUM; i++) {
			pstI2c[i].bUpdate = CVI_TRUE;
			pstI2c[i].u8DevAddr = vd55g1_i2c_addr;
			pstI2c[i].u32AddrByteNum = vd55g1_addr_byte;
			pstI2c[i].u32DataByteNum = vd55g1_data_byte;
			pstI2c[i].u32RegAddr = g_au32SyncRegAddr[i];
		}
		pstSnsState->bSyncInit = CVI_TRUE;
		pstCfg0->snsCfg.need_update = CVI_TRUE;
		cmos_get_wdr_size(ViPipe, &pstCfg0->ispCfg);
		pstCfg0->ispCfg.need_update = CVI_TRUE;
	} else {
		pstCfg0->snsCfg.need_update = CVI_FALSE;
		for (i = 0; i < pstCfg0->snsCfg.u32RegNum; i++) {
			if (pstI2c[i].u32Data == pstCfg1->snsCfg.astI2cData[i].u32Data) {
				pstI2c[i].bUpdate = CVI_FALSE;
			} else {
				pstI2c[i].bUpdate = CVI_TRUE;
				pstCfg0->snsCfg.need_update = CVI_TRUE;
			}
		}
		pstCfg0->ispCfg.need_update = sensor_cmp_wdr_size(&pstCfg0->ispCfg, &pstCfg1->ispCfg) ?
			CVI_TRUE : CVI_FALSE;
		pstCfg0->cifCfg.need_update = CVI_FALSE;
	}

	pstSnsSyncInfo->snsCfg.bConfig = CVI_FALSE;
	memcpy(pstSnsSyncInfo, pstCfg0, sizeof(ISP_SNS_SYNC_INFO_S));
	memcpy(pstCfg1, pstCfg0, sizeof(ISP_SNS_SYNC_INFO_S));
	pstSnsState->au32FL[1] = pstSnsState->au32FL[0];

	return CVI_SUCCESS;
}

static CVI_S32 cmos_set_image_mode(VI_PIPE ViPipe, ISP_CMOS_SENSOR_IMAGE_MODE_S *pstSensorImageMode)
{
	ISP_SNS_STATE_S *pstSnsState = CVI_NULL;
	CVI_U8 u8Mode;

	CMOS_CHECK_POINTER(pstSensorImageMode);
	VD55G1_SENSOR_GET_CTX(ViPipe, pstSnsState);
	CMOS_CHECK_POINTER(pstSnsState);

	pstSnsState->bSyncInit = CVI_FALSE;

	for (u8Mode = 0; u8Mode < VD55G1_MODE_LINEAR_NUM; u8Mode++) {
		const ISP_WDR_SIZE_S *img = &g_astVd55g1_mode[u8Mode].astImg[0];

		if (pstSensorImageMode->u16Width == img->stSnsSize.u32Width &&
		    pstSensorImageMode->u16Height == img->stSnsSize.u32Height &&
		    pstSensorImageMode->f32Fps <= g_astVd55g1_mode[u8Mode].f32MaxFps)
			break;
	}
	if (u8Mode == VD55G1_MODE_LINEAR_NUM || pstSnsState->enWDRMode != WDR_MODE_NONE) {
		CVI_TRACE_SNS(CVI_DBG_ERR, "Not support! Width:%d, Height:%d, Fps:%f, WDRMode:%d\n",
			      pstSensorImageMode->u16Width, pstSensorImageMode->u16Height,
			      pstSensorImageMode->f32Fps, pstSnsState->enWDRMode);
		return CVI_FAILURE;
	}

	if (pstSnsState->bInit == CVI_TRUE && u8Mode == pstSnsState->u8ImgMode)
		return CVI_FAILURE;	/* no switch needed */

	pstSnsState->u8ImgMode = u8Mode;
	pstSnsState->u32FLStd = g_astVd55g1_mode[u8Mode].u32VtsDef;
	pstSnsState->au32FL[0] = pstSnsState->u32FLStd;
	pstSnsState->au32FL[1] = pstSnsState->u32FLStd;
	pstSnsState->astSyncInfo[0].snsCfg.astI2cData[LINEAR_FL_L].u32Data = pstSnsState->u32FLStd & 0xff;
	pstSnsState->astSyncInfo[0].snsCfg.astI2cData[LINEAR_FL_H].u32Data = pstSnsState->u32FLStd >> 8;

	return CVI_SUCCESS;
}

#define VD55G1_EXPO_DEF	500

static void sync_regs_default(ISP_SNS_STATE_S *pstSnsState)
{
	ISP_I2C_DATA_S *d = pstSnsState->astSyncInfo[0].snsCfg.astI2cData;
	CVI_U32 fl = pstSnsState->u32FLStd;
	int ch;

	d[LINEAR_EXP_L].u32Data = VD55G1_EXPO_DEF & 0xff;
	d[LINEAR_EXP_H].u32Data = VD55G1_EXPO_DEF >> 8;
	d[LINEAR_AGAIN].u32Data = 0;
	for (ch = 0; ch < 4; ch++) {
		d[LINEAR_DGAIN0_L + 2 * ch].u32Data = VD55G1_DGAIN_1X & 0xff;
		d[LINEAR_DGAIN0_H + 2 * ch].u32Data = VD55G1_DGAIN_1X >> 8;
	}
	d[LINEAR_FL_L].u32Data = fl & 0xff;
	d[LINEAR_FL_H].u32Data = (fl >> 8) & 0xff;
}

CVI_U32 vd55g1_line_ns(VI_PIPE ViPipe)
{
	ISP_SNS_STATE_S *pstSnsState = g_pastVd55g1[ViPipe];

	return g_astVd55g1_mode[pstSnsState ? pstSnsState->u8ImgMode : 0].u32LineNs;
}

const ISP_WDR_SIZE_S *vd55g1_mode_size(CVI_U8 u8Mode)
{
	return &g_astVd55g1_mode[u8Mode < VD55G1_MODE_LINEAR_NUM ? u8Mode : 0].astImg[0];
}

/* Sync register values as the sensor should start with (used by sensor init). */
void vd55g1_sync_state(VI_PIPE ViPipe, CVI_U32 *pu32Fl, CVI_U32 *pu32Expo, CVI_U32 *pu32Again,
		       CVI_U32 *pu32Dgain)
{
	ISP_SNS_STATE_S *pstSnsState = g_pastVd55g1[ViPipe];
	ISP_I2C_DATA_S *d = pstSnsState->astSyncInfo[0].snsCfg.astI2cData;
	CVI_U32 fl = d[LINEAR_FL_L].u32Data | d[LINEAR_FL_H].u32Data << 8;

	*pu32Fl = fl ? fl : pstSnsState->u32FLStd;
	*pu32Expo = d[LINEAR_EXP_L].u32Data | d[LINEAR_EXP_H].u32Data << 8;
	*pu32Again = d[LINEAR_AGAIN].u32Data;
	*pu32Dgain = d[LINEAR_DGAIN0_L].u32Data | d[LINEAR_DGAIN0_H].u32Data << 8;
	if (!*pu32Dgain)
		*pu32Dgain = VD55G1_DGAIN_1X;
	if (!*pu32Expo)
		*pu32Expo = VD55G1_EXPO_DEF;
}

static CVI_VOID sensor_global_init(VI_PIPE ViPipe)
{
	ISP_SNS_STATE_S *pstSnsState = CVI_NULL;

	VD55G1_SENSOR_GET_CTX(ViPipe, pstSnsState);
	CMOS_CHECK_POINTER_VOID(pstSnsState);

	pstSnsState->bInit = CVI_FALSE;
	pstSnsState->bSyncInit = CVI_FALSE;
	pstSnsState->u8ImgMode = VD55G1_MODE_768X576P60;
	pstSnsState->enWDRMode = WDR_MODE_NONE;
	pstSnsState->u32FLStd  = g_astVd55g1_mode[pstSnsState->u8ImgMode].u32VtsDef;
	pstSnsState->au32FL[0] = pstSnsState->u32FLStd;
	pstSnsState->au32FL[1] = pstSnsState->u32FLStd;

	memset(&pstSnsState->astSyncInfo[0], 0, sizeof(ISP_SNS_SYNC_INFO_S));
	memset(&pstSnsState->astSyncInfo[1], 0, sizeof(ISP_SNS_SYNC_INFO_S));

	/* Start values until the AE has run: frame length of the mode,
	 * 500 lines, 1x gains (never write a 0 frame length or gain). */
	sync_regs_default(pstSnsState);
}

static CVI_S32 sensor_rx_attr(VI_PIPE ViPipe, SNS_COMBO_DEV_ATTR_S *pstRxAttr)
{
	ISP_SNS_STATE_S *pstSnsState = CVI_NULL;
	const ISP_WDR_SIZE_S *img;

	VD55G1_SENSOR_GET_CTX(ViPipe, pstSnsState);
	CMOS_CHECK_POINTER(pstSnsState);
	CMOS_CHECK_POINTER(pstRxAttr);

	img = &g_astVd55g1_mode[pstSnsState->u8ImgMode].astImg[0];
	memcpy(pstRxAttr, &vd55g1_rx_attr, sizeof(*pstRxAttr));
	pstRxAttr->img_size.width = img->stSnsSize.u32Width;
	pstRxAttr->img_size.height = img->stSnsSize.u32Height;
	pstRxAttr->mipi_attr.wdr_mode = CVI_MIPI_WDR_MODE_NONE;

	return CVI_SUCCESS;
}

static CVI_S32 sensor_patch_rx_attr(RX_INIT_ATTR_S *pstRxInitAttr)
{
	struct mipi_dev_attr_s *attr = &vd55g1_rx_attr.mipi_attr;
	int i;

	CMOS_CHECK_POINTER(pstRxInitAttr);

	if (pstRxInitAttr->stMclkAttr.bMclkEn)
		vd55g1_rx_attr.mclk.cam = pstRxInitAttr->stMclkAttr.u8Mclk;
	if (pstRxInitAttr->MipiDev >= VI_MAX_DEV_NUM)
		return CVI_SUCCESS;

	vd55g1_rx_attr.devno = pstRxInitAttr->MipiDev;
	for (i = 0; i < MIPI_LANE_NUM + 1; i++) {
		attr->lane_id[i] = pstRxInitAttr->as16LaneId[i];
		attr->pn_swap[i] = pstRxInitAttr->as8PNSwap[i];
	}

	return CVI_SUCCESS;
}

static CVI_S32 cmos_init_sensor_exp_function(ISP_SENSOR_EXP_FUNC_S *pstSensorExpFunc)
{
	CMOS_CHECK_POINTER(pstSensorExpFunc);

	memset(pstSensorExpFunc, 0, sizeof(ISP_SENSOR_EXP_FUNC_S));
	pstSensorExpFunc->pfn_cmos_sensor_init = vd55g1_init;
	pstSensorExpFunc->pfn_cmos_sensor_exit = vd55g1_exit;
	pstSensorExpFunc->pfn_cmos_sensor_global_init = sensor_global_init;
	pstSensorExpFunc->pfn_cmos_set_image_mode = cmos_set_image_mode;
	pstSensorExpFunc->pfn_cmos_set_wdr_mode = cmos_set_wdr_mode;
	pstSensorExpFunc->pfn_cmos_get_isp_default = cmos_get_isp_default;
	pstSensorExpFunc->pfn_cmos_get_isp_black_level = cmos_get_blc_default;
	pstSensorExpFunc->pfn_cmos_get_sns_reg_info = cmos_get_sns_regs_info;

	return CVI_SUCCESS;
}

static CVI_S32 vd55g1_set_bus_info(VI_PIPE ViPipe, ISP_SNS_COMMBUS_U unSNSBusInfo)
{
	g_aunVd55g1_BusInfo[ViPipe].s8I2cDev = unSNSBusInfo.s8I2cDev;
	return CVI_SUCCESS;
}

static CVI_S32 sensor_ctx_init(VI_PIPE ViPipe)
{
	ISP_SNS_STATE_S *ctx = CVI_NULL;

	VD55G1_SENSOR_GET_CTX(ViPipe, ctx);
	if (ctx == CVI_NULL) {
		ctx = malloc(sizeof(ISP_SNS_STATE_S));
		if (ctx == CVI_NULL) {
			CVI_TRACE_SNS(CVI_DBG_ERR, "Isp[%d] SnsCtx malloc memory failed!\n", ViPipe);
			return -ENOMEM;
		}
	}
	memset(ctx, 0, sizeof(ISP_SNS_STATE_S));
	VD55G1_SENSOR_SET_CTX(ViPipe, ctx);

	return CVI_SUCCESS;
}

static CVI_VOID sensor_ctx_exit(VI_PIPE ViPipe)
{
	ISP_SNS_STATE_S *ctx = CVI_NULL;

	VD55G1_SENSOR_GET_CTX(ViPipe, ctx);
	SENSOR_FREE(ctx);
	VD55G1_SENSOR_RESET_CTX(ViPipe);
}

static CVI_S32 sensor_register_callback(VI_PIPE ViPipe, ALG_LIB_S *pstAeLib, ALG_LIB_S *pstAwbLib)
{
	ISP_SENSOR_REGISTER_S stIspRegister;
	AE_SENSOR_REGISTER_S stAeRegister;
	AWB_SENSOR_REGISTER_S stAwbRegister;
	ISP_SNS_ATTR_INFO_S stSnsAttrInfo;
	CVI_S32 s32Ret;

	CMOS_CHECK_POINTER(pstAeLib);
	CMOS_CHECK_POINTER(pstAwbLib);

	if (sensor_ctx_init(ViPipe) != CVI_SUCCESS)
		return CVI_FAILURE;

	stSnsAttrInfo.eSensorId = VD55G1_ID;

	s32Ret  = cmos_init_sensor_exp_function(&stIspRegister.stSnsExp);
	s32Ret |= CVI_ISP_SensorRegCallBack(ViPipe, &stSnsAttrInfo, &stIspRegister);
	if (s32Ret != CVI_SUCCESS) {
		CVI_TRACE_SNS(CVI_DBG_ERR, "sensor register callback function failed!\n");
		return s32Ret;
	}

	s32Ret  = cmos_init_ae_exp_function(&stAeRegister.stAeExp);
	s32Ret |= CVI_AE_SensorRegCallBack(ViPipe, pstAeLib, &stSnsAttrInfo, &stAeRegister);
	if (s32Ret != CVI_SUCCESS) {
		CVI_TRACE_SNS(CVI_DBG_ERR, "sensor register callback function to ae lib failed!\n");
		return s32Ret;
	}

	s32Ret  = cmos_init_awb_exp_function(&stAwbRegister.stAwbExp);
	s32Ret |= CVI_AWB_SensorRegCallBack(ViPipe, pstAwbLib, &stSnsAttrInfo, &stAwbRegister);
	if (s32Ret != CVI_SUCCESS) {
		CVI_TRACE_SNS(CVI_DBG_ERR, "sensor register callback function to awb lib failed!\n");
		return s32Ret;
	}

	return CVI_SUCCESS;
}

static CVI_S32 sensor_unregister_callback(VI_PIPE ViPipe, ALG_LIB_S *pstAeLib, ALG_LIB_S *pstAwbLib)
{
	CVI_S32 s32Ret;

	CMOS_CHECK_POINTER(pstAeLib);
	CMOS_CHECK_POINTER(pstAwbLib);

	s32Ret = CVI_ISP_SensorUnRegCallBack(ViPipe, VD55G1_ID);
	if (s32Ret != CVI_SUCCESS) {
		CVI_TRACE_SNS(CVI_DBG_ERR, "sensor unregister callback function failed!\n");
		return s32Ret;
	}
	s32Ret = CVI_AE_SensorUnRegCallBack(ViPipe, pstAeLib, VD55G1_ID);
	if (s32Ret != CVI_SUCCESS) {
		CVI_TRACE_SNS(CVI_DBG_ERR, "sensor unregister callback function to ae lib failed!\n");
		return s32Ret;
	}
	s32Ret = CVI_AWB_SensorUnRegCallBack(ViPipe, pstAwbLib, VD55G1_ID);
	if (s32Ret != CVI_SUCCESS) {
		CVI_TRACE_SNS(CVI_DBG_ERR, "sensor unregister callback function to awb lib failed!\n");
		return s32Ret;
	}
	sensor_ctx_exit(ViPipe);

	return CVI_SUCCESS;
}

static CVI_S32 sensor_set_init(VI_PIPE ViPipe, ISP_INIT_ATTR_S *pstInitAttr)
{
	CMOS_CHECK_POINTER(pstInitAttr);
	g_au32InitExposure[ViPipe] = pstInitAttr->u32Exposure;
	return CVI_SUCCESS;
}

ISP_SNS_OBJ_S stSnsVd55g1_Obj = {
	.pfnRegisterCallback    = sensor_register_callback,
	.pfnUnRegisterCallback  = sensor_unregister_callback,
	.pfnStandby             = vd55g1_standby,
	.pfnRestart             = vd55g1_restart,
	.pfnMirrorFlip          = vd55g1_mirror_flip,
	.pfnWriteReg            = vd55g1_write_register,
	.pfnReadReg             = vd55g1_read_register,
	.pfnSetBusInfo          = vd55g1_set_bus_info,
	.pfnSetInit             = sensor_set_init,
	.pfnPatchRxAttr         = sensor_patch_rx_attr,
	.pfnPatchI2cAddr        = CVI_NULL,
	.pfnGetRxAttr           = sensor_rx_attr,
	.pfnExpSensorCb         = cmos_init_sensor_exp_function,
	.pfnExpAeCb             = cmos_init_ae_exp_function,
	.pfnSnsProbe            = vd55g1_probe,
};
