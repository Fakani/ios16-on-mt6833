/* Host-only MT6833 GPIO banks and command-validating SPI peer. */
#include <stdint.h>
#include <string.h>
#include <assert.h>
#ifndef BB_RW_TEST
#define BB_RW_TEST 0
#endif
extern void touch_gate_diagnostic(void);
extern volatile uint32_t diag_rx,bb_ack,bb_pid[3],bb_flags,bb_frames,bb_clocks;
#if BB_RW_TEST
extern volatile uint32_t bb_rw_before,bb_rw_expected,bb_rw_read,bb_rw_after;
#endif
struct console {uint64_t base;uint32_t pitch,w,h,x,y,top,scale,fg,bg;};
volatile struct console console_state={0,4352,1080,2400,16,96,0,2,0,0};
static uint32_t regs[256],saved[256],ies_register,saved_ies,dummy_word,original_dummy;
static unsigned frames,bits,reply_bit,test_mode,delay_calls,fail_at,timer_failed,expected_frame,cleanup_index,writes;
static uint8_t expected[17][9]={
 {0x82,0},{0x82,0x25,0x62,0x10,0x18},
 {0x82,0x25,0x9c,0,4},{0x83,0,0,0,0},
 {0x82,0x25,0x9c,0,4},{0x83,0,0,0,0},
 {0x82,0x25,0x9c,0,4},{0x83,0,0,0,0},
 {0x82,0x25,0x24,0x10,5},{0x83,0,0,0,0},
 {0x82,0x25,0x24,0x10,5,0,0,0,0},
 {0x82,0x25,0x24,0x10,5},{0x83,0,0,0,0},
 {0x82,0x25,0x24,0x10,5,0,0,0,0},
 {0x82,0x25,0x24,0x10,5},{0x83,0,0,0,0},
 {0x82,0x1b,0x62,0x10,0x18}};
static int gpio(unsigned p){return ((regs[(0x300+(p/8)*0x10)/4]>>((p%8)*4))&7u)==0;}
static int output(unsigned p){return (regs[((p/32)*0x10)/4]>>(p%32))&1u;}
static int latch(unsigned p){return (regs[(0x100+(p/32)*0x10)/4]>>(p%32))&1u;}
static int cs(void){return gpio(98)&&output(98)?latch(98):1;}
static int clk(void){return gpio(97)&&output(97)?latch(97):0;}
static unsigned length(unsigned frame){return frame==0?2:((frame==10||frame==13)?9:5);}
static int valid_identity(void){return test_mode==0||test_mode>=4;}
static uint32_t payload_word(unsigned frame){
 if(frame==3||frame==5||frame==7)return test_mode==1?0x83:0x78071f01;
 if(frame==9||frame==12||frame==15)return dummy_word^((test_mode==4&&frame==12)?1u:0u);
 return 0;
}
static uint8_t response(unsigned frame,unsigned byte){
 if(test_mode==3)return 255;
 if(test_mode==2)return 0;
 if(frame==0)return byte==1?(test_mode==1?0x82:0xa3):0;
 return byte?(payload_word(frame)>>(8*(byte-1)))&255u:0;
}
uint32_t bb_read(uint64_t a){
 if(a==0x11e60090u)return ies_register;
 assert(a>=0x10005000u&&a<0x10005400u);unsigned off=a-0x10005000u;
 if(off==0x200){assert(gpio(12)&&!output(12)&&(ies_register&(1u<<11)));
 return (regs[off/4]&~(1u<<12))|((cs()?1u:reply_bit)<<12);}
 return regs[off/4];
}
void bb_write(uint64_t a,uint32_t v){
 if(a==0x11e60094u||a==0x11e60098u){assert(v==(1u<<11));
 if(a==0x11e60094u)ies_register|=v;else ies_register&=~v;return;}
 assert(a>=0x10005000u&&a<0x10005400u);unsigned off=a-0x10005000u;
 int old_cs=cs(),old_clk=clk();
 if(off==0x310||off==0x3c0){uint32_t mask=off==0x310?0xff0000:0xff0;
 assert(!((regs[off/4]^v)&~mask));regs[off/4]=v;}
 else {unsigned alias=off%16,reg=off-alias;assert(alias==4||alias==8);uint32_t mask;
 if(reg==0)mask=(1u<<12)|(1u<<13);else if(reg==0x30||reg==0x130)mask=6;
 else {assert(reg==0x100);mask=1u<<13;}assert(!(v&~mask));
 if(alias==4)regs[reg/4]|=v;else regs[reg/4]&=~v;}
 int new_cs=cs(),new_clk=clk();
 if(old_cs&&!new_cs){assert(frames<17);bits=0;
  if(timer_failed)expected_frame=cleanup_index++;
  else if(frames==8&&(!BB_RW_TEST||!valid_identity()))expected_frame=16;
  else expected_frame=frames;
  assert(expected_frame<17);
 }
 if(!new_cs&&!old_clk&&new_clk){assert(gpio(13)&&output(13));
 unsigned byte=bits/8,bit=7-bits%8;assert(byte<length(expected_frame));
 assert(latch(13)==((expected[expected_frame][byte]>>bit)&1u));
 reply_bit=(response(expected_frame,byte)>>bit)&1u;bits++;}
 if(!old_cs&&new_cs){
  if(!timer_failed)assert(bits==length(expected_frame)*8);
  if((expected_frame==10||expected_frame==13)&&bits==72){
   writes++;if(!(test_mode==5&&expected_frame==13)){dummy_word=0;
    for(unsigned i=0;i<4;i++)dummy_word|=(uint32_t)expected[expected_frame][5+i]<<(8*i);}}
  frames++;
 }
}
int bb_delay(unsigned us){assert(us==10||us==1000);delay_calls++;
 if(fail_at&&delay_calls==fail_at){timer_failed=1;cleanup_index=(expected_frame>=10&&expected_frame<16)?13:16;return 0;}return 1;}
