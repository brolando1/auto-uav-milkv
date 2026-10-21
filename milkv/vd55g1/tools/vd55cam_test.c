// SPDX-License-Identifier: GPL-2.0-only
/*
 * vd55cam_test - run the VD55G1 through libvd55cam, print frame rate and
 * exposure once a second, save the last frame as PGM.
 *
 *   vd55cam_test [-t secs] [-s WxH] [-f fps] [-F] [-T] [-o file.pgm] [-R raw.pgm]
 *     -F  full sensor height (768x704) instead of 768x576
 *     -T  keep the ISP's adaptive tone mapping
 *     -R  also save a raw sensor frame (before the ISP) at the end
 */
#include "vd55cam.h"

#include <string.h>
#include <cvi_sys.h>
#include <cvi_vi.h>

#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t stop;

static void on_signal(int sig)
{
	(void)sig;
	stop = 1;
}

/* Raw frame from the VI (before the ISP), 12-bit packed, RAW8 in the high byte. */
static void dump_raw(const char *path, int w, int h)
{
	VI_DUMP_ATTR_S dump = { .bEnable = CVI_TRUE, .u32Depth = 0, .enDumpType = VI_DUMP_TYPE_RAW };
	VIDEO_FRAME_INFO_S frm[2];
	VIDEO_FRAME_S *f = &frm[0].stVFrame;
	uint8_t *va, *gray;
	uint32_t stride;
	FILE *fp;

	memset(frm, 0, sizeof(frm));
	frm[0].stVFrame.enPixelFormat = PIXEL_FORMAT_RGB_BAYER_12BPP;
	frm[1].stVFrame.enPixelFormat = PIXEL_FORMAT_RGB_BAYER_12BPP;
	if (CVI_VI_SetPipeDumpAttr(0, &dump) || CVI_VI_GetPipeFrame(0, frm, 2000)) {
		fprintf(stderr, "raw dump failed\n");
		return;
	}
	va = CVI_SYS_Mmap(f->u64PhyAddr[0], f->u32Length[0]);
	printf("raw: %ux%u stride %u len %u\n", f->u32Width, f->u32Height, f->u32Stride[0], f->u32Length[0]);
	stride = f->u32Stride[0] ? f->u32Stride[0] : f->u32Length[0] / f->u32Height;
	gray = malloc((size_t)w * h);
	for (int y = 0; y < h && (uint32_t)y < f->u32Height; y++)
		for (int x = 0; x < w; x += 2) {
			gray[y * w + x] = va[y * stride + x / 2 * 3];
			gray[y * w + x + 1] = va[y * stride + x / 2 * 3 + 1];
		}
	if ((fp = fopen(path, "wb"))) {
		fprintf(fp, "P5\n%d %d\n255\n", w, h);
		fwrite(gray, 1, (size_t)w * h, fp);
		fclose(fp);
		printf("raw frame in %s\n", path);
	}
	free(gray);
	CVI_SYS_Munmap(va, f->u32Length[0]);
	CVI_VI_ReleasePipeFrame(0, frm);
}

static double now(void)
{
	struct timespec ts;

	clock_gettime(CLOCK_MONOTONIC, &ts);
	return ts.tv_sec + ts.tv_nsec * 1e-9;
}

int main(int argc, char **argv)
{
	int w = 324, h = 244, flags = 0, secs = 5, opt;
	const char *raw = NULL;
	float fps = 30;
	const char *out = "/tmp/vd55cam_last.pgm";
	struct vd55cam_info info;
	double t0, last;
	long frames = 0, frames_sec = 0;
	uint8_t *buf;
	FILE *f;

	while ((opt = getopt(argc, argv, "t:s:f:FTo:R:")) != -1) {
		switch (opt) {
		case 't': secs = atoi(optarg); break;
		case 's': if (sscanf(optarg, "%dx%d", &w, &h) != 2) return 1; break;
		case 'f': fps = atof(optarg); break;
		case 'F': flags |= VD55CAM_FULL_HEIGHT; break;
		case 'T': flags |= VD55CAM_ISP_TONE; break;
		case 'o': out = optarg; break;
		case 'R': raw = optarg; break;
		default:
			fprintf(stderr, "usage: %s [-t secs] [-s WxH] [-f fps] [-F] [-T] [-o file.pgm] [-R raw.pgm]\n", argv[0]);
			return 1;
		}
	}
	buf = malloc((size_t)w * h);
	if (!buf)
		return 1;
	signal(SIGINT, on_signal);
	signal(SIGTERM, on_signal);

	if (vd55cam_open(w, h, fps, flags)) {
		fprintf(stderr, "vd55cam_open failed\n");
		return 1;
	}
	t0 = last = now();
	while (!stop && now() - t0 < secs) {
		int64_t seq = vd55cam_read(buf, 500);

		if (seq < 0)
			break;
		if (seq == 0) {
			printf("timeout, no frame in 500 ms\n");
			continue;
		}
		frames++;
		frames_sec++;
		if (now() - last >= 1.0) {
			long sum = 0;

			for (int i = 0; i < w * h; i++)
				sum += buf[i];
			vd55cam_get_info(&info);
			printf("%5.1f fps  mean %3ld  exposure %u lines (%u us)  again %.2fx  dgain %.2fx\n",
			       frames_sec / (now() - last), sum / (w * h), info.exposure_lines,
			       info.exposure_us, info.again, info.dgain);
			fflush(stdout);
			frames_sec = 0;
			last = now();
		}
	}
	if (raw)
		dump_raw(raw, 768, flags & VD55CAM_FULL_HEIGHT ? 704 : 576);
	vd55cam_close();

	printf("%ld frames in %.1f s\n", frames, now() - t0);
	if (frames && (f = fopen(out, "wb"))) {
		fprintf(f, "P5\n%d %d\n255\n", w, h);
		fwrite(buf, 1, (size_t)w * h, f);
		fclose(f);
		printf("last frame in %s\n", out);
	}
	free(buf);
	return frames ? 0 : 1;
}
