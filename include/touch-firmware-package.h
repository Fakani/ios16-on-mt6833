#ifndef TOUCH_FIRMWARE_PACKAGE_H
#define TOUCH_FIRMWARE_PACKAGE_H
#include <stdint.h>
#define TOUCH_FW_MAGIC 0x57464c49u /* ILFW */
#define TOUCH_FW_BYTES 90624u
#define TOUCH_FW_TIMEOUT_MS 60000u
struct touch_fw_block {uint32_t target,size,offset,crc;};
struct touch_fw_package {
 uint32_t magic,version,count,bytes,expected_pid,timeout_ms,reserved[2];
 struct touch_fw_block block[3];
};
_Static_assert(sizeof(struct touch_fw_package)==80,"firmware package layout");
extern const struct touch_fw_package fw_package;
extern const uint8_t fw_data[];
extern volatile uint32_t bb_pid[3],bb_flags;
extern volatile uint32_t fw_phase,fw_error,fw_verified,fw_bytes_written,fw_bytes_verified;
extern volatile uint32_t fw_crc_read[3],fw_ack,fw_reply,fw_tp_x,fw_tp_y,fw_elapsed_ms;
int touch_gpio_transfer(const uint8_t *tx,uint8_t *rx,unsigned n);
int touch_gpio_wait(unsigned us);
void touch_fw_progress(uint32_t phase,uint32_t block,uint32_t bytes);
int touch_fw_load(void);
#endif
