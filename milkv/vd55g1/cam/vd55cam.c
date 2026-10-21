// SPDX-License-Identifier: GPL-2.0-only
/*
 * vd55cam - VD55G1 capture through the Sophgo media stack:
 *
 *   sensor (stSnsVd55g1_Obj) -> MIPI RX -> VI -> ISP (mono, Sophgo AE)
 *   -> VI channel (NV21) -> VPSS (hardware scaler) -> gray frames
 *
 * Same bring-up order as the vendor's sample_common_platform.c
 * (SAMPLE_PLAT_VI_INIT), for one sensor on pipe 0.
 */
#include "vd55cam.h"

#include <pthread.h>
#include <stdio.h>
#include <string.h>

#include <cvi_sys.h>
#include <cvi_vb.h>
#include <cvi_vi.h>
#include <cvi_vpss.h>
#include <cvi_isp.h>
#include <cvi_ae.h>
#include <cvi_awb.h>
#include <cvi_sns_ctrl.h>

#include "vd55g1.h"
#include "vd55g1_cmos_ex.h"

extern ISP_SNS_OBJ_S stSnsVd55g1_Obj;

#define PIPE		0
#define VI_DEV		0
#define VI_CHN		0
#define VPSS_GRP	0
#define VPSS_CHN	0
#define I2C_BUS		2	/* J2 connector */
#define VB_BLK_CNT	6

#define ALIGN_UP(x, a)	(((x) + (a) - 1) / (a) * (a))

#define CHECK(call) do {						\
	CVI_S32 _r = (call);						\
	if (_r != CVI_SUCCESS) {					\
		fprintf(stderr, "vd55cam: %s failed: %#x\n", #call, _r);\
		ret = _r ? _r : -1;					\
		goto fail;						\
	}								\
} while (0)

static struct {
	int open;
	int sys_up, sns_reg, algo_reg, dev_up, pipe_up, isp_up, isp_thread;
	int chn_up, vpss_grp, vpss_chn, vpss_started, bound;
	pthread_t isp_tid;
	uint32_t w, h, out_w, out_h;
	float fps;
	int64_t seq;
} g;

static ALG_LIB_S g_ae_lib = { .s32Id = PIPE, .acLibName = CVI_AE_LIB_NAME };
static ALG_LIB_S g_awb_lib = { .s32Id = PIPE, .acLibName = CVI_AWB_LIB_NAME };

static void *isp_run(void *arg)
{
	(void)arg;
	CVI_ISP_Run(PIPE);	/* returns after CVI_ISP_Exit() */
	return NULL;
}

static int start_sensor(void)
{
	ISP_SNS_OBJ_S *sns = &stSnsVd55g1_Obj;
	ISP_SNS_COMMBUS_U bus = { .s8I2cDev = I2C_BUS };
	ISP_SENSOR_EXP_FUNC_S exp;
	ISP_CMOS_SENSOR_IMAGE_MODE_S mode = {
		.u16Width = g.w, .u16Height = g.h, .f32Fps = g.fps,
	};
	int ret = 0;

	CHECK(sns->pfnSetBusInfo(PIPE, bus));
	CHECK(sns->pfnRegisterCallback(PIPE, &g_ae_lib, &g_awb_lib));
	g.sns_reg = 1;
	CHECK(sns->pfnExpSensorCb(&exp));
	CHECK(exp.pfn_cmos_set_image_mode(PIPE, &mode));
	CHECK(exp.pfn_cmos_set_wdr_mode(PIPE, WDR_MODE_NONE));
fail:
	return ret;
}

