/* On-device SiriusXM presence look for the LilyGO T-Display-S3.
 *
 * A short press changes screen. A long press starts the screen in front
 * of you: the data screen saves a one-minute scan, the waterfall screen
 * runs a live view of one dial. This is spectrum presence only: it does
 * not demodulate and it does not touch the cipher.
 *
 * The 2.33 GHz spectrum on this chip is inverted about the dial and the
 * reference reads about 60 kHz low. Scoring undoes that before it looks
 * for a ~1.8 MHz hump. The line on the tune center is the receiver spur.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 * font8x8_basic is public domain (Daniel Hepper / IBM VGA).
 */

#include "handheld.h"

#include <errno.h>
#include <stdlib.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

#include "driver/gpio.h"
#include "driver/sdmmc_host.h"
#include "esp_lcd_io_i80.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_st7789.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_vfs_fat.h"
#include "font8x8_basic.h"
#include "hal/usb_serial_jtag_ll.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "sdmmc_cmd.h"

static const char *TAG = "orcxm";

#define LCD_W 320
#define LCD_H 170
#define SCALE 2
#define ROW_H (8 * SCALE)
#define ROWS 10
#define COLS 20
#define NFFT 1024
#define STORE_BINS 256
#define FS_HZ 16000000.0f
#define FRAMES 12
#define GAIN 70
#define BANDWIDTH_MHZ 20
/* Scoring geometry, see bench/xm_metrics.py. */
#define METRICS_VERSION 2
#define REF_LOW_HZ 60000.0f
#define SPUR_HZ 150000.0f
#define WINDOW_HZ 950000.0f
#define FLOOR_IN_HZ 4000000.0f
#define FLOOR_OUT_HZ 7500000.0f
#define RISE_DB 3.0f
/* Six XM centers share one minute. Wi-Fi is only a short sanity check. */
#define XM_DWELL_MS 10000
#define WIFI_DWELL_MS 1500
#define WF_COLS 160
#define WF_ROWS 76
#define LONG_PRESS_US 650000
#define SHORT_PRESS_US 50000

#define PIN_LCD_BL 38
#define PIN_LCD_D0 39
#define PIN_LCD_D1 40
#define PIN_LCD_D2 41
#define PIN_LCD_D3 42
#define PIN_LCD_D4 45
#define PIN_LCD_D5 46
#define PIN_LCD_D6 47
#define PIN_LCD_D7 48
#define PIN_POWER 15
#define PIN_LCD_RES 5
#define PIN_LCD_CS 6
#define PIN_LCD_DC 7
#define PIN_LCD_WR 8
#define PIN_LCD_RD 9
#define PIN_BTN_BOOT 0
#define PIN_BTN_USER 14
#define PIN_SD_CLK 11
#define PIN_SD_CMD 13
#define PIN_SD_D0 12

#define RGB(r, g, b) \
    ((uint16_t)((((r) & 0xF8) << 8) | (((g) & 0xFC) << 3) | (((b) & 0xF8) >> 3)))
#define C_BG RGB(0, 0, 0)
#define C_FG RGB(255, 255, 255)
#define C_DIM RGB(140, 150, 160)
#define C_OK RGB(80, 220, 120)
#define C_AMB RGB(240, 180, 60)
#define C_BAD RGB(230, 80, 70)

static esp_lcd_panel_handle_t s_panel;
static SemaphoreHandle_t s_flush;
/* One arena. A full-screen paint uses lcd and overlaps the spectra.
 * During a dwell, frames stay put and the countdown is drawn in live.row,
 * which sits after the spectra. Internal RAM ends at the RF ring. */
static union {
    struct {
        uint16_t strip[ROW_H * LCD_W];
        uint16_t footer[10 * LCD_W];
    } lcd;
    struct {
        uint16_t frames[FRAMES][STORE_BINS];
        uint16_t row[ROW_H * LCD_W];
    } live;
    struct {
        uint8_t hist[WF_ROWS][WF_COLS];
        uint16_t strip[2 * LCD_W];
    } fall;
} s_mem __attribute__((aligned(64)));
_Static_assert(NFFT % STORE_BINS == 0, "bins divide the FFT");
_Static_assert(sizeof(s_mem.live) <= sizeof(s_mem.lcd), "countdown row fits beside the spectra");
_Static_assert((FRAMES * STORE_BINS * sizeof(uint16_t)) % 64 == 0, "countdown row is DMA aligned");
_Static_assert((WF_ROWS * WF_COLS) % 64 == 0, "waterfall strip is DMA aligned");
_Static_assert(sizeof(s_mem.fall) <= sizeof(s_mem.lcd), "waterfall fits the arena");
static int8_t s_iq[NFFT * 2];
static float s_power[NFFT];
static bool s_lcd;
static bool s_sd;

static char s_sd_name[16];

static bool IRAM_ATTR flush_done(esp_lcd_panel_io_handle_t io,
                                 esp_lcd_panel_io_event_data_t *edata, void *ctx) {
    (void)io;
    (void)edata;
    BaseType_t woken = pdFALSE;
    xSemaphoreGiveFromISR((SemaphoreHandle_t)ctx, &woken);
    return woken == pdTRUE;
}

