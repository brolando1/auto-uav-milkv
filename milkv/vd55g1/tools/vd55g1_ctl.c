// SPDX-License-Identifier: GPL-2.0-only
/*
 * vd55g1_ctl - talk to the VD55G1 over I2C only (no MIPI receiver involved).
 *
 *   vd55g1_ctl status           show state, id, patch, exposure
 *   vd55g1_ctl probe            boot + patch the sensor, then show status
 *   vd55g1_ctl start [secs]     boot, stream for secs (default 3), stop
 *   vd55g1_ctl stream           boot and leave it streaming
 *   vd55g1_ctl stop             stop streaming
 *
 * Environment: VD55G1_PATTERN=1|2 selects a test pattern for start/stream.
 */
#include "vd55g1.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define I2C_DEV		"/dev/i2c-2"
#define XCLK_HZ		12000000	/* 12 MHz oscillator on the PCB4189 */

static void status(struct vd55g1 *s)
{
	uint32_t id = 0, patch = 0, expo = 0;
	uint8_t state = 0;

	vd55g1_get_state(s, &state);
	vd55g1_read(s, 0x0000, 4, &id);
	vd55g1_read(s, 0x0012, 2, &patch);
	vd55g1_read(s, 0x00e8, 2, &expo);
	printf("state     : 0x%02x (%s)\n", state, vd55g1_state_name(state));
	printf("model id  : 0x%08x\n", id);
	printf("fw patch  : %u.%u\n", patch >> 8, patch & 0xff);
	printf("exposure  : %u lines (applied)\n", expo);
}

static struct vd55g1_config default_config(void)
{
	const char *p = getenv("VD55G1_PATTERN");
	struct vd55g1_config cfg = {
		.width = 800,
		.height = 704,
		.bpp = 8,
		.mipi_rate = 600000000,
		.swap_pn = true,	/* "MIPI Lane P/N shall be swap by SW" */
		.frame_length = 1860,
		.pattern = p ? atoi(p) : VD55G1_PATTERN_OFF,
	};
	return cfg;
}

int main(int argc, char **argv)
{
	const char *cmd = argc > 1 ? argv[1] : "status";
	struct vd55g1_config cfg = default_config();
	struct vd55g1 s;
	int ret = 0, i;

	if (vd55g1_open(&s, I2C_DEV, VD55G1_I2C_ADDR))
		return 1;

	if (!strcmp(cmd, "status")) {
		status(&s);
	} else if (!strcmp(cmd, "probe")) {
		ret = vd55g1_power_on(&s, XCLK_HZ);
		status(&s);
	} else if (!strcmp(cmd, "start") || !strcmp(cmd, "stream")) {
		int secs = argc > 2 ? atoi(argv[2]) : 3;

		ret = vd55g1_power_on(&s, XCLK_HZ);
		if (!ret)
			ret = vd55g1_start(&s, &cfg);
		if (!ret) {
			printf("streaming %ux%u RAW%u, %u Mbit/s, line %u, pixclk %u MHz\n",
			       cfg.width, cfg.height, cfg.bpp,
			       cfg.mipi_rate / 1000000, s.line_length,
			       s.pixel_clock_hz / 1000000);
			if (!strcmp(cmd, "start")) {
				for (i = 0; i < secs; i++) {
					sleep(1);
					status(&s);
				}
				ret = vd55g1_stop(&s);
			}
		}
		status(&s);
	} else if (!strcmp(cmd, "stop")) {
		ret = vd55g1_stop(&s);
		status(&s);
	} else {
		fprintf(stderr, "unknown command %s\n", cmd);
		ret = 1;
	}

	vd55g1_close(&s);
	return ret ? 1 : 0;
}
