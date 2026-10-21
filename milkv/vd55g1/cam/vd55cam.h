/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * vd55cam - grayscale frames from the VD55G1 on the Milk-V Duo S.
 *
 * Sensor (libsns_vd55g1) -> MIPI -> VI -> ISP (mono, Sophgo AE) -> VPSS scaler
 * -> 8-bit gray frames of the requested size. Plain C API, meant for ctypes.
 * Needs root and the camera power on (board/vd55g1-power.sh on).
 */
#ifndef VD55CAM_H
#define VD55CAM_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

struct vd55cam_info {
	uint32_t sensor_w, sensor_h;	/* sensor window */
	uint32_t out_w, out_h;		/* frames returned by vd55cam_read */
	float fps;
	uint32_t exposure_lines;	/* applied, read back from the sensor */
	uint32_t exposure_us;
	float again, dgain;		/* applied analog / digital gain, x */
};

/* vd55cam_open() flags */
#define VD55CAM_FULL_HEIGHT	1	/* 768x704 sensor window instead of 768x576 (4:3) */
#define VD55CAM_ISP_TONE	2	/* keep the ISP's adaptive tone mapping (DRC, local
					 * contrast, dehaze); default: off, plain sRGB gamma */

/*
 * Start the camera. out_w/out_h: size of the returned frames (hardware
 * scaler, even numbers). fps: 1.4..60. Returns 0 or a negative error;
 * details go to stderr.
 */
int vd55cam_open(int out_w, int out_h, float fps, int flags);

/*
 * Wait up to timeout_ms for the next frame and copy it into dst
 * (out_w * out_h bytes, rows packed). Returns the frame counter (>= 1),
 * 0 on timeout or a negative error.
 */
int64_t vd55cam_read(uint8_t *dst, int timeout_ms);

int vd55cam_get_info(struct vd55cam_info *info);

/* Stop everything; safe to call more than once. */
void vd55cam_close(void);

#ifdef __cplusplus
}
#endif

#endif
