// SPDX-License-Identifier: GPL-2.0-only
/*
 * ST VD55G1 sensor driver for the Sophgo ISP: I2C access, power-up (boot +
 * firmware patch), configuration and streaming. The register work itself is
 * in vd55g1.c.
 *
 * The sensor's power and the J2 pin mux are not handled here, see
 * board/vd55g1-power.sh.
 */
#include <stdio.h>
#include <stdlib.h>
#include <syslog.h>
#include <unistd.h>

#include <linux/cvi_comm_video.h>
#include "cvi_debug.h"
#include "cvi_sns_ctrl.h"

#include "vd55g1.h"
#include "vd55g1_cmos_ex.h"

#define REG_MODEL_ID		0x0000
#define REG_ORIENTATION		0x0302
#define MODEL_ID_CUT2		0x53354731
#define MODEL_ID_CUT3		0x53354733

const CVI_U8 vd55g1_i2c_addr = VD55G1_I2C_ADDR;
const CVI_U32 vd55g1_addr_byte = 2;
const CVI_U32 vd55g1_data_byte = 1;

static struct vd55g1 g_dev[VI_MAX_PIPE_NUM] = { [0 ... VI_MAX_PIPE_NUM - 1] = { .fd = -1 } };
static CVI_BOOL g_streaming[VI_MAX_PIPE_NUM];

static int vd55g1_i2c_init(VI_PIPE ViPipe)
{
	char dev[16];

	if (g_dev[ViPipe].fd >= 0)
		return CVI_SUCCESS;
	snprintf(dev, sizeof(dev), "/dev/i2c-%d", g_aunVd55g1_BusInfo[ViPipe].s8I2cDev);
	if (vd55g1_open(&g_dev[ViPipe], dev, vd55g1_i2c_addr)) {
		CVI_TRACE_SNS(CVI_DBG_ERR, "open %s failed\n", dev);
		return CVI_FAILURE;
	}
	return CVI_SUCCESS;
}

static void vd55g1_i2c_exit(VI_PIPE ViPipe)
{
	vd55g1_close(&g_dev[ViPipe]);
}

int vd55g1_read_register(VI_PIPE ViPipe, int addr)
{
	uint32_t val;

	if (g_dev[ViPipe].fd < 0 || vd55g1_read(&g_dev[ViPipe], addr, 1, &val))
		return CVI_FAILURE;
	return val;
}

int vd55g1_write_register(VI_PIPE ViPipe, int addr, int data)
{
	if (g_dev[ViPipe].fd < 0)
		return CVI_SUCCESS;
	if (vd55g1_write(&g_dev[ViPipe], addr, 1, data))
		return CVI_FAILURE;
	syslog(LOG_DEBUG, "i2c w 0x%x 0x%x\n", addr, data);
	return CVI_SUCCESS;
}

/* Is the sensor there? Needs power (vd55g1-power.sh on), works before boot. */
int vd55g1_probe(VI_PIPE ViPipe)
{
	uint32_t id;

	if (vd55g1_i2c_init(ViPipe) != CVI_SUCCESS)
		return CVI_FAILURE;
	if (vd55g1_read(&g_dev[ViPipe], REG_MODEL_ID, 4, &id)) {
		CVI_TRACE_SNS(CVI_DBG_ERR, "no answer on i2c-%d 0x%02x, camera power on?\n",
			      g_aunVd55g1_BusInfo[ViPipe].s8I2cDev, vd55g1_i2c_addr);
		return CVI_FAILURE;
	}
	if (id != MODEL_ID_CUT2 && id != MODEL_ID_CUT3) {
		CVI_TRACE_SNS(CVI_DBG_ERR, "unexpected model id 0x%08x\n", id);
		return CVI_FAILURE;
	}
	return CVI_SUCCESS;
}