static int start_vi(void)
{
	VI_DEV_ATTR_S dev = {
		.enIntfMode = VI_MODE_MIPI,
		.enWorkMode = VI_WORK_MODE_1Multiplex,
		.enScanMode = VI_SCAN_PROGRESSIVE,
		.as32AdChnId = { -1, -1, -1, -1 },
		.enDataSeq = VI_DATA_SEQ_YUYV,
		.stSynCfg = {
			VI_VSYNC_PULSE, VI_VSYNC_NEG_LOW, VI_HSYNC_VALID_SINGNAL,
			VI_HSYNC_NEG_HIGH, VI_VSYNC_VALID_SIGNAL, VI_VSYNC_VALID_NEG_HIGH,
			{ 0, g.w, 0, 0, g.h, 0, 0, 0, 0 },
		},
		.enInputDataType = VI_DATA_TYPE_RGB,
		.stSize = { g.w, g.h },
		.stWDRAttr = { WDR_MODE_NONE, g.h, 0 },
		.enBayerFormat = BAYER_FORMAT_BG,
		.snrFps = (CVI_U32)g.fps,
	};
	VI_PIPE_ATTR_S pipe = {
		.bYuvSkip = CVI_FALSE,
		.u32MaxW = g.w,
		.u32MaxH = g.h,
		.enPixFmt = PIXEL_FORMAT_RGB_BAYER_12BPP,
		.enCompressMode = COMPRESS_MODE_NONE,
		.enBitWidth = DATA_BITWIDTH_12,
		.stFrameRate = { -1, -1 },
		.bNrEn = CVI_FALSE,
		.bYuvBypassPath = CVI_FALSE,
	};
	SNS_COMBO_DEV_ATTR_S rx;
	ISP_SNS_OBJ_S *sns = &stSnsVd55g1_Obj;
	int ret = 0;

	CHECK(CVI_VI_SetDevNum(1));
	CHECK(CVI_VI_SetDevAttr(VI_DEV, &dev));
	CHECK(CVI_VI_EnableDev(VI_DEV));
	g.dev_up = 1;

	CHECK(sns->pfnGetRxAttr(PIPE, &rx));
	CHECK(CVI_MIPI_SetMipiReset(rx.devno, 1));
	CHECK(CVI_MIPI_SetMipiAttr(PIPE, &rx));
	if (sns->pfnSnsProbe(PIPE) != CVI_SUCCESS) {
		fprintf(stderr, "vd55cam: no VD55G1 on i2c-%d, camera power on? "
			"(sudo board/vd55g1-power.sh on)\n", I2C_BUS);
		ret = -1;
		goto fail;
	}

	CHECK(CVI_VI_CreatePipe(PIPE, &pipe));
	CHECK(CVI_VI_StartPipe(PIPE));
	g.pipe_up = 1;
fail:
	return ret;
}

static int start_isp(void)
{
	ISP_BIND_ATTR_S bind = { .sensorId = 0 };
	ISP_PUB_ATTR_S pub = {
		.stWndRect = { 0, 0, g.w, g.h },
		.stSnsSize = { g.w, g.h },
		.f32FrameRate = g.fps,
		.enBayer = BAYER_BGGR,
		.enWDRMode = WDR_MODE_NONE,
		.u8SnsMode = 0,
	};
	ISP_MONO_ATTR_S mono = { .Enable = CVI_TRUE, .UpdateInterval = 1 };
	int ret = 0;

	CHECK(CVI_AE_Register(PIPE, &g_ae_lib));
	CHECK(CVI_AWB_Register(PIPE, &g_awb_lib));
	g.algo_reg = 1;
	bind.stAeLib = g_ae_lib;
	bind.stAwbLib = g_awb_lib;
	CHECK(CVI_ISP_SetBindAttr(PIPE, &bind));
	CHECK(CVI_ISP_MemInit(PIPE));
	CHECK(CVI_ISP_SetPubAttr(PIPE, &pub));
	CHECK(CVI_ISP_Init(PIPE));	/* calls the sensor init: boot, configure, stream */
	g.isp_up = 1;
	CHECK(CVI_ISP_SetMonoAttr(PIPE, &mono));
	if (pthread_create(&g.isp_tid, NULL, isp_run, NULL)) {
		fprintf(stderr, "vd55cam: cannot start the ISP thread\n");
		ret = -1;
		goto fail;
	}
	g.isp_thread = 1;
fail:
	return ret;
}

/*
 * The untuned ISP defaults brighten each frame depending on its content
 * (DRC, local contrast, dehaze). Switch those off so the same scene
 * brightness always gives the same gray value, and use a plain sRGB gamma.
 */
