#pragma once

#include <stdbool.h>
#include <stdint.h>

/* Implemented in ESP-SDR's receiver.c (radio_hooks.inc). */
bool orcxm_radio_start(unsigned gain, unsigned bandwidth_mhz);
bool orcxm_capture(unsigned mhz, unsigned n, int8_t *iq);
unsigned orcxm_gain_max(void);

/* Screen, buttons, SD card, and the scan loop. */
void orcxm_handheld(void);