void original_probe(void){assert(console_state.scale==2);diag_rx=0x8200;}
void output_char(uint32_t c){(void)c;assert(console_state.scale==4);}
void output_hex(uint64_t v){(void)v;assert(console_state.scale==4);}
static void run(unsigned mode,unsigned fail,unsigned ies_on){
 memset(regs,0,sizeof(regs));regs[0]=0x7654abcd;regs[0x30/4]=0x12e44930;
 regs[0x100/4]=0xabcdef01;regs[0x130/4]=0x55443320;
 regs[0x310/4]=0x220007;regs[0x3c0/4]=0x11122221;memcpy(saved,regs,sizeof(regs));
 ies_register=saved_ies=(0x24681357u&~(1u<<11))|(ies_on?1u<<11:0);
 dummy_word=original_dummy=mode==6?0xa55a5aa5u:0x12345678u;
 uint32_t pattern=original_dummy==0xa55a5aa5u?0x5aa5a55au:0xa55a5aa5u;
 for(unsigned i=0;i<4;i++){expected[10][5+i]=(uint8_t)(pattern>>(8*i));expected[13][5+i]=(uint8_t)(original_dummy>>(8*i));}
 frames=bits=reply_bit=delay_calls=timer_failed=cleanup_index=writes=0;test_mode=mode;fail_at=fail;
 touch_gate_diagnostic();assert(!memcmp(saved,regs,sizeof(regs))&&ies_register==saved_ies);
 assert(console_state.scale==2&&console_state.x==16&&console_state.y==96);assert(bb_flags&0x200u);
 if(fail){assert(!(bb_flags&0x800u));
 if(fail<=34)assert(bb_ack==0xffffffffu);else assert(bb_ack==0xa300);
 if(fail==115||fail==200)assert(bb_flags&0x40u);
 if(fail==910){assert(dummy_word==original_dummy);assert(bb_flags&0x1000u);}
 return;}
 if(BB_RW_TEST&&valid_identity()){
  assert(frames==17&&bb_frames==17&&bb_clocks==720&&writes==2);
#if BB_RW_TEST
  assert(bb_rw_before==original_dummy&&bb_rw_expected==pattern);
  if(mode==4)assert(!(bb_flags&0x800u));else assert(bb_flags&0x800u);
  if(mode==5){assert(!(bb_flags&0x1000u));assert(dummy_word==pattern);}
  else {assert(bb_flags&0x1000u);assert(dummy_word==original_dummy);assert(bb_rw_after==original_dummy);}
#endif
 }else{assert(frames==9&&bb_frames==9&&bb_clocks==336&&writes==0);
  assert(dummy_word==original_dummy);if(mode==0)assert(bb_flags==0x77fu);}
 if(valid_identity())assert(bb_pid[0]==0x78071f01u);else assert(!(bb_flags&0x500u));
 if(mode==1)assert(bb_pid[0]==0x83&&bb_ack==0x8200);
 if(mode==2)assert(bb_pid[0]==0&&bb_ack==0);
 if(mode==3)assert(bb_pid[0]==0xffffffffu&&bb_ack==0xffffu);
}
int main(void){for(unsigned ies=0;ies<2;ies++){for(unsigned mode=0;mode<(BB_RW_TEST?7u:4u);mode++)run(mode,0,ies);
 run(0,1,ies);run(0,3,ies);run(0,115,ies);run(0,200,ies);if(BB_RW_TEST)run(0,910,ies);}return 0;}