static int set_plain_tone(void)
{
	ISP_GAMMA_ATTR_S gamma;
	ISP_DRC_ATTR_S drc;
	ISP_DCI_ATTR_S dci;
	ISP_LDCI_ATTR_S ldci;
	ISP_DEHAZE_ATTR_S dehaze;
	int ret = 0;

	CHECK(CVI_ISP_GetGammaAttr(PIPE, &gamma));
	gamma.Enable = CVI_TRUE;
	gamma.enCurveType = ISP_GAMMA_CURVE_SRGB;
	CHECK(CVI_ISP_SetGammaAttr(PIPE, &gamma));

	CHECK(CVI_ISP_GetDRCAttr(PIPE, &drc));
	drc.Enable = CVI_FALSE;
	CHECK(CVI_ISP_SetDRCAttr(PIPE, &drc));
	CHECK(CVI_ISP_GetDCIAttr(PIPE, &dci));
	dci.Enable = CVI_FALSE;
	CHECK(CVI_ISP_SetDCIAttr(PIPE, &dci));
	CHECK(CVI_ISP_GetLDCIAttr(PIPE, &ldci));
	ldci.Enable = CVI_FALSE;
	CHECK(CVI_ISP_SetLDCIAttr(PIPE, &ldci));
	CHECK(CVI_ISP_GetDehazeAttr(PIPE, &dehaze));
	dehaze.Enable = CVI_FALSE;
	CHECK(CVI_ISP_SetDehazeAttr(PIPE, &dehaze));
fail:
	return ret;
}

static int start_chn_vpss(void)
{
	VI_CHN_ATTR_S chn = {
		.stSize = { g.w, g.h },
		.enPixelFormat = PIXEL_FORMAT_NV21,
		.enDynamicRange = DYNAMIC_RANGE_SDR8,
		.enVideoFormat = VIDEO_FORMAT_LINEAR,
		.enCompressMode = COMPRESS_MODE_NONE,
		.u32Depth = 0,
		.stFrameRate = { -1, -1 },
		.u32BindVbPool = -1,
	};
	VPSS_GRP_ATTR_S grp = {
		.u32MaxW = g.w,
		.u32MaxH = g.h,
		.enPixelFormat = PIXEL_FORMAT_NV21,
		.stFrameRate = { -1, -1 },
		.u8VpssDev = 0,
	};
	VPSS_CHN_ATTR_S vchn = {
		.u32Width = g.out_w,
		.u32Height = g.out_h,
		.enVideoFormat = VIDEO_FORMAT_LINEAR,
		.enPixelFormat = PIXEL_FORMAT_YUV_400,
		.stFrameRate = { -1, -1 },
		.bMirror = CVI_FALSE,
		.bFlip = CVI_FALSE,
		.u32Depth = 2,
		.stAspectRatio = { .enMode = ASPECT_RATIO_NONE },
		.stNormalize = { .bEnable = CVI_FALSE },
	};
	MMF_CHN_S src = { .enModId = CVI_ID_VI, .s32DevId = PIPE, .s32ChnId = VI_CHN };
	MMF_CHN_S dst = { .enModId = CVI_ID_VPSS, .s32DevId = VPSS_GRP, .s32ChnId = 0 };
	int ret = 0;

	CHECK(CVI_VI_SetChnAttr(PIPE, VI_CHN, &chn));
	CHECK(CVI_VI_EnableChn(PIPE, VI_CHN));
	g.chn_up = 1;

	CHECK(CVI_VPSS_CreateGrp(VPSS_GRP, &grp));
	g.vpss_grp = 1;
	CHECK(CVI_VPSS_SetChnAttr(VPSS_GRP, VPSS_CHN, &vchn));
	CHECK(CVI_VPSS_EnableChn(VPSS_GRP, VPSS_CHN));
	g.vpss_chn = 1;
	CHECK(CVI_VPSS_StartGrp(VPSS_GRP));
	g.vpss_started = 1;
	CHECK(CVI_SYS_Bind(&src, &dst));
	g.bound = 1;
fail:
	return ret;
}