void vd55g1_standby(VI_PIPE ViPipe)
{
	if (g_streaming[ViPipe] && !vd55g1_stop(&g_dev[ViPipe]))
		g_streaming[ViPipe] = CVI_FALSE;
}

void vd55g1_restart(VI_PIPE ViPipe)
{
	if (!g_streaming[ViPipe] && !vd55g1_stream_on(&g_dev[ViPipe]))
		g_streaming[ViPipe] = CVI_TRUE;
}

void vd55g1_mirror_flip(VI_PIPE ViPipe, ISP_SNS_MIRRORFLIP_TYPE_E eSnsMirrorFlip)
{
	/* bit 0 horizontal, bit 1 vertical; mono sensor, no Bayer phase to fix */
	if (eSnsMirrorFlip < ISP_SNS_BUTT)
		vd55g1_write_register(ViPipe, REG_ORIENTATION, eSnsMirrorFlip);
}

void vd55g1_init(VI_PIPE ViPipe)
{
	ISP_SNS_STATE_S *pstSnsState = g_pastVd55g1[ViPipe];
	const ISP_WDR_SIZE_S *img;
	struct vd55g1_config cfg = {
		.bpp = 8,
		.mipi_rate = VD55G1_MIPI_RATE,
		.swap_pn = VD55G1_SWAP_PN,
		.pattern = VD55G1_PATTERN_OFF,
		.manual_exposure = true,
	};
	CVI_U32 fl, expo, again, dgain;
	struct vd55g1 *s = &g_dev[ViPipe];
	uint8_t state;

	if (!pstSnsState || vd55g1_i2c_init(ViPipe) != CVI_SUCCESS)
		return;

	/* boot ROM -> firmware patch -> standby (skipped if already booted) */
	if (vd55g1_power_on(s, VD55G1_XCLK_HZ)) {
		CVI_TRACE_SNS(CVI_DBG_ERR, "power-up failed, camera power on?\n");
		return;
	}
	/* an earlier run that was killed can leave it streaming */
	if (!vd55g1_get_state(s, &state) && state == VD55G1_FSM_STREAMING)
		vd55g1_stop(s);
	g_streaming[ViPipe] = CVI_FALSE;

	img = vd55g1_mode_size(pstSnsState->u8ImgMode);
	vd55g1_sync_state(ViPipe, &fl, &expo, &again, &dgain);
	cfg.width = img->stSnsSize.u32Width;
	cfg.height = img->stSnsSize.u32Height;
	cfg.frame_length = fl;
	cfg.expo_lines = expo;
	cfg.again = again;
	cfg.dgain = dgain;
	/* VD55G1_PATTERN=1 grey ramp, 2 noise: sensor test pattern instead of the image */
	if (getenv("VD55G1_PATTERN"))
		cfg.pattern = atoi(getenv("VD55G1_PATTERN"));

	if (vd55g1_configure(s, &cfg)) {
		CVI_TRACE_SNS(CVI_DBG_ERR, "configure failed\n");
		return;
	}
	if (vd55g1_line_time_ns(s) != vd55g1_line_ns(ViPipe))
		CVI_TRACE_SNS(CVI_DBG_WARN, "line time %u ns, AE assumes %u ns\n",
			      vd55g1_line_time_ns(s), vd55g1_line_ns(ViPipe));
	if (vd55g1_stream_on(s)) {
		CVI_TRACE_SNS(CVI_DBG_ERR, "stream on failed\n");
		return;
	}
	g_streaming[ViPipe] = CVI_TRUE;
	pstSnsState->bInit = CVI_TRUE;

	syslog(LOG_INFO, "ViPipe %d: VD55G1 (id 0x%08x) %ux%u RAW8, %u lines/frame, streaming\n",
	       ViPipe, s->model_id, cfg.width, cfg.height, fl);
}

void vd55g1_exit(VI_PIPE ViPipe)
{
	vd55g1_standby(ViPipe);
	vd55g1_i2c_exit(ViPipe);
}