static void lcd_init(void) {
    gpio_config_t power = {
        .pin_bit_mask = (1ULL << PIN_POWER) | (1ULL << PIN_LCD_BL) | (1ULL << PIN_LCD_RD),
        .mode = GPIO_MODE_OUTPUT,
    };
    gpio_config(&power);
    gpio_set_level(PIN_POWER, 1);
    gpio_set_level(PIN_LCD_RD, 1);
    gpio_set_level(PIN_LCD_BL, 1);
    vTaskDelay(pdMS_TO_TICKS(20));

    s_flush = xSemaphoreCreateBinary();
    esp_lcd_i80_bus_handle_t bus = NULL;
    esp_lcd_i80_bus_config_t bus_config = {
        .clk_src = LCD_CLK_SRC_DEFAULT,
        .dc_gpio_num = PIN_LCD_DC,
        .wr_gpio_num = PIN_LCD_WR,
        .data_gpio_nums =
            {
                PIN_LCD_D0,
                PIN_LCD_D1,
                PIN_LCD_D2,
                PIN_LCD_D3,
                PIN_LCD_D4,
                PIN_LCD_D5,
                PIN_LCD_D6,
                PIN_LCD_D7,
            },
        .bus_width = 8,
        .max_transfer_bytes = LCD_W * ROW_H * sizeof(uint16_t),
        .dma_burst_size = 64,
    };
    if (esp_lcd_new_i80_bus(&bus_config, &bus) != ESP_OK) {
        ESP_LOGE(TAG, "LCD bus failed");
        return;
    }
    esp_lcd_panel_io_handle_t io = NULL;
    esp_lcd_panel_io_i80_config_t io_config = {
        .cs_gpio_num = PIN_LCD_CS,
        .pclk_hz = 16 * 1000 * 1000,
        .trans_queue_depth = 4,
        .on_color_trans_done = flush_done,
        .user_ctx = s_flush,
        .lcd_cmd_bits = 8,
        .lcd_param_bits = 8,
        .dc_levels =
            {
                .dc_idle_level = 0,
                .dc_cmd_level = 0,
                .dc_dummy_level = 0,
                .dc_data_level = 1,
            },
        .flags.swap_color_bytes = 1,
    };
    if (esp_lcd_new_panel_io_i80(bus, &io_config, &io) != ESP_OK) {
        ESP_LOGE(TAG, "LCD io failed");
        return;
    }
    esp_lcd_panel_dev_config_t panel_config = {
        .reset_gpio_num = PIN_LCD_RES,
        .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB,
        .bits_per_pixel = 16,
    };
    if (esp_lcd_new_panel_st7789(io, &panel_config, &s_panel) != ESP_OK) {
        ESP_LOGE(TAG, "LCD panel failed");
        return;
    }
    ESP_ERROR_CHECK(esp_lcd_panel_reset(s_panel));
    ESP_ERROR_CHECK(esp_lcd_panel_init(s_panel));
    ESP_ERROR_CHECK(esp_lcd_panel_invert_color(s_panel, true));
    /* Landscape, USB on the left, from LilyGO's T-Display-S3 example.
     * The 170-pixel window is centered in the 240-wide GRAM. */
    ESP_ERROR_CHECK(esp_lcd_panel_swap_xy(s_panel, true));
    ESP_ERROR_CHECK(esp_lcd_panel_mirror(s_panel, false, true));
    ESP_ERROR_CHECK(esp_lcd_panel_set_gap(s_panel, 0, 35));
    ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(s_panel, true));
    s_lcd = true;
    ESP_LOGI(TAG, "LCD ready");
}

static void fill_strip(uint16_t *strip, uint16_t color) {
    for (int i = 0; i < ROW_H * LCD_W; i++) strip[i] = color;
}

static void blit_span(int y, int h, const uint16_t *strip) {
    if (!s_lcd || h <= 0) return;
    esp_lcd_panel_draw_bitmap(s_panel, 0, y, LCD_W, y + h, strip);
    xSemaphoreTake(s_flush, pdMS_TO_TICKS(100));
}

static void blit_row(int y, const uint16_t *strip) {
    blit_span(y, ROW_H, strip);
}

static void draw_glyph(uint16_t *strip, int col, char ch, uint16_t color) {
    unsigned c = (unsigned char)ch;
    if (c > 127) c = '?';
    const char *glyph = font8x8_basic[c];
    int origin = col * 8 * SCALE;
    if (origin >= LCD_W) return;
    for (int row = 0; row < 8; row++) {
        uint8_t bits = (uint8_t)glyph[row];
        for (int px = 0; px < 8; px++) {
            if ((bits & (1u << px)) == 0) continue;
            int x0 = origin + px * SCALE;
            int y0 = row * SCALE;
            for (int dy = 0; dy < SCALE; dy++) {
                for (int dx = 0; dx < SCALE; dx++) {
                    int x = x0 + dx;
                    if (x >= 0 && x < LCD_W) strip[(y0 + dy) * LCD_W + x] = color;
                }
            }
        }
    }
}

static void paint_line_on(uint16_t *strip, int row, const char *text, uint16_t color) {
    fill_strip(strip, C_BG);
    char buf[COLS + 1];
    snprintf(buf, sizeof(buf), "%-*.*s", COLS, COLS, text ? text : "");
    for (int i = 0; i < COLS; i++) draw_glyph(strip, i, buf[i], color);
    blit_row(row * ROW_H, strip);
}

static void paint_line(int row, const char *text, uint16_t color) {
    paint_line_on(s_mem.lcd.strip, row, text, color);
}

static void paint_footer(void) {
    if (!s_lcd) return;
    int y = ROWS * ROW_H;
    if (y >= LCD_H) return;
    int h = LCD_H - y;
    for (int i = 0; i < h * LCD_W; i++) s_mem.lcd.footer[i] = C_BG;
    esp_lcd_panel_draw_bitmap(s_panel, 0, y, LCD_W, LCD_H, s_mem.lcd.footer);
    xSemaphoreTake(s_flush, pdMS_TO_TICKS(100));
}

