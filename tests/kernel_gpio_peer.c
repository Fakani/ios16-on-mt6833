/* Host-only XNU API and GPIO peer: no live device access. */
#include <stdint.h>
#include <assert.h>
#include <string.h>
extern void touch_thread_entry(void *,int);
static uint32_t regs[256];static unsigned frame,bits,miso,scenario,event_count,message_count;
static uint64_t fake_ticks;static unsigned short_delays,time_calls,interval_calls;
uint64_t kernel_time(void){time_calls++;fake_ticks+=13;return fake_ticks;}
void kernel_interval(uint32_t interval,uint32_t scale,uint64_t *ticks){assert(scale==1000&&(interval==1||interval==10));interval_calls++;*ticks=scenario==3?0:(uint64_t)interval*13;}
int kernel_spin_decision(uint64_t ticks){(void)ticks;return 0;}
int kernel_preempt_level(void){return 0;}
int kernel_irq_enabled(void){return 1;}
static uint8_t payload[72];static uint32_t events[16][4];
static int mode(unsigned p){return (regs[(0x300+(p/8)*16)/4]>>((p%8)*4))&7;}
static int output(unsigned p){return (regs[((p/32)*16)/4]>>(p%32))&1;}
static int latch(unsigned p){return (regs[(0x100+(p/32)*16)/4]>>(p%32))&1;}
static int cs(void){return !mode(98)&&output(98)?latch(98):1;}
static int clk(void){return !mode(97)&&output(97)?latch(97):0;}
static void packet(void){
 memset(payload,255,72);payload[0]=0x5b;payload[1]=0;payload[2]=72;payload[3]=0xf9;
 if(frame<2){unsigned x=frame?4319:231,y=frame?9599:321;
 payload[4]=x>>8;payload[5]=x;payload[6]=y>>8;payload[7]=y;payload[8]=10;}
 unsigned sum=0;for(unsigned i=0;i<71;i++)sum+=payload[i];payload[71]=(uint8_t)(0u-sum);
 if(scenario==1&&frame==1)payload[71]^=1;
}
uint64_t kernel_map(uint64_t a,uint64_t n){assert(n==0x1000&&(a==0x10005000u||a==0x11e60000u||a==0x11e20000u));return a;}
void kernel_delay(uint32_t us){assert(us==10||us==1000);if(us==10)short_delays++;fake_ticks+=(uint64_t)us*13;}
int kernel_printf(const char *s,...){assert(!strchr(s,'%'));message_count++;return 0;}
void kernel_post(uint32_t t,uint32_t f,uint32_t x,uint32_t y){assert(event_count<16);events[event_count][0]=t;events[event_count][1]=f;events[event_count][2]=x;events[event_count++][3]=y;}
uint32_t kernel_reg_read(uint64_t a){
 assert(a>=0x10005000u&&a<0x10005400u);unsigned off=a-0x10005000u;
 if(off==0x200)return (miso<<12)|((frame<3&&scenario!=2)?0:1u<<14);
 return regs[off/4];
}
void kernel_reg_write(uint64_t a,uint32_t value){
 if(a==0x11e60094u){assert(value==(1u<<11));return;}
 if(a==0x11e20054u){assert(value==4);return;}
 assert(a>=0x10005000u&&a<0x10005400u);unsigned off=a-0x10005000u;int oldcs=cs(),oldclk=clk();
 if(off>=0x30c&&off%16==12){
  unsigned group=(off-0x30c)/16,at=(0x300+group*16)/4;
  for(unsigned i=0;i<8;i++){unsigned nib=(value>>(i*4))&15;
   if(nib&8){unsigned pin=group*8+i;assert(pin==12||pin==13||pin==14||pin==97||pin==98);
    assert((nib&7)==0);regs[at]&=~(7u<<(i*4));}}
 }else{unsigned alias=off%16,reg=off-alias;assert(alias==4||alias==8);
  if(reg==0){assert(value==(1u<<13)||value==((1u<<12)|(1u<<14)));}
  else if(reg==0x30)assert(value==6);
  else if(reg==0x100)assert(value==(1u<<13));
  else{assert(reg==0x130&&(value==2||value==4));}
  assert(!(reg==0x100&&(value&(1u<<15))));
  if(alias==4)regs[reg/4]|=value;else regs[reg/4]&=~value;
 }
 int newcs=cs(),newclk=clk();
 if(oldcs&&!newcs){bits=0;packet();}
 if(!newcs&&!oldclk&&newclk){unsigned byte=bits/8,bit=7-bits%8;assert(byte<75);
  unsigned out=byte?0:0x83;assert(latch(13)==((out>>bit)&1));
  unsigned in=byte==1?0xa3:(byte>=3?payload[byte-3]:0);miso=(in>>bit)&1;bits++;}
 if(!oldcs&&newcs){assert(bits==600);frame++;}
}
static void run(unsigned which){
 memset(regs,0,sizeof(regs));regs[0x310/4]=0x220007;regs[0x3c0/4]=0x11122221;
 frame=bits=miso=event_count=message_count=0;fake_ticks=short_delays=time_calls=interval_calls=0;scenario=which;touch_thread_entry(0,0);
 assert(frame>=3&&message_count>=3);
#if TOUCH_TIMING_LOG
 assert(interval_calls==2&&time_calls>0);
#if TOUCH_COUNTER_WAIT
 if(scenario!=3)assert(short_delays==0);else assert(short_delays>0);
#endif
#endif
 if(which==1){assert(event_count==2&&events[0][0]==1&&events[1][0]==3);}
 else{assert(event_count==3&&events[0][0]==1&&events[1][0]==2&&events[2][0]==3);
 assert(events[0][2]==3505&&events[0][3]==2191);assert(events[1][2]==65535&&events[1][3]==65535);}
}
int main(void){run(0);run(1);run(2);run(3);return 0;}
