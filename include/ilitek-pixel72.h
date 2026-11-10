#ifndef ILITEK_PIXEL72_H
#define ILITEK_PIXEL72_H
#include <stdint.h>
struct ilitek_track{uint8_t down[10];uint16_t x[10],y[10];uint32_t reports,bad,events;};
void touch_emit(uint32_t type,uint32_t finger,uint32_t x,uint32_t y);
static inline int ilitek_pixel72(struct ilitek_track *s,const uint8_t *p,unsigned n)
{
 if(n!=72||p[0]!=0x5b||p[1]!=0||p[2]!=72){s->bad++;return 0;}
 unsigned sum=0;for(unsigned j=0;j<72;j++)sum+=p[j];
 if(sum&255u){s->bad++;return 0;}
 for(unsigned i=0;i<10;i++){unsigned at=4+5*i;
  uint32_t x=(uint32_t)p[at]<<8|p[at+1],y=(uint32_t)p[at+2]<<8|p[at+3];
  int absent=(x==65535&&y==65535)||x>=4320||y>=9600;
  if(absent){if(s->down[i]){touch_emit(3,i,s->x[i],s->y[i]);s->events++;s->down[i]=0;}continue;}
  uint32_t nx=(uint32_t)((uint64_t)x*65535u/4319u),ny=(uint32_t)((uint64_t)y*65535u/9599u);
  touch_emit(s->down[i]?2:1,i,nx,ny);s->events++;s->down[i]=1;s->x[i]=(uint16_t)nx;s->y[i]=(uint16_t)ny;
 }s->reports++;return 1;
}
#endif