static void release_leftovers(void)
{
	MMF_CHN_S src = { .enModId = CVI_ID_VI, .s32DevId = PIPE, .s32ChnId = VI_CHN };
	MMF_CHN_S dst = { .enModId = CVI_ID_VPSS, .s32DevId = VPSS_GRP, .s32ChnId = 0 };

	CVI_SYS_UnBind(&src, &dst);
	CVI_VPSS_StopGrp(VPSS_GRP);
	CVI_VPSS_DisableChn(VPSS_GRP, VPSS_CHN);
	CVI_VPSS_DestroyGrp(VPSS_GRP);
	CVI_VI_DisableChn(PIPE, VI_CHN);
	CVI_VI_StopPipe(PIPE);
	CVI_VI_DestroyPipe(PIPE);
	CVI_VI_DisableDev(VI_DEV);
}

int vd55cam_open(int out_w, int out_h, float fps, int flags)
{
	VI_VPSS_MODE_S vi_vpss = { .aenMode = { [0] = VI_OFFLINE_VPSS_OFFLINE } };
	VB_CONFIG_S vb = { .u32MaxPoolCnt = 1 };
	int ret = 0;

	if (g.open)
		vd55cam_close();
	memset(&g, 0, sizeof(g));
	g.w = 768;	/* multiple of 64, see vd55g1_cmos_param.h */
	g.h = flags & VD55CAM_FULL_HEIGHT ? 704 : 576;
	g.out_w = out_w;
	g.out_h = out_h;
	g.fps = fps;
	if (out_w < 32 || out_h < 32 || out_w > (int)g.w || out_h > (int)g.h ||
	    (out_w & 1) || (out_h & 1) || fps < 1.4f || fps > 60) {
		fprintf(stderr, "vd55cam: bad size %dx%d or fps %.1f\n", out_w, out_h, fps);
		return -1;
	}
	g.open = 1;

	/*
	 * 1. buffers + media system. One pool for the NV21 VI frames, sized for
	 * the biggest mode: the kernel keeps the pool of the first camera start
	 * after boot (the VI holds on to blocks of it), so a smaller pool from
	 * another program stays until the next reboot.
	 */
	CVI_SYS_Exit();
	CVI_VB_Exit();
	vb.astCommPool[0].u32BlkSize = ALIGN_UP(768, 64) * ALIGN_UP(704, 64) * 3 / 2;
	vb.astCommPool[0].u32BlkCnt = VB_BLK_CNT;
	vb.astCommPool[0].enRemapMode = VB_REMAP_MODE_CACHED;
	CHECK(CVI_VB_SetConfig(&vb));
	CHECK(CVI_VB_Init());
	CHECK(CVI_SYS_Init());
	g.sys_up = 1;
	/* a process that died without vd55cam_close() (kill -9) leaves the
	 * kernel side set up; only one process can use the camera anyway */
	release_leftovers();
	CHECK(CVI_SYS_SetVIVPSSMode(&vi_vpss));
	CHECK(CVI_SYS_SetVPSSMode(VPSS_MODE_SINGLE));

	/* 2-6 */
	if ((ret = start_sensor()) || (ret = start_vi()) || (ret = start_isp()))
		goto fail;
	if (!g_pastVd55g1[PIPE] || !g_pastVd55g1[PIPE]->bInit) {
		fprintf(stderr, "vd55cam: sensor start failed (journalctl -b | grep vd55g1)\n");
		ret = -1;
		goto fail;
	}
	if (!(flags & VD55CAM_ISP_TONE) && (ret = set_plain_tone()))
		goto fail;
	if ((ret = start_chn_vpss()))
		goto fail;
	return 0;
fail:
	vd55cam_close();
	return ret < 0 ? ret : -ret;
}

int64_t vd55cam_read(uint8_t *dst, int timeout_ms)
{
	VIDEO_FRAME_INFO_S frm;
	VIDEO_FRAME_S *f = &frm.stVFrame;
	uint32_t y, rows, cols, len;
	uint8_t *va;

	if (!g.bound)
		return -1;
	if (CVI_VPSS_GetChnFrame(VPSS_GRP, VPSS_CHN, &frm, timeout_ms) != CVI_SUCCESS)
		return 0;

	len = f->u32Stride[0] * f->u32Height;
	va = CVI_SYS_MmapCache(f->u64PhyAddr[0], len);
	if (!va) {
		CVI_VPSS_ReleaseChnFrame(VPSS_GRP, VPSS_CHN, &frm);
		return -1;
	}
	CVI_SYS_IonInvalidateCache(f->u64PhyAddr[0], va, len);
	rows = f->u32Height < g.out_h ? f->u32Height : g.out_h;
	cols = f->u32Width < g.out_w ? f->u32Width : g.out_w;
	for (y = 0; y < rows; y++)
		memcpy(dst + (size_t)y * g.out_w, va + (size_t)y * f->u32Stride[0], cols);
	CVI_SYS_Munmap(va, len);
	CVI_VPSS_ReleaseChnFrame(VPSS_GRP, VPSS_CHN, &frm);

	return ++g.seq;
}

