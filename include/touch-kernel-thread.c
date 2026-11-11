/* Offline replacement for v43 _touch_thread only.
 * Keeps loader-started firmware alive: no RESET15, ICE, or host download.
 * Uses only stack state; no writable data is placed in executable text.
 */
#include <stdint.h>
#ifndef TOUCH_HALF_PERIOD_US
#define TOUCH_HALF_PERIOD_US 10
#endif
#if TOUCH_HALF_PERIOD_US != 10 && TOUCH_HALF_PERIOD_US != 2
#error Unsupported tested half period
#endif
#ifndef TOUCH_COUNTER_WAIT
#define TOUCH_COUNTER_WAIT 0
#endif
#ifndef TOUCH_TIMING_LOG
#define TOUCH_TIMING_LOG 0
#endif
#if TOUCH_COUNTER_WAIT && !TOUCH_TIMING_LOG
#error Counter wait requires calibrated timing profile
#endif
#if TOUCH_TIMING_LOG
extern uint64_t kernel_time(void);
extern void kernel_interval(uint32_t interval,uint32_t scale,uint64_t *ticks);
extern int kernel_spin_decision(uint64_t ticks);
extern int kernel_preempt_level(void);
extern int kernel_irq_enabled(void);
#endif
extern uint64_t kernel_map(uint64_t physical,uint64_t size);
extern void kernel_delay(uint32_t microseconds);
extern int kernel_printf(const char *format,...);
extern void kernel_post(uint32_t type,uint32_t finger,uint32_t x,uint32_t y);
#define touch_emit kernel_post
#include "ilitek-pixel72.h"
struct gpio_bus{uint64_t gpio,mi,irq;
#if TOUCH_TIMING_LOG
 uint64_t half_ticks,ticks_per_us;
#endif
};
#if TOUCH_TIMING_LOG
struct touch_timing{uint64_t total,max;uint32_t reads,ack_bad;};
static char *append_text(char *p,const char *s){while(*s)*p++=*s++;return p;}
static char *append_number(char *p,uint64_t value){char digits[20];unsigned n=0;do{digits[n++]='0'+value%10;value/=10;}while(value);while(n)*p++=digits[--n];return p;}
static void log_context(struct gpio_bus *b)
{
 char line[160],*p=line;p=append_text(p,TOUCH_HALF_PERIOD_US==10?"ili_gpio: timing ticks10=":"ili_gpio: timing ticks2=");p=append_number(p,b->half_ticks);
 p=append_text(p,TOUCH_HALF_PERIOD_US==10?" spin10=":" spin2=");p=append_number(p,(uint32_t)kernel_spin_decision(b->half_ticks));
 p=append_text(p," irq=");p=append_number(p,(uint32_t)kernel_irq_enabled());
 p=append_text(p," preempt=");p=append_number(p,(uint32_t)kernel_preempt_level());
 p=append_text(p,TOUCH_COUNTER_WAIT?" counter=1\n":" counter=0\n");*p=0;kernel_printf(line);
}
static void log_timing(struct gpio_bus *b,struct touch_timing *t,struct ilitek_track *track)
{
 char line[192],*p=line;uint64_t divisor=b->ticks_per_us?b->ticks_per_us:1;
 p=append_text(p,"ili_gpio: perf reads=");p=append_number(p,t->reads);
 p=append_text(p," valid=");p=append_number(p,track->reports);
 p=append_text(p," bad=");p=append_number(p,track->bad);
 p=append_text(p," ackbad=");p=append_number(p,t->ack_bad);
 p=append_text(p," avg_us=");p=append_number(p,t->reads?t->total/t->reads/divisor:0);
 p=append_text(p," max_us=");p=append_number(p,t->max/divisor);p=append_text(p,"\n");*p=0;kernel_printf(line);
}
#endif
#ifdef TOUCH_KERNEL_HOST
extern uint32_t kernel_reg_read(uint64_t address);
extern void kernel_reg_write(uint64_t address,uint32_t value);
#define barrier() ((void)0)
static uint32_t rd(uint64_t b,unsigned off){return kernel_reg_read(b+off);}
static void wr(uint64_t b,unsigned off,uint32_t v){kernel_reg_write(b+off,v);}
#else
#define barrier() __asm__ volatile("dsb sy"::: "memory")
static uint32_t rd(uint64_t b,unsigned off){return *(volatile uint32_t *)(b+off);}
static void wr(uint64_t b,unsigned off,uint32_t v){*(volatile uint32_t *)(b+off)=v;}
#endif
static void level(struct gpio_bus *b,unsigned pin,int high)
{wr(b->gpio,0x100+(pin/32)*0x10+(high?4:8),1u<<(pin%32));barrier();}
static void mode(struct gpio_bus *b,unsigned pin)
{wr(b->gpio,0x30c+(pin/8)*0x10,8u<<((pin%8)*4));barrier();}
#if TOUCH_COUNTER_WAIT
static void half_wait(struct gpio_bus *b)
{
 if(!b->half_ticks){kernel_delay(TOUCH_HALF_PERIOD_US);return;}
 uint64_t start=kernel_time();
 for(unsigned spin=0;spin<65536;spin++)if(kernel_time()-start>=b->half_ticks)return;
 kernel_delay(TOUCH_HALF_PERIOD_US); /* fallback if the counter stops advancing */
}
#define HALF_WAIT(bus) half_wait(bus)
#else
#define HALF_WAIT(bus) kernel_delay(TOUCH_HALF_PERIOD_US)
#endif
static void read_report(struct gpio_bus *b,uint8_t *rx)
{
 level(b,97,0);level(b,98,0);
 for(unsigned i=0;i<75;i++){uint8_t out=i?0:0x83,in=0;
  for(int bit=7;bit>=0;bit--){level(b,13,(out>>bit)&1);HALF_WAIT(b);level(b,97,1);HALF_WAIT(b);
   in=(uint8_t)((in<<1)|((rd(b->gpio,0x200)>>12)&1u));level(b,97,0);}
  rx[i]=in;
 }level(b,98,1);kernel_delay(1000);
}
#ifndef TOUCH_KERNEL_HOST
__attribute__((section(".text.entry")))
#endif
void touch_thread_entry(void *argument,int result)
{
 (void)argument;(void)result;
 struct gpio_bus b;struct ilitek_track track;uint8_t rx[75];
#if TOUCH_TIMING_LOG
 struct touch_timing timing;timing.total=timing.max=timing.reads=timing.ack_bad=0;
 kernel_interval(TOUCH_HALF_PERIOD_US,1000,&b.half_ticks);kernel_interval(1,1000,&b.ticks_per_us);
#endif
 for(unsigned i=0;i<10;i++){track.down[i]=0;track.x[i]=track.y[i]=0;}track.reports=track.bad=track.events=0;
 b.gpio=kernel_map(0x10005000u,0x1000);b.mi=kernel_map(0x11e60000u,0x1000);b.irq=kernel_map(0x11e20000u,0x1000);
 if(!b.gpio||!b.mi||!b.irq){kernel_printf("ili_gpio: map failed\n");for(;;)kernel_delay(10000);}
 level(&b,98,1);level(&b,97,0);level(&b,13,0);
 wr(b.gpio,4,1u<<13);wr(b.gpio,8,(1u<<12)|(1u<<14));wr(b.gpio,0x34,6);barrier();
 mode(&b,12);mode(&b,13);mode(&b,97);mode(&b,98);mode(&b,14);
 wr(b.mi,0x94,1u<<11);wr(b.irq,0x54,4);barrier();
 kernel_printf("ili_gpio: online, firmware preserved, pixel72 negative checksum\n");
#if TOUCH_TIMING_LOG
 log_context(&b);
#endif
 unsigned idle=0,announced=0,event_announced=0,heartbeat=0;
#ifdef TOUCH_KERNEL_HOST
 unsigned iteration=0;
#endif
 for(;;){
#ifdef TOUCH_KERNEL_HOST
  if(iteration++>=80)return;
#endif
  int irq=!(rd(b.gpio,0x200)&(1u<<14));
  if(irq||++idle>=20){idle=0;
#if TOUCH_TIMING_LOG
   uint64_t before=kernel_time();
#endif
   read_report(&b,rx);
#if TOUCH_TIMING_LOG
   uint64_t duration=kernel_time()-before;timing.reads++;timing.total+=duration;if(duration>timing.max)timing.max=duration;
   if(rx[1]!=0xa3)timing.ack_bad++;
#endif
   if(rx[1]==0xa3&&ilitek_pixel72(&track,rx+3,72)&&!announced){kernel_printf("ili_gpio: first verified report\n");announced=1;}
  }
  if(track.events&&!event_announced){kernel_printf("ili_gpio: first HID event queued\n");event_announced=1;}
  if(++heartbeat>=1024){heartbeat=0;
#if TOUCH_TIMING_LOG
   log_timing(&b,&timing,&track);
#endif
   if(track.events)kernel_printf("ili_gpio: HB verified reports and HID events\n");
   else if(track.reports)kernel_printf("ili_gpio: HB valid reports, no contact yet\n");
   else kernel_printf("ili_gpio: HB waiting for verified pixel72\n");
  }
  kernel_delay(1000);
 }
}
