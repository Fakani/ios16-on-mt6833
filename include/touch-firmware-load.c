/* Strict device-specific IRAM load. No flash, DMA, or watchdog writes.
 * Every byte is read back; code starts only after all three blocks verify.
 */
#include "touch-firmware-package.h"

volatile uint32_t fw_phase=0,fw_error=0,fw_verified=0,fw_bytes_written=0,fw_bytes_verified=0;
volatile uint32_t fw_crc_read[3]={0xffffffffu,0xffffffffu,0xffffffffu};
volatile uint32_t fw_ack=0xffffffffu,fw_reply=0xffffffffu,fw_tp_x=0,fw_tp_y=0,fw_elapsed_ms=0;
static uint64_t started;
#ifdef TOUCH_DIAG_HOST
extern uint64_t fw_now_ms(void);
#else
static uint64_t fw_now_ms(void)
{
 uint64_t ticks,frequency;
 __asm__ volatile("isb; mrs %0,cntpct_el0":"=r"(ticks));
 __asm__ volatile("mrs %0,cntfrq_el0":"=r"(frequency));
 return ticks*1000u/(frequency?frequency:13000000u);
}
#endif
static const struct touch_fw_block expected[3]={
 {0,81920,0,0xbb7b8d39u},{0x20870,8192,81920,0x061ef7efu},{0x20670,512,90112,0x7532981cu}};