static void screen(const char lines[ROWS][COLS + 1], const uint16_t *colors) {
    for (int i = 0; i < ROWS; i++) paint_line(i, lines[i], colors[i]);
    paint_footer();
}

static void buttons_init(void) {
    gpio_config_t cfg = {
        .pin_bit_mask = (1ULL << PIN_BTN_BOOT) | (1ULL << PIN_BTN_USER),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&cfg);
}

static bool button_down(void) {
    return gpio_get_level(PIN_BTN_BOOT) == 0 || gpio_get_level(PIN_BTN_USER) == 0;
}

static int read_host_byte(void) {
    /* The USB-Serial-JTAG console's non-blocking read never polls the
     * hardware FIFO unless the driver ring is installed. Keys are one
     * byte, so read the FIFO here. */
    uint8_t ch;
    if (usb_serial_jtag_ll_read_rxfifo(&ch, 1) == 0) return -1;
    return (int)ch;
}

static void dump_reports(void) {
    printf("DUMP\n");
    fflush(stdout);
    if (!s_sd) {
        printf("NO SD\n");
        fflush(stdout);
        return;
    }
    int found = 0;
    for (int index = 1; index < 10000; index++) {
        char path[48];
        snprintf(path, sizeof(path), "/sdcard/orcxm/s%04d.txt", index);
        printf("OPEN %s\n", path);
        fflush(stdout);
        FILE *f = fopen(path, "r");
        if (!f) break;
        found++;
        printf("FILE %s\n", path);
        char line[180];
        while (fgets(line, sizeof(line), f)) {
            size_t n = strlen(line);
            while (n > 0 && (line[n - 1] == '\n' || line[n - 1] == '\r')) line[--n] = 0;
            printf("%s\n", line);
        }
        fclose(f);
        printf("ENDFILE\n");
        fflush(stdout);
    }
    printf("ENDDUMP %d\n", found);
    fflush(stdout);
}

enum { GESTURE_NONE = 0, GESTURE_SHORT, GESTURE_LONG };

static int poll_gesture(bool allow_dump) {
    static bool tracking;
    static bool fired_long;
    static int64_t down_us;
    int c = read_host_byte();
    if (c >= 0 && c != '\n' && c != '\r') ESP_LOGI(TAG, "key 0x%02x", c);
    if (c == 'd' || c == 'D') {
        if (allow_dump) dump_reports();
    } else if (c == 's' || c == 'S' || c == 'f' || c == 'F') {
        return c == 'f' || c == 'F' ? GESTURE_SHORT : GESTURE_LONG;
    }
    bool pressed = button_down();
    int64_t now = esp_timer_get_time();
    if (pressed) {
        if (!tracking) {
            tracking = true;
            fired_long = false;
            down_us = now;
        }
        if (!fired_long && now - down_us >= LONG_PRESS_US) {
            fired_long = true;
            return GESTURE_LONG;
        }
        return GESTURE_NONE;
    }
    int gesture = GESTURE_NONE;
    if (tracking && !fired_long && now - down_us >= SHORT_PRESS_US) gesture = GESTURE_SHORT;
    tracking = false;
    fired_long = false;
    return gesture;
}

static void sd_init(void) {
    sdmmc_host_t host = SDMMC_HOST_DEFAULT();
    host.flags = SDMMC_HOST_FLAG_1BIT | SDMMC_HOST_FLAG_DEINIT_ARG;
    host.max_freq_khz = SDMMC_FREQ_DEFAULT;
    sdmmc_slot_config_t slot = SDMMC_SLOT_CONFIG_DEFAULT();
    /* T-Shield is 1-bit on the GPIO matrix. Drop the slot-1 defaults
     * (GPIO14 is the user button, GPIO15 is board power). */
    slot.width = 1;
    slot.clk = PIN_SD_CLK;
    slot.cmd = PIN_SD_CMD;
    slot.d0 = PIN_SD_D0;
    slot.d1 = GPIO_NUM_NC;
    slot.d2 = GPIO_NUM_NC;
    slot.d3 = GPIO_NUM_NC;
    slot.d4 = GPIO_NUM_NC;
    slot.d5 = GPIO_NUM_NC;
    slot.d6 = GPIO_NUM_NC;
    slot.d7 = GPIO_NUM_NC;
    slot.flags |= SDMMC_SLOT_FLAG_INTERNAL_PULLUP;
    esp_vfs_fat_sdmmc_mount_config_t mount = {
        .format_if_mount_failed = false,
        .max_files = 4,
        .allocation_unit_size = 16 * 1024,
    };
    sdmmc_card_t *card = NULL;
    esp_err_t err = esp_vfs_fat_sdmmc_mount("/sdcard", &host, &slot, &mount, &card);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "SD mount failed: %s", esp_err_to_name(err));
        s_sd = false;
        return;
    }
    s_sd = true;
    mkdir("/sdcard/orcxm", 0775);
    ESP_LOGI(TAG, "SD mounted, %llu MB", (unsigned long long)(((uint64_t)card->csd.capacity) *
                                                              card->csd.sector_size / (1024 * 1024)));
}

typedef struct {
    int dial;
    float center_mhz;
    int role; /* 0 wifi, 1 carrier */
    float rms_med;
    float rms_p95;
    float excess_db;
    float width_mhz;
    float threshold_db; /* raised to the floor's side-to-side tilt */
    float tilt_db;
    float spur_db;
    int spur_masks; /* carrier sits inside the +/-150 kHz spur exclusion */
    int kind; /* 0 quiet, 1 rise, 2 narrow, 3 broad, 4 fail */
    int16_t bins[64];
} tune_out_t;

