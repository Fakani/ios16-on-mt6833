/* Host-only report stream and IRQ pin restoration model. */
#include <stdint.h>
#include <assert.h>
#include <string.h>
#include "touch-report-capture.h"
static uint32_t mode_reg,dir_reg,ies_reg,saved_mode,saved_dir,saved_ies;
static uint64_t micros;static unsigned mode,calls,prompts;
uint64_t rp_now_ms(void){return micros/1000;}
uint32_t rp_read(uint64_t a){
 if(a==0x10005310u)return mode_reg;if(a==0x10005000u)return dir_reg;if(a==0x11e20050u)return ies_reg;
 assert(a==0x10005200u);return (mode==5||micros<300000||micros>14000000)?1u<<14:0;
}
void rp_write(uint64_t a,uint32_t v){
 if(a==0x10005310u){assert(!((mode_reg^v)&~(0xfu<<24)));mode_reg=v;}
 else if(a==0x10005004u||a==0x10005008u){assert(v==(1u<<14));if(a==0x10005004u)dir_reg|=v;else dir_reg&=~v;}
 else{assert((a==0x11e20054u||a==0x11e20058u)&&v==4);if(a==0x11e20054u)ies_reg|=v;else ies_reg&=~v;}
}
int touch_gpio_wait(unsigned us){assert(us==1000);micros+=us;return mode!=3;}
void touch_report_prompt(void){assert(!(mode_reg&(0xfu<<24))&&!(dir_reg&(1u<<14))&&(ies_reg&4));prompts++;}
int touch_gpio_transfer(const uint8_t *tx,uint8_t *rx,unsigned n){
 assert(n==75&&tx[0]==0x83);for(unsigned i=1;i<n;i++)assert(tx[i]==0);calls++;micros+=13000;
 if(mode==4&&calls==3)return 0;
 memset(rx,0,n);rx[1]=mode==7?0x82:0xa3;uint8_t *p=rx+3;
 if(mode==2){p[0]=0x20;return 1;}
 if(mode==0){
  memset(p,255,72);p[0]=0x5a;unsigned x=calls*17%2048,y=calls*23%2048;
  p[1]=(uint8_t)(((x>>8)<<4)|(y>>8));p[2]=(uint8_t)x;p[3]=(uint8_t)y;p[4]=10;p[41]=0;
  unsigned sum=0;for(unsigned i=0;i<42;i++)sum+=p[i];p[42]=(uint8_t)(0u-sum);
 }else{
  memset(p,255,72);p[0]=mode==6?0x77:0x5b;p[1]=0;p[2]=0x48;p[3]=1;
  unsigned x=calls*31%8192,y=calls*37%9600;
  p[4]=x>>8;p[5]=x;p[6]=y>>8;p[7]=y;p[8]=10;
  for(unsigned i=54;i<71;i++)p[i]=0;unsigned sum=0;for(unsigned i=0;i<71;i++)sum+=p[i];p[71]=(uint8_t)(0u-sum);
 }return 1;
}
static void run(unsigned which){
 mode=which;mode_reg=saved_mode=0x33220007;dir_reg=saved_dir=0x12345678|(1u<<14);ies_reg=saved_ies=0x87654321&~4u;
 micros=calls=prompts=0;touch_report_capture();
 assert(mode_reg==saved_mode&&dir_reg==saved_dir&&ies_reg==saved_ies&&prompts==1&&(rp_status&32));
 if(mode==3||mode==2||mode==7||mode==6){assert(rp_count==0);return;}
 if(mode==4){assert(rp_count==2&&calls==3);return;}
 assert(rp_count==3&&rp_reads>3&&(rp_status&64));
 if(mode==0){assert((rp_masks[0]&3)==3&&(rp_masks[2]&3)==3&&rp_max12);}
 else if(mode==6){assert(!(rp_masks[0]&1));}
 else{assert((rp_masks[0]&5)==5&&(rp_masks[2]&5)==5&&rp_max16);}
 if(mode==5)assert(!(rp_status&16));
}
int main(void){for(unsigned i=0;i<8;i++)run(i);return 0;}
