/* Read-only 15-second capture after verified firmware startup.
 * Preserve IRQ14 direction/mux/IES; no report format is assumed correct yet. */
#include "touch-firmware-package.h"
#include "touch-report-capture.h"
volatile uint32_t rp_count=0,rp_reads=0,rp_status=0,rp_last_ack=0xff,rp_last_header=0xff,rp_irq_before=0,rp_irq_after=0;
volatile uint32_t rp_masks[3]={0,0,0},rp_max12=0,rp_max16=0,rp_valid43=0,rp_valid72=0,rp_bad=0;
volatile uint8_t rp_packets[3][72];
#ifdef TOUCH_DIAG_HOST
extern uint32_t rp_read(uint64_t address);
extern void rp_write(uint64_t address,uint32_t value);
extern uint64_t rp_now_ms(void);
#define barrier() ((void)0)
#else
static uint32_t rp_read(uint64_t a){return *(volatile uint32_t *)a;}
static void rp_write(uint64_t a,uint32_t v){*(volatile uint32_t *)a=v;}
#define barrier() __asm__ volatile("dsb sy"::: "memory")
static uint64_t rp_now_ms(void){uint64_t t,f;__asm__ volatile("isb;mrs %0,cntpct_el0":"=r"(t));__asm__ volatile("mrs %0,cntfrq_el0":"=r"(f));return t*1000/(f?f:13000000u);}
#endif
#define GPIO 0x10005000u
#define IRQ (1u<<14)
#define MODE (0xfu<<24)
#define IES 0x11e20050u
static uint32_t checks(const uint8_t *p)
{
 uint32_t s43=0,s72=0,mask=(p[0]==0x5a||p[0]==0x5b)?1u:0u;
 for(unsigned i=0;i<72;i++){s72+=p[i];if(i<43)s43+=p[i];}
 if(!(s43&255u))mask|=2;if(!(s72&255u))mask|=4;
 if(((s43-p[42])&255u)==p[42])mask|=8;
 if(((s72-p[71])&255u)==p[71])mask|=16;
 return mask;
}
static void maxima(const uint8_t *p,uint32_t mask)
{
 if((mask&3u)==3u&&!(p[1]==255&&p[2]==255&&p[3]==255)){
  uint32_t x=((p[1]&0xf0u)<<4)|p[2],y=((p[1]&15u)<<8)|p[3];
  uint32_t oldx=rp_max12>>16,oldy=rp_max12&65535u;
  rp_max12=((x>oldx?x:oldx)<<16)|(y>oldy?y:oldy);
 }
 if((mask&5u)==5u&&!(p[4]==255&&p[5]==255&&p[6]==255&&p[7]==255)){
  uint32_t x=(uint32_t)p[4]<<8|p[5],y=(uint32_t)p[6]<<8|p[7];
  if(x<16384&&y<16384){uint32_t oldx=rp_max16>>16,oldy=rp_max16&65535u;
   rp_max16=((x>oldx?x:oldx)<<16)|(y>oldy?y:oldy);}
 }
}
void touch_report_capture(void)
{
 uint32_t mode=rp_read(GPIO+0x310),dir=rp_read(GPIO),ies=rp_read(IES);
 uint8_t tx[75],rx[75],last[72];unsigned have_last=0;
 tx[0]=0x83;for(unsigned i=1;i<75;i++)tx[i]=0;
 rp_count=rp_reads=rp_status=rp_max12=rp_max16=rp_valid43=rp_valid72=rp_bad=0;rp_last_ack=rp_last_header=0xff;
 for(unsigned f=0;f<3;f++){rp_masks[f]=0;for(unsigned i=0;i<72;i++)rp_packets[f][i]=255;}
 rp_write(IES+4,4);rp_write(GPIO+8,IRQ);barrier();
 rp_write(GPIO+0x310,mode&~MODE);barrier();
 rp_irq_before=(rp_read(GPIO+0x200)>>14)&1u;
 if((rp_read(GPIO)&IRQ)||(rp_read(GPIO+0x310)&MODE)||!(rp_read(IES)&4u))goto restore;
 rp_status|=1;touch_report_prompt();
 uint64_t start=rp_now_ms(),last_poll=start;
 for(unsigned iteration=0;iteration<15000;iteration++){
  uint64_t now=rp_now_ms();if(now-start>=15000){rp_status|=8;break;}
  int low=!(rp_read(GPIO+0x200)&IRQ);if(low)rp_status|=16;
  if(low||now-last_poll>=100){
   last_poll=now;
   if(!touch_gpio_transfer(tx,rx,75))break;
   rp_reads++;rp_last_ack=rx[1];rp_last_header=rx[3];
   if(rx[1]==0xa3){
    rp_status|=2;uint8_t *packet=rx+3;unsigned varied=0,same=have_last;
    for(unsigned i=0;i<72;i++){if(packet[i]&&packet[i]!=255)varied=1;if(have_last&&packet[i]!=last[i])same=0;}
    if(varied&&packet[0]!=0x20){
     uint32_t mask=checks(packet);maxima(packet,mask);
     if(!(mask&1u)||!(mask&6u)){rp_bad++;}
     else {
      if(mask&2u)rp_valid43++;if(mask&4u)rp_valid72++;
      if(!same){unsigned slot=rp_count<3?rp_count:2;
       for(unsigned i=0;i<72;i++){rp_packets[slot][i]=packet[i];last[i]=packet[i];}
       rp_masks[slot]=mask;have_last=1;if(rp_count<3)rp_count++;rp_status|=4;if(rp_count==3)rp_status|=64;
      }
     }
    }
   }
  }
  if(!touch_gpio_wait(1000))break;
 }
restore:
 rp_write(GPIO+0x310,(rp_read(GPIO+0x310)&~MODE)|(mode&MODE));barrier();
 rp_write(GPIO+((dir&IRQ)?4u:8u),IRQ);rp_write(IES+((ies&4u)?4u:8u),4);barrier();
 rp_irq_after=(rp_read(GPIO+0x200)>>14)&1u;
 if(!((rp_read(GPIO+0x310)^mode)&MODE)&&!((rp_read(GPIO)^dir)&IRQ)&&!((rp_read(IES)^ies)&4u))rp_status|=32;
}
