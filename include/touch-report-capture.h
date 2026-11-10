#ifndef TOUCH_REPORT_CAPTURE_H
#define TOUCH_REPORT_CAPTURE_H
#include <stdint.h>
extern volatile uint32_t rp_count,rp_reads,rp_status,rp_last_ack,rp_last_header,rp_irq_before,rp_irq_after;
extern volatile uint32_t rp_masks[3],rp_max12,rp_max16,rp_valid43,rp_valid72,rp_bad;
extern volatile uint8_t rp_packets[3][72];
void touch_report_prompt(void);
void touch_report_capture(void);
#endif