static int read_reg16(int addr)
{
	int lo = stSnsVd55g1_Obj.pfnReadReg(PIPE, addr);
	int hi = stSnsVd55g1_Obj.pfnReadReg(PIPE, addr + 1);

	return lo < 0 || hi < 0 ? -1 : lo | hi << 8;
}

int vd55cam_get_info(struct vd55cam_info *info)
{
	int expo, again, dgain;

	if (!g.isp_up)
		return -1;
	memset(info, 0, sizeof(*info));
	info->sensor_w = g.w;
	info->sensor_h = g.h;
	info->out_w = g.out_w;
	info->out_h = g.out_h;
	info->fps = g.fps;

	expo = read_reg16(VD55G1_REG_APPLIED_COARSE_EXPOSURE);
	again = read_reg16(VD55G1_REG_APPLIED_ANALOG_GAIN);
	dgain = read_reg16(VD55G1_REG_APPLIED_DIGITAL_GAIN);
	if (expo < 0 || again < 0 || dgain < 0)
		return -1;
	info->exposure_lines = expo;
	info->exposure_us = (uint64_t)expo * vd55g1_line_ns(PIPE) / 1000;
	info->again = 32.0f / (32 - (again & 0x1f));
	info->dgain = dgain / 256.0f;
	return 0;
}

void vd55cam_close(void)
{
	ISP_SNS_OBJ_S *sns = &stSnsVd55g1_Obj;
	MMF_CHN_S src = { .enModId = CVI_ID_VI, .s32DevId = PIPE, .s32ChnId = VI_CHN };
	MMF_CHN_S dst = { .enModId = CVI_ID_VPSS, .s32DevId = VPSS_GRP, .s32ChnId = 0 };
	ISP_SENSOR_EXP_FUNC_S exp;

	if (!g.open)
		return;

	if (g.bound)
		CVI_SYS_UnBind(&src, &dst);
	if (g.vpss_started)
		CVI_VPSS_StopGrp(VPSS_GRP);
	if (g.vpss_chn)
		CVI_VPSS_DisableChn(VPSS_GRP, VPSS_CHN);
	if (g.vpss_grp)
		CVI_VPSS_DestroyGrp(VPSS_GRP);
	if (g.chn_up)
		CVI_VI_DisableChn(PIPE, VI_CHN);

	/* sensor out of streaming before the receiver goes away */
	if (g.sns_reg)
		sns->pfnStandby(PIPE);
	if (g.isp_up)
		CVI_ISP_Exit(PIPE);
	if (g.isp_thread)
		pthread_join(g.isp_tid, NULL);
	if (g.algo_reg) {
		CVI_AE_UnRegister(PIPE, &g_ae_lib);
		CVI_AWB_UnRegister(PIPE, &g_awb_lib);
	}
	if (g.sns_reg) {
		if (sns->pfnExpSensorCb(&exp) == CVI_SUCCESS && exp.pfn_cmos_sensor_exit)
			exp.pfn_cmos_sensor_exit(PIPE);
		sns->pfnUnRegisterCallback(PIPE, &g_ae_lib, &g_awb_lib);
	}

	if (g.pipe_up) {
		CVI_VI_StopPipe(PIPE);
		CVI_VI_DestroyPipe(PIPE);
	}
	if (g.dev_up)
		CVI_VI_DisableDev(VI_DEV);
	if (g.sys_up) {
		CVI_SYS_Exit();
		CVI_VB_Exit();
	}
	memset(&g, 0, sizeof(g));
}
