/* Host-only IRAM/SPI peer. Never runs on the phone. */
#include <stdint.h>
#include <assert.h>
#include <string.h>
#include "touch-firmware-package.h"
#include "firmware_fixture.h"
volatile uint32_t bb_pid[3]={0x78071f05u,0x78071f05u,0x78071f05u},bb_flags=0x393f;
static uint8_t iram[0x30000];
static uint64_t micros;
static unsigned mode,calls,reset_count,close_count,ice_on,query_state;
static uint32_t address;
uint64_t fw_now_ms(void){return micros/1000;}
int touch_gpio_wait(unsigned us){assert(us==1000);micros+=us;return 1;}
void touch_fw_progress(uint32_t phase,uint32_t block,uint32_t bytes){assert(phase<=7&&block<=3&&bytes<=90624);}
static int valid_extent(uint32_t a,unsigned n){
 for(unsigned i=0;i<3;i++){const struct touch_fw_block *b=&fw_package.block[i];
  if(a>=b->target&&a+n<=b->target+b->size)return 1;}return 0;
}
int touch_gpio_transfer(const uint8_t *tx,uint8_t *rx,unsigned n){
 assert(n>0&&n<=133);calls++;micros+=mode==2?2000000u:n*160u+1000u;
 if(mode==6&&calls==3)return 0;
 if(ice_on&&tx[0]==0x82&&tx[1]==0x25){
  uint32_t a=(uint32_t)tx[2]|((uint32_t)tx[3]<<8)|((uint32_t)tx[4]<<16);
  if(n==5){assert(valid_extent(a,1));address=a;return 1;}
  if(a==0x40040){assert(n==6&&tx[5]==0xae&&fw_verified==7&&fw_bytes_written==90624&&fw_bytes_verified==90624);reset_count++;return 1;}
  assert(valid_extent(a,n-5));memcpy(iram+a,tx+5,n-5);return 1;
 }
 if(ice_on&&tx[0]==0x83){
  assert(rx&&valid_extent(address,n-1));rx[0]=0;
  memcpy(rx+1,iram+address,n-1);if(mode==1&&address==0)rx[8]^=1;return 1;
 }
 if(tx[0]==0x82&&tx[1]==0x1b){
  const uint8_t close[]={0x82,0x1b,0x62,0x10,0x18};
  assert(n==5&&!memcmp(tx,close,5)&&reset_count==1&&fw_verified==7);ice_on=0;close_count++;return 1;
 }
 assert(!ice_on&&reset_count==1&&close_count==1);
 if(tx[0]==0x82&&n==5){const uint8_t pre[]={0x82,0,2,0xf6,0x20};assert(!memcmp(tx,pre,5));query_state=1;return 1;}
 if(tx[0]==0x82&&n==4){const uint8_t cmd[]={0x82,0,1,0x20};assert(query_state==1&&!memcmp(tx,cmd,4));query_state=2;return 1;}
 assert(tx[0]==0x83&&n==17&&rx&&query_state==2);memset(rx,0,n);
 rx[1]=mode==3?0x82:0xa3;rx[3]=0x20;rx[6]=0x38;rx[7]=4;rx[8]=0x60;rx[9]=9;return 1;
}
static void run(unsigned which){
 mode=which;calls=reset_count=close_count=query_state=0;ice_on=1;micros=0;address=0;
 memset(iram,0xff,sizeof(iram));for(unsigned i=0;i<3;i++)bb_pid[i]=0x78071f05;bb_flags=0x393f;
 if(mode==4)bb_pid[1]^=1;if(mode==5)bb_flags&=~0x1000u;
 int ok=touch_fw_load();
 if(mode==0){
  assert(ok==1&&fw_phase==7&&fw_error==0&&fw_verified==7);
  assert(fw_bytes_written==90624&&fw_bytes_verified==90624&&reset_count==1&&close_count==1);
  assert(fw_ack==0xa3&&fw_reply==0x20&&fw_tp_x==1080&&fw_tp_y==2400&&fw_elapsed_ms<60000);
  for(unsigned i=0;i<3;i++){const struct touch_fw_block *b=&fw_package.block[i];
   assert(!memcmp(iram+b->target,fw_data+b->offset,b->size));assert(fw_crc_read[i]==b->crc);}
 }else if(mode==1){assert(!ok&&fw_error==5&&reset_count==0&&close_count==0&&ice_on);}
 else if(mode==2){assert(!ok&&fw_error==6&&reset_count==0&&close_count==0&&ice_on);}
 else if(mode==3){assert(!ok&&fw_error==7&&fw_verified==7&&reset_count==1&&close_count==1);}
 else if(mode==4||mode==5){assert(!ok&&fw_error==2&&calls==0&&reset_count==0&&close_count==0);}
 else if(mode==6){assert(!ok&&fw_error==4&&reset_count==0&&close_count==0&&ice_on);}
}
int main(void){for(unsigned i=0;i<7;i++)run(i);return 0;}