static uint32_t crc_byte(uint32_t crc,uint8_t byte)
{
 crc^=(uint32_t)byte<<24;
 for(unsigned bit=0;bit<8;bit++)crc=(crc<<1)^((crc&0x80000000u)?0x04c11db7u:0);
 return crc;
}
static uint32_t crc_data(const uint8_t *data,uint32_t n)
{uint32_t crc=0xffffffffu;for(uint32_t i=0;i<n;i++)crc=crc_byte(crc,data[i]);return crc;}
static int failed(uint32_t error)
{fw_error=error;fw_elapsed_ms=(uint32_t)(fw_now_ms()-started);return 0;}
static int within_time(void)
{fw_elapsed_ms=(uint32_t)(fw_now_ms()-started);return fw_elapsed_ms<TOUCH_FW_TIMEOUT_MS;}
static int send(const uint8_t *tx,uint8_t *rx,unsigned n)
{
 if(!within_time())return failed(6);
 if(!touch_gpio_transfer(tx,rx,n))return failed(4);
 return 1;
}
static int pause_ms(unsigned ms)
{for(unsigned i=0;i<ms;i++){if(!within_time())return failed(6);if(!touch_gpio_wait(1000))return failed(4);}return 1;}
static int write_memory(uint32_t address,const uint8_t *data,unsigned n)
{
 uint8_t tx[133];
 if(!n||n>128)return failed(1);
 tx[0]=0x82;tx[1]=0x25;tx[2]=(uint8_t)address;tx[3]=(uint8_t)(address>>8);tx[4]=(uint8_t)(address>>16);
 for(unsigned i=0;i<n;i++)tx[5+i]=data[i];
 return send(tx,0,n+5);
}
static int read_memory(uint32_t address,uint8_t *rx,unsigned n)
{
 uint8_t tx[129];
 if(!n||n>128)return failed(1);
 tx[0]=0x82;tx[1]=0x25;tx[2]=(uint8_t)address;tx[3]=(uint8_t)(address>>8);tx[4]=(uint8_t)(address>>16);
 if(!send(tx,0,5))return 0;
 tx[0]=0x83;for(unsigned i=1;i<=n;i++)tx[i]=0;
 return send(tx,rx,n+1);
}
static int metadata_valid(void)
{
 if(fw_package.magic!=TOUCH_FW_MAGIC||fw_package.version!=1||fw_package.count!=3||
    fw_package.bytes!=TOUCH_FW_BYTES||fw_package.expected_pid!=0x78071f05u||
    fw_package.timeout_ms!=TOUCH_FW_TIMEOUT_MS||fw_package.reserved[0]||fw_package.reserved[1])return 0;
 for(unsigned i=0;i<3;i++){
  const struct touch_fw_block *b=&fw_package.block[i],*e=&expected[i];
  if(b->target!=e->target||b->size!=e->size||b->offset!=e->offset||b->crc!=e->crc)return 0;
 }
 return 1;
}
static int application_files_valid(void)
{
 for(unsigned i=0;i<3;i++){
  const struct touch_fw_block *b=&fw_package.block[i];const uint8_t *p=fw_data+b->offset;
  uint32_t crc=crc_data(p,b->size-4);
  uint32_t tail=(uint32_t)p[b->size-4]<<24|(uint32_t)p[b->size-3]<<16|
                (uint32_t)p[b->size-2]<<8|p[b->size-1];
  if(crc!=b->crc||tail!=b->crc)return 0;
 }
 return 1;
}
int touch_fw_load(void)
{
 started=fw_now_ms();fw_phase=1;fw_error=fw_verified=fw_bytes_written=fw_bytes_verified=fw_elapsed_ms=0;
 fw_ack=fw_reply=0xffffffffu;fw_tp_x=fw_tp_y=0;
 for(unsigned i=0;i<3;i++)fw_crc_read[i]=0xffffffffu;
 if(!metadata_valid())return failed(1);
 if((bb_flags&0x3900u)!=0x3900u||bb_pid[0]!=0x78071f05u||
    bb_pid[1]!=bb_pid[0]||bb_pid[2]!=bb_pid[0])return failed(2);
 fw_phase=2;touch_fw_progress(fw_phase,0,0);
 if(!application_files_valid())return failed(3);
 for(unsigned block=0;block<3;block++){
  const struct touch_fw_block *b=&fw_package.block[block];const uint8_t *data=fw_data+b->offset;
  fw_phase=3;touch_fw_progress(fw_phase,block+1,0);
  for(uint32_t off=0;off<b->size;off+=128){
   unsigned n=b->size-off<128?b->size-off:128;
   if(!write_memory(b->target+off,data+off,n))return 0;
   fw_bytes_written+=n;
   if(((off+n)&8191u)==0)touch_fw_progress(fw_phase,block+1,off+n);
  }
  fw_phase=4;touch_fw_progress(fw_phase,block+1,0);
  uint32_t crc=0xffffffffu;uint8_t rx[129];
  for(uint32_t off=0;off<b->size;off+=128){
   unsigned n=b->size-off<128?b->size-off:128;
   if(!read_memory(b->target+off,rx,n))return 0;
   for(unsigned j=0;j<n;j++){
    if(rx[j+1]!=data[off+j])return failed(5);
    if(off+j<b->size-4)crc=crc_byte(crc,rx[j+1]);
   }
   fw_bytes_verified+=n;
   if(((off+n)&8191u)==0)touch_fw_progress(fw_phase,block+1,off+n);
  }
  fw_crc_read[block]=crc;if(crc!=b->crc)return failed(5);
  fw_verified|=1u<<block;
 }
 if(fw_verified!=7||fw_bytes_written!=TOUCH_FW_BYTES||fw_bytes_verified!=TOUCH_FW_BYTES)return failed(5);
 fw_phase=5;touch_fw_progress(fw_phase,0,fw_bytes_verified);
 const uint8_t reset[]={0xae},close[]={0x82,0x1b,0x62,0x10,0x18};
 if(!write_memory(0x40040,reset,1)||!send(close,0,5)||!pause_ms(100))return 0;
 fw_phase=6;
 for(unsigned attempt=0;attempt<3;attempt++){
  const uint8_t pre[]={0x82,0,2,0xf6,0x20},cmd[]={0x82,0,1,0x20};
  uint8_t tx[17]={0x83},rx[17]={0};
  if(!send(pre,0,5)||!send(cmd,0,4)||!send(tx,rx,17))return 0;
  fw_ack=rx[1];fw_reply=rx[3];
  fw_tp_x=(uint32_t)rx[6]|((uint32_t)rx[7]<<8);fw_tp_y=(uint32_t)rx[8]|((uint32_t)rx[9]<<8);
  if(fw_ack==0xa3&&fw_reply==0x20&&fw_tp_x&&fw_tp_y){fw_phase=7;fw_elapsed_ms=(uint32_t)(fw_now_ms()-started);return 1;}
  if(!pause_ms(20))return 0;
 }
 return failed(7);
}