static float median_sorted(float *v, int n) {
    for (int i = 1; i < n; i++) {
        float x = v[i];
        int j = i;
        while (j > 0 && v[j - 1] > x) {
            v[j] = v[j - 1];
            j--;
        }
        v[j] = x;
    }
    return v[n / 2];
}

static void fft_1024(float *re, float *im) {
    const int n = NFFT;
    for (int i = 1, j = 0; i < n; i++) {
        int bit = n >> 1;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j) {
            float tr = re[i];
            re[i] = re[j];
            re[j] = tr;
            float ti = im[i];
            im[i] = im[j];
            im[j] = ti;
        }
    }
    for (int len = 2; len <= n; len <<= 1) {
        float ang = -2.0f * (float)M_PI / (float)len;
        float wlen_r = cosf(ang);
        float wlen_i = sinf(ang);
        for (int i = 0; i < n; i += len) {
            float wr = 1.0f, wi = 0.0f;
            for (int k = 0; k < len / 2; k++) {
                int a = i + k;
                int b = a + len / 2;
                float vr = re[b] * wr - im[b] * wi;
                float vi = re[b] * wi + im[b] * wr;
                re[b] = re[a] - vr;
                im[b] = im[a] - vi;
                re[a] += vr;
                im[a] += vi;
                float nwr = wr * wlen_r - wi * wlen_i;
                wi = wr * wlen_i + wi * wlen_r;
                wr = nwr;
            }
        }
    }
}

static void spectrum(const int8_t *iq, float *power, float *rms, float *clip) {
    static float re[NFFT];
    static float im[NFFT];
    double acc = 0;
    double i_sum = 0, q_sum = 0;
    int clipped = 0;
    for (int i = 0; i < NFFT; i++) {
        float ii = iq[2 * i];
        float qq = iq[2 * i + 1];
        i_sum += ii;
        q_sum += qq;
        if (ii <= -126 || ii >= 126 || qq <= -126 || qq >= 126) clipped++;
    }
    float i_mean = (float)(i_sum / NFFT);
    float q_mean = (float)(q_sum / NFFT);
    double wsum = 0;
    for (int i = 0; i < NFFT; i++) {
        float w = 0.5f - 0.5f * cosf(2.0f * (float)M_PI * (float)i / (float)(NFFT - 1));
        float ii = iq[2 * i] - i_mean;
        float qq = iq[2 * i + 1] - q_mean;
        acc += (double)ii * ii + (double)qq * qq;
        re[i] = ii * w;
        im[i] = qq * w;
        wsum += (double)w * w;
    }
    *rms = sqrtf((float)(acc / NFFT));
    *clip = (float)clipped / (float)NFFT;
    fft_1024(re, im);
    for (int i = 0; i < NFFT / 2; i++) {
        float tr = re[i];
        re[i] = re[i + NFFT / 2];
        re[i + NFFT / 2] = tr;
        float ti = im[i];
        im[i] = im[i + NFFT / 2];
        im[i + NFFT / 2] = ti;
    }
    float norm = (float)wsum;
    if (norm < 1e-6f) norm = 1.0f;
    for (int i = 0; i < NFFT; i++) power[i] = (re[i] * re[i] + im[i] * im[i]) / norm;
}

static float corrected_hz(int dial, int bin) {
    float baseband = ((float)bin - (NFFT / 2.0f)) * (FS_HZ / NFFT);
    return (float)dial * 1e6f - baseband + REF_LOW_HZ;
}

static void smooth_db(const float *power, float *db) {
    const int half = (int)(150000.0f / (FS_HZ / NFFT) / 2.0f);
    for (int i = 0; i < NFFT; i++) {
        int a = i - half;
        int b = i + half;
        if (a < 0) a = 0;
        if (b >= NFFT) b = NFFT - 1;
        double sum = 0;
        for (int k = a; k <= b; k++) sum += power[k];
        db[i] = 10.0f * log10f((float)(sum / (double)(b - a + 1)) + 1e-20f);
    }
}

