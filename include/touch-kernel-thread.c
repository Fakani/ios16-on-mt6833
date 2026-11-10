/* Offline replacement for v43 _touch_thread only.
 * Keeps loader-started firmware alive: no RESET15, ICE, or host download.
 * Uses only stack state; no writable data is placed in executable text.
 */
#include <stdint.h>
extern uint64_t kernel_map(uint64_t physical,uint64_t size);
extern void kernel_delay(uint32_t microseconds);
extern int kernel_printf(const char *format,...);
extern void kernel_post(uint32_t type,uint32_t finger,uint32_t x,uint32_t y);
#define touch_emit kernel_post
#include "ilitek-pixel72.h"
struct gpio_bus{uint64_t gpio,mi,irq;};
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
static void read_report(struct gpio_bus *b,uint8_t *rx)
{
 level(b,97,0);level(b,98,0);
 for(unsigned i=0;i<75;i++){uint8_t out=i?0:0x83,in=0;
  for(int bit=7;bit>=0;bit--){level(b,13,(out>>bit)&1);kernel_delay(10);level(b,97,1);kernel_delay(10);
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
 for(unsigned i=0;i<10;i++){track.down[i]=0;track.x[i]=track.y[i]=0;}track.reports=track.bad=track.events=0;
 b.gpio=kernel_map(0x10005000u,0x1000);b.mi=kernel_map(0x11e60000u,0x1000);b.irq=kernel_map(0x11e20000u,0x1000);
 if(!b.gpio||!b.mi||!b.irq){kernel_printf("ili_gpio: map failed\n");for(;;)kernel_delay(10000);}
 level(&b,98,1);level(&b,97,0);level(&b,13,0);
 wr(b.gpio,4,1u<<13);wr(b.gpio,8,(1u<<12)|(1u<<14));wr(b.gpio,0x34,6);barrier();
 mode(&b,12);mode(&b,13);mode(&b,97);mode(&b,98);mode(&b,14);
 wr(b.mi,0x94,1u<<11);wr(b.irq,0x54,4);barrier();
 kernel_printf("ili_gpio: online, firmware preserved, pixel72 negative checksum\n");
 unsigned idle=0,announced=0,event_announced=0,heartbeat=0;
#ifdef TOUCH_KERNEL_HOST
 unsigned iteration=0;
#endif
 for(;;){
#ifdef TOUCH_KERNEL_HOST
  if(iteration++>=80)return;
#endif
  int irq=!(rd(b.gpio,0x200)&(1u<<14));
  if(irq||++idle>=20){idle=0;read_report(&b,rx);
   if(rx[1]==0xa3&&ilitek_pixel72(&track,rx+3,72)&&!announced){kernel_printf("ili_gpio: first verified report\n");announced=1;}
  }
  if(track.events&&!event_announced){kernel_printf("ili_gpio: first HID event queued\n");event_announced=1;}
  if(++heartbeat>=1024){heartbeat=0;
   if(track.events)kernel_printf("ili_gpio: HB verified reports and HID events\n");
   else if(track.reports)kernel_printf("ili_gpio: HB valid reports, no contact yet\n");
   else kernel_printf("ili_gpio: HB waiting for verified pixel72\n");
  }
  kernel_delay(1000);
 }
}
