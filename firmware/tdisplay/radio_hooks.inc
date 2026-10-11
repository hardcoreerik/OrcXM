/* Included at the bottom of ESP-SDR receiver.c so these functions share
 * that file's static tuner state. Do not compile this file on its own.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

bool orcxm_radio_start(unsigned gain, unsigned bandwidth_mhz) {
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    if (err != ESP_OK) return false;
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_NULL));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));
    ESP_ERROR_CHECK(esp_wifi_set_channel(1, WIFI_SECOND_CHAN_NONE));
    if (bandwidth_mhz == 0 ||
        (bandwidth_mhz >= RX_BANDWIDTH_MIN && bandwidth_mhz <= RX_BANDWIDTH_MAX)) {
        rx_filter = (int)rx_bandwidth_dcap(bandwidth_mhz);
    }
    frequency_mhz = 2412;
    rx_ready = false;
    prepare_rx();
    gain_mode = GAIN_MANUAL;
    gain_code = gain;
    gain_reconfigure();
    return true;
}

unsigned orcxm_gain_max(void) { return gain_max(); }

bool orcxm_capture(unsigned mhz, unsigned n, int8_t *iq) {
    if (!iq || n < 256 || n > IQ_WORDS) return false;
    if (frequency_mhz != mhz) {
        frequency_mhz = mhz;
        rx_ready = false;
    }
    prepare_rx();
    for (unsigned j = 0; j < n; j++) IQ_BUFFER[j] = 0xa5a0055au;
    rx_filter_apply();
    uint32_t owner = REG_READ(SRAM_OWNER_REG);
    int64_t start = esp_timer_get_time();
    REG_WRITE(0x60033d5c, 0);
    REG_WRITE(0x60033d90,
              rx_pack | ((rx_pack + 1) << 6) | ((rx_pack + 2) << 12) |
                  ((rx_pack + 3) << 18) | (rx_agc << 24));
    REG_WRITE(SRAM_OWNER_REG, (owner & ~15u) | 4u);
    /* Divider 6: the 16 MS/s hardware path. */
    uint32_t ctrl = 0x80000000u | (1u << 16) | (rx_wide << 17) | (rx_flag << 16) |
                    (rx_source << 20) | (rx_mode << 28) | n;
    REG_WRITE(0x60033d5c, ctrl);
    REG_WRITE(0x60033d5c, ctrl | (1u << 19));
    REG_WRITE(0x60033d5c, ctrl);
    while (!(REG_READ(0x60033d5c) & (1u << 18)) && esp_timer_get_time() - start < 20000) {
    }
    bool done = (REG_READ(0x60033d5c) & (1u << 18)) != 0;
    REG_WRITE(0x60033d5c, 0);
    REG_WRITE(SRAM_OWNER_REG, owner);
    rx_filter_restore();
    if (!done) return false;
    for (unsigned j = 0; j < n; j++) {
        if (IQ_BUFFER[j] == 0xa5a0055au) return false;
        uint32_t w = IQ_BUFFER[j];
        iq[2 * j] = (int8_t)((w >> 2) & 255);
        iq[2 * j + 1] = (int8_t)((w >> 12) & 255);
    }
    return true;
}