static void score_carrier(tune_out_t *out, const float *db) {
    /* These are too big for the main task stack. The scan is single-threaded. */
    static float floor_vals[NFFT];
    static float window_vals[NFFT];
    static int hot[NFFT];
    int n_floor = 0, n_lower = 0, n_upper = 0, n_window = 0;
    float center = out->center_mhz * 1e6f;
    /* Where the carrier lands on the raw baseband axis. */
    float carrier_bb = -(out->center_mhz - (float)out->dial) * 1e6f + REF_LOW_HZ;

    out->threshold_db = RISE_DB;
    out->tilt_db = NAN;
    out->spur_db = NAN;
    out->spur_masks = fabsf(carrier_bb) < SPUR_HZ ? 1 : 0;

    for (int i = 0; i < NFFT; i++) {
        float baseband = ((float)i - (NFFT / 2.0f)) * (FS_HZ / NFFT);
        float abs_b = fabsf(baseband);
        float f = corrected_hz(out->dial, i);
        if (abs_b >= FLOOR_IN_HZ && abs_b <= FLOOR_OUT_HZ) {
            floor_vals[n_floor++] = db[i];
            if (baseband < 0.0f) n_lower++;
            else n_upper++;
        }
        if (fabsf(f - center) <= WINDOW_HZ && abs_b >= SPUR_HZ) window_vals[n_window++] = db[i];
    }
    if (n_floor < 8 || n_window < 8) {
        out->kind = 4;
        return;
    }
    float floor_db = median_sorted(floor_vals, n_floor);
    out->excess_db = median_sorted(window_vals, n_window) - floor_db;

    /* How far the two halves of the floor disagree. A rise below that is
     * not evidence of a carrier, so it also raises the gate. */
    if (n_lower >= 8 && n_upper >= 8) {
        int n = 0;
        for (int i = 0; i < NFFT; i++) {
            float baseband = ((float)i - (NFFT / 2.0f)) * (FS_HZ / NFFT);
            float abs_b = fabsf(baseband);
            if (abs_b >= FLOOR_IN_HZ && abs_b <= FLOOR_OUT_HZ && baseband < 0.0f)
                floor_vals[n++] = db[i];
        }
        float lo = median_sorted(floor_vals, n);
        n = 0;
        for (int i = 0; i < NFFT; i++) {
            float baseband = ((float)i - (NFFT / 2.0f)) * (FS_HZ / NFFT);
            float abs_b = fabsf(baseband);
            if (abs_b >= FLOOR_IN_HZ && abs_b <= FLOOR_OUT_HZ && baseband > 0.0f)
                floor_vals[n++] = db[i];
        }
        out->tilt_db = fabsf(median_sorted(floor_vals, n) - lo);
        if (out->tilt_db > out->threshold_db) out->threshold_db = out->tilt_db;
    }

    float spur_peak = -INFINITY;
    for (int i = 0; i < NFFT; i++) {
        float baseband = ((float)i - (NFFT / 2.0f)) * (FS_HZ / NFFT);
        if (fabsf(baseband) < SPUR_HZ && db[i] > spur_peak) spur_peak = db[i];
    }
    if (spur_peak > -INFINITY) out->spur_db = spur_peak - floor_db;

    int n_hot = 0;
    int center_bin = 0;
    float best = 1e30f;
    for (int i = 0; i < NFFT; i++) {
        float f = corrected_hz(out->dial, i);
        float err = fabsf(f - center);
        if (err < best) {
            best = err;
            center_bin = i;
        }
        float baseband = ((float)i - (NFFT / 2.0f)) * (FS_HZ / NFFT);
        if (err <= 2.5e6f && fabsf(baseband) >= SPUR_HZ && db[i] >= floor_db + RISE_DB) hot[n_hot++] = i;
    }
    out->width_mhz = 0;
    if (n_hot > 0) {
        int gap = (int)(400000.0f / (FS_HZ / NFFT));
        if (gap < 1) gap = 1;
        int start = hot[0];
        int prev = hot[0];
        for (int k = 0; k <= n_hot; k++) {
            int bin = k < n_hot ? hot[k] : -1;
            if (k == n_hot || bin - prev > gap) {
                if (start <= center_bin && center_bin <= prev) {
                    out->width_mhz = fabsf(corrected_hz(out->dial, prev) - corrected_hz(out->dial, start)) / 1e6f;
                    break;
                }
                if (k < n_hot) start = bin;
            }
            if (k < n_hot) prev = bin;
        }
    }
    if (out->excess_db < out->threshold_db || out->width_mhz <= 0.0f) out->kind = 0;
    else if (out->width_mhz >= 1.2f && out->width_mhz <= 2.6f) out->kind = 1;
    else if (out->width_mhz < 1.2f) out->kind = 2;
    else out->kind = 3;
}

static const char *kind_word(int kind) {
    switch (kind) {
    case 1: return "RISE";
    case 2: return "narrow";
    case 3: return "broad";
    case 4: return "fail";
    default: return "quiet";
    }
}

static void pack_bins(tune_out_t *out, const float *db) {
    for (int i = 0; i < 64; i++) {
        double sum = 0;
        for (int k = 0; k < NFFT / 64; k++) sum += db[i * (NFFT / 64) + k];
        float v = (float)(sum / (NFFT / 64));
        if (v > 3200) v = 3200;
        if (v < -3200) v = -3200;
        out->bins[i] = (int16_t)(v * 10.0f);
    }
}

static void show_progress(const char *what, int seconds) {
    char lines[ROWS][COLS + 1];
    uint16_t colors[ROWS];
    memset(lines, 0, sizeof(lines));
    for (int i = 0; i < ROWS; i++) colors[i] = C_DIM;
    snprintf(lines[0], COLS + 1, "OrcXM scanning");
    snprintf(lines[2], COLS + 1, "%s", what);
    snprintf(lines[3], COLS + 1, "%ds left", seconds);
    snprintf(lines[5], COLS + 1, "SMA whip");
    snprintf(lines[6], COLS + 1, "gain %d", GAIN);
    colors[0] = C_FG;
    colors[2] = C_AMB;
    screen(lines, colors);
}

static uint16_t quantize_power(float power) {
    float q = power * 1000.0f;
    if (q < 0) q = 0;
    if (q > 65535.0f) q = 65535.0f;
    return (uint16_t)(q + 0.5f);
}

static void show_remain(int dial, int left_s) {
    char line[COLS + 1];
    snprintf(line, sizeof(line), "%d  %ds left", dial, left_s);
    /* This row sits after the stored spectra, so the countdown can update. */
    paint_line_on(s_mem.live.row, 3, line, C_AMB);
}

