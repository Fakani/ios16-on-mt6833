/* Host-only bit-level check for 129/133-byte GPIO frames. */
#include <stdint.h>
#include <assert.h>
#include "touch-firmware-package.h"
extern volatile uint32_t bb_frames,bb_clocks;
struct console{uint64_t base;uint32_t pitch,w,h,x,y,top,scale,fg,bg;};
volatile struct console console_state;
volatile uint32_t fw_phase,fw_error,fw_verified,fw_bytes_written,fw_bytes_verified,fw_crc_read[3],fw_ack,fw_reply,fw_tp_x,fw_tp_y,fw_elapsed_ms;
static uint32_t out0,out3=4;static unsigned steps,mi,wanted;static uint8_t txdata[133];
int touch_fw_load(void){return 0;}
void original_probe(void){}
void output_char(uint32_t c){(void)c;}
void output_hex(uint64_t v){(void)v;}
int bb_delay(unsigned us){assert(us==10||us==1000);return 1;}
uint32_t bb_read(uint64_t a){assert(a==0x10005200u);return mi<<12;}
void bb_write(uint64_t a,uint32_t v){
 unsigned cs=out3&4,clk=out3&2;
 if(a==0x10005104u){assert(v==(1u<<13));out0|=v;}
 else if(a==0x10005108u){assert(v==(1u<<13));out0&=~v;}
 else if(a==0x10005134u){assert(v==2||v==4);out3|=v;}
 else {assert(a==0x10005138u&&(v==2||v==4));out3&=~v;}
 if(cs&&!(out3&4))steps=0;
 if(!(out3&4)&&!clk&&(out3&2)){unsigned byte=steps/8,bit=7-steps%8;
  assert(byte<wanted);assert(((out0>>13)&1u)==((txdata[byte]>>bit)&1u));
  mi=((byte^0xa5u)>>bit)&1u;steps++;}
 if(!cs&&(out3&4))assert(steps==wanted*8);
}
int main(void){
 for(unsigned i=0;i<133;i++)txdata[i]=(uint8_t)(i^0x5a);
 uint8_t storage[135];storage[0]=storage[134]=0xcc;wanted=133;
 assert(touch_gpio_transfer(txdata,storage+1,133));
 for(unsigned i=0;i<133;i++)assert(storage[i+1]==(uint8_t)(i^0xa5));
 assert(storage[0]==0xcc&&storage[134]==0xcc&&bb_frames==1);
 assert(!touch_gpio_transfer(txdata,storage+1,134)&&!touch_gpio_transfer(txdata,storage+1,0));
 wanted=129;assert(touch_gpio_transfer(txdata,storage+1,129));
 assert(bb_frames==2&&bb_clocks==(133+129)*8&&out3==4);return 0;
}