static bool listen_one(tune_out_t *out) {
    static float db[NFFT];
    float rms[FRAMES];
    int got = 0;
    int dwell_ms = out->role == 1 ? XM_DWELL_MS : WIFI_DWELL_MS;
    int64_t dwell_us = (int64_t)dwell_ms * 1000;
    char what[COLS + 1];
    snprintf(what, sizeof(what), "Listen %d", out->dial);
    /* Full-screen paint overlaps the spectrum store. Do it before captures. */
    show_progress(what, dwell_ms / 1000);
    int64_t start = esp_timer_get_time();
    int last_left = dwell_ms / 1000;
    int group = NFFT / STORE_BINS;
    for (int frame = 0; frame < FRAMES; frame++) {
        int64_t target = start + dwell_us * frame / FRAMES;
        while (esp_timer_get_time() < target) {
            int left = (int)((start + dwell_us - esp_timer_get_time()) / 1000000);
            if (left < 0) left = 0;
            if (left != last_left) {
                show_remain(out->dial, left);
                last_left = left;
            }
            vTaskDelay(pdMS_TO_TICKS(50));
        }
        if (!orcxm_capture((unsigned)out->dial, NFFT, s_iq)) {
            ESP_LOGW(TAG, "capture %d failed", out->dial);
            continue;
        }
        float clip = 0;
        spectrum(s_iq, s_power, &rms[got], &clip);
        (void)clip;
        for (int i = 0; i < STORE_BINS; i++) {
            float sum = 0;
            for (int k = 0; k < group; k++) sum += s_power[i * group + k];
            s_mem.live.frames[got][i] = quantize_power(sum / (float)group);
        }
        got++;
    }
    if (got < 4) {
        out->kind = 4;
        return false;
    }
    float sorted[FRAMES];
    memcpy(sorted, rms, (size_t)got * sizeof(float));
    out->rms_med = median_sorted(sorted, got);
    memcpy(sorted, rms, (size_t)got * sizeof(float));
    median_sorted(sorted, got);
    int p95 = (got * 95) / 100;
    if (p95 >= got) p95 = got - 1;
    out->rms_p95 = sorted[p95];

    static float med_power[NFFT];
    float column[FRAMES];
    int repeat = NFFT / STORE_BINS;
    for (int i = 0; i < STORE_BINS; i++) {
        for (int f = 0; f < got; f++) column[f] = (float)s_mem.live.frames[f][i];
        float level = median_sorted(column, got) / 1000.0f;
        for (int k = 0; k < repeat; k++) med_power[i * repeat + k] = level;
    }
    smooth_db(med_power, db);
    pack_bins(out, db);
    if (out->role == 1) score_carrier(out, db);
    return true;
}

static void format_result_line(char *dst, size_t n, const tune_out_t *t) {
    if (t->kind == 4) {
        snprintf(dst, n, "%d fail", t->dial);
        return;
    }
    if (t->role == 0) return;
    snprintf(dst, n, "%d %+.1f %s", t->dial, t->excess_db, kind_word(t->kind));
}

static char s_saved[ROWS][COLS + 1];
static uint16_t s_saved_color[ROWS];
static bool s_saved_ok;

static void show_results(const tune_out_t *tunes, int n, const tune_out_t *wifi, float burst_db) {
    char lines[ROWS][COLS + 1];
    uint16_t colors[ROWS];
    memset(lines, 0, sizeof(lines));
    for (int i = 0; i < ROWS; i++) colors[i] = C_FG;
    snprintf(lines[0], COLS + 1, "OrcXM %s", s_sd ? "SD ok" : "NO SD");
    colors[0] = s_sd ? C_OK : C_BAD;
    if (burst_db >= 6.0f) {
        snprintf(lines[1], COLS + 1, "WiFi %+.0fdB HEARD", burst_db);
        colors[1] = C_OK;
    } else {
        snprintf(lines[1], COLS + 1, "WiFi quiet");
        colors[1] = C_AMB;
    }
    (void)wifi;
    int row = 2;
    for (int i = 0; i < n && row < 8; i++) {
        if (tunes[i].role != 1) continue;
        format_result_line(lines[row], COLS + 1, &tunes[i]);
        colors[row] = tunes[i].kind == 1 ? C_OK : C_FG;
        row++;
    }
    if (s_sd && s_sd_name[0]) snprintf(lines[8], COLS + 1, "saved %s", s_sd_name);
    else if (!s_sd) snprintf(lines[8], COLS + 1, "not saved");
    snprintf(lines[9], COLS + 1, "tap sw, hold saves");
    colors[8] = C_DIM;
    colors[9] = C_DIM;
    memcpy(s_saved, lines, sizeof(s_saved));
    memcpy(s_saved_color, colors, sizeof(s_saved_color));
    s_saved_ok = true;
    screen(lines, colors);
}

static void save_report(const tune_out_t *tunes, int n, float burst_db) {
    s_sd_name[0] = 0;
    if (!s_sd) return;
    char path[48];
    int index = 1;
    for (; index < 10000; index++) {
        snprintf(path, sizeof(path), "/sdcard/orcxm/s%04d.txt", index);
        struct stat st;
        if (stat(path, &st) != 0) break;
    }
    FILE *f = fopen(path, "w");
    if (!f) {
        ESP_LOGW(TAG, "SD write failed: %s", strerror(errno));
        s_sd = false;
        return;
    }
    fprintf(f, "orcxm handheld\nmetrics %d\ngain %d\nbandwidth %d\nframes %d\nfft %d\nxm_dwell_s %d\n",
            METRICS_VERSION, GAIN, BANDWIDTH_MHZ, FRAMES, NFFT, XM_DWELL_MS / 1000);
    fprintf(f, "wifi_burst_db %.1f\n", burst_db);
    for (int i = 0; i < n; i++) {
        const tune_out_t *t = &tunes[i];
        fprintf(f, "tune %d role %s rms_med %.2f rms_p95 %.2f excess %.2f width %.2f %s",
                t->dial, t->role ? "carrier" : "wifi", t->rms_med, t->rms_p95, t->excess_db,
                t->width_mhz, kind_word(t->kind));
        if (t->role)
            fprintf(f, " gate %.2f tilt %.2f spur %.2f mask %d", t->threshold_db, t->tilt_db,
                    t->spur_db, t->spur_masks);
        fprintf(f, "\n");
        fprintf(f, "bins");
        for (int b = 0; b < 64; b++) fprintf(f, " %d", t->bins[b]);
        fprintf(f, "\n");
    }
    fprintf(f, "note presence only, not demodulated\n");
    fclose(f);
    snprintf(s_sd_name, sizeof(s_sd_name), "s%04d.txt", index);
    ESP_LOGI(TAG, "wrote %s", path);
}

static void run_scan(void) {
    static const struct {
        int dial;
        float center;
        int role;
    } plan[] = {
        /* Each carrier is tuned 2-3.5 MHz off its dial: the spur sits on
         * the dial at +4 to +7 dB and the window drops +/-150 kHz of it,
         * so a carrier on its own dial loses its middle bins. */
        {2437, 0, 0}, {2412, 0, 0}, {2331, 2333.465f, 1}, {2332, 2335.305f, 1},
        {2334, 2337.490f, 1}, {2343, 2340.020f, 1}, {2345, 2342.205f, 1}, {2342, 2344.045f, 1},
    };
    const int n = (int)(sizeof(plan) / sizeof(plan[0]));
    tune_out_t tunes[8];
    memset(tunes, 0, sizeof(tunes));
    for (int i = 0; i < n; i++) {
        tunes[i].dial = plan[i].dial;
        tunes[i].center_mhz = plan[i].center;
        tunes[i].role = plan[i].role;
        listen_one(&tunes[i]);
        if (tunes[i].role == 0) {
            float burst = 0;
            if (tunes[i].rms_med > 0.1f) burst = 20.0f * log10f(tunes[i].rms_p95 / tunes[i].rms_med);
            ESP_LOGI(TAG, "%d rms %.2f p95 %.2f burst %+.1f", tunes[i].dial, tunes[i].rms_med, tunes[i].rms_p95,
                     burst);
        } else {
            ESP_LOGI(TAG, "%d rms %.2f %+.1f dB width %.2f %s", tunes[i].dial, tunes[i].rms_med, tunes[i].excess_db,
                     tunes[i].width_mhz, kind_word(tunes[i].kind));
        }
    }
    float burst_db = -99;
    const tune_out_t *wifi = NULL;
    for (int i = 0; i < n; i++) {
        if (tunes[i].role != 0 || tunes[i].rms_med < 0.1f) continue;
        float db = 20.0f * log10f(tunes[i].rms_p95 / tunes[i].rms_med);
        if (db > burst_db) {
            burst_db = db;
            wifi = &tunes[i];
        }
    }
    save_report(tunes, n, burst_db);
    show_results(tunes, n, wifi, burst_db);
    ESP_LOGI(TAG, "scan done, wifi burst %+.1f dB, sd %s", burst_db, s_sd_name[0] ? s_sd_name : "none");
}

static void show_idle(void) {
    char lines[ROWS][COLS + 1];
    uint16_t colors[ROWS];
    memset(lines, 0, sizeof(lines));
    for (int i = 0; i < ROWS; i++) colors[i] = C_FG;
    snprintf(lines[0], COLS + 1, "OrcXM data");
    snprintf(lines[2], COLS + 1, "tap: waterfall");
    snprintf(lines[3], COLS + 1, "hold: save scan");
    snprintf(lines[4], COLS + 1, "about 1 minute");
    snprintf(lines[5], COLS + 1, s_sd ? "SD card ready" : "NO SD card");
    snprintf(lines[6], COLS + 1, "gain %d", GAIN);
    snprintf(lines[8], COLS + 1, "2.4 GHz SMA");
    colors[2] = C_AMB;
    colors[3] = C_AMB;
    colors[5] = s_sd ? C_OK : C_BAD;
    colors[8] = C_DIM;
    if (s_saved_ok) screen(s_saved, s_saved_color);
    else screen(lines, colors);
}

static const int k_fall_dial[] = {2331, 2332, 2334, 2343, 2345, 2342, 2437};
static int s_fall_i;
static int s_screen;

static void show_fall_idle(void) {
    char lines[ROWS][COLS + 1];
    uint16_t colors[ROWS];
    memset(lines, 0, sizeof(lines));
    for (int i = 0; i < ROWS; i++) colors[i] = C_FG;
    int dial = k_fall_dial[s_fall_i];
    snprintf(lines[0], COLS + 1, "OrcXM waterfall");
    snprintf(lines[2], COLS + 1, "%d MHz", dial);
    snprintf(lines[3], COLS + 1, "tap: data screen");
    snprintf(lines[4], COLS + 1, "hold: run live");
    snprintf(lines[6], COLS + 1, "tap away, back");
    snprintf(lines[7], COLS + 1, "picks next MHz");
    colors[0] = C_OK;
    colors[2] = C_AMB;
    colors[3] = C_DIM;
    colors[4] = C_AMB;
    colors[6] = C_DIM;
    colors[7] = C_DIM;
    screen(lines, colors);
}

static uint16_t heat_color(uint8_t level) {
    if (level == 255) return RGB(50, 50, 60);
    if (level < 64) return RGB(0, 0, level * 3);
    if (level < 128) return RGB(0, (level - 64) * 4, 255);
    if (level < 192) return RGB((level - 128) * 4, 255, 255 - (level - 128) * 4);
    return RGB(255, 255 - (level - 192) * 3, 0);
}

static void paint_fall_row(int y, const uint8_t *cols) {
    uint16_t *strip = s_mem.fall.strip;
    for (int x = 0; x < LCD_W; x++) {
        int col = x * WF_COLS / LCD_W;
        uint16_t color = heat_color(cols[col]);
        strip[x] = color;
        strip[LCD_W + x] = color;
    }
    blit_span(y, 2, strip);
}

static void redraw_waterfall(void) {
    for (int row = 0; row < WF_ROWS; row++) paint_fall_row(ROW_H + row * 2, s_mem.fall.hist[row]);
}

static void push_fall_row(int dial) {
    float column_db[WF_COLS];
    float floor_vals[WF_COLS];
    uint8_t row[WF_COLS];
    int n_floor = 0;
    for (int col = 0; col < WF_COLS; col++) {
        int rev = WF_COLS - 1 - col;
        int b0 = rev * NFFT / WF_COLS;
        int b1 = (rev + 1) * NFFT / WF_COLS;
        if (b1 <= b0) b1 = b0 + 1;
        double sum = 0;
        for (int b = b0; b < b1; b++) sum += s_power[b];
        float power = (float)(sum / (double)(b1 - b0));
        int mid = (b0 + b1) / 2;
        float baseband = ((float)mid - (NFFT / 2.0f)) * (FS_HZ / NFFT);
        column_db[col] = 10.0f * log10f(power + 1e-20f);
        if (fabsf(baseband) < 150000.0f) {
            row[col] = 255;
        } else {
            floor_vals[n_floor++] = column_db[col];
            row[col] = 0;
        }
    }
    float floor_db = 0;
    if (n_floor > 4) {
        float sorted[WF_COLS];
        memcpy(sorted, floor_vals, (size_t)n_floor * sizeof(float));
        floor_db = median_sorted(sorted, n_floor);
    }
    for (int col = 0; col < WF_COLS; col++) {
        if (row[col] == 255) continue;
        float rel = column_db[col] - floor_db;
        int level = (int)((rel + 3.0f) * (254.0f / 18.0f));
        if (level < 0) level = 0;
        if (level > 254) level = 254;
        row[col] = (uint8_t)level;
    }
    (void)dial;
    memmove(s_mem.fall.hist[1], s_mem.fall.hist[0], (WF_ROWS - 1) * WF_COLS);
    memcpy(s_mem.fall.hist[0], row, WF_COLS);
}

static void run_waterfall(int dial) {
    char header[COLS + 1];
    snprintf(header, sizeof(header), "%d hold stops", dial);
    char lines[ROWS][COLS + 1];
    uint16_t colors[ROWS];
    memset(lines, 0, sizeof(lines));
    memset(colors, 0, sizeof(colors));
    snprintf(lines[0], COLS + 1, "%s", header);
    colors[0] = C_AMB;
    screen(lines, colors);
    memset(s_mem.fall.hist, 0, sizeof(s_mem.fall.hist));
    ESP_LOGI(TAG, "fall start %d", dial);
    int frames = 0;
    while (poll_gesture(false) != GESTURE_LONG) {
        if (!orcxm_capture((unsigned)dial, NFFT, s_iq)) {
            ESP_LOGW(TAG, "fall capture %d failed", dial);
            vTaskDelay(pdMS_TO_TICKS(50));
            continue;
        }
        float rms = 0, clip = 0;
        spectrum(s_iq, s_power, &rms, &clip);
        (void)rms;
        (void)clip;
        push_fall_row(dial);
        redraw_waterfall();
        if ((++frames % 8) == 0) ESP_LOGI(TAG, "fall frame %d", frames);
        vTaskDelay(pdMS_TO_TICKS(20));
    }
    ESP_LOGI(TAG, "fall stop %d", dial);
    while (button_down()) vTaskDelay(pdMS_TO_TICKS(20));
}

void orcxm_handheld(void) {
    ESP_LOGI(TAG, "handheld start");
    lcd_init();
    buttons_init();

    char lines[ROWS][COLS + 1];
    uint16_t colors[ROWS];
    memset(lines, 0, sizeof(lines));
    for (int i = 0; i < ROWS; i++) colors[i] = C_FG;
    snprintf(lines[2], COLS + 1, "Starting radio");
    screen(lines, colors);

    sd_init();
    if (!orcxm_radio_start(GAIN, BANDWIDTH_MHZ)) {
        snprintf(lines[2], COLS + 1, "Radio failed");
        colors[2] = C_BAD;
        screen(lines, colors);
        ESP_LOGE(TAG, "radio start failed");
        return;
    }
    ESP_LOGI(TAG, "radio ready, gain max %u", orcxm_gain_max());
    s_screen = 0;
    show_idle();
    ESP_LOGI(TAG, "screen data, tap switches, hold saves");
    for (;;) {
        int gesture = poll_gesture(true);
        if (gesture == GESTURE_SHORT) {
            if (s_screen == 1) s_fall_i = (s_fall_i + 1) % (int)(sizeof(k_fall_dial) / sizeof(k_fall_dial[0]));
            s_screen ^= 1;
            if (s_screen == 0) show_idle();
            else show_fall_idle();
            ESP_LOGI(TAG, "screen %s", s_screen == 0 ? "data" : "waterfall");
        } else if (gesture == GESTURE_LONG) {
            if (s_screen == 0) {
                ESP_LOGI(TAG, "scan start");
                run_scan();
                while (button_down()) vTaskDelay(pdMS_TO_TICKS(20));
                show_idle();
            } else {
                run_waterfall(k_fall_dial[s_fall_i]);
                show_fall_idle();
            }
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}
