#include <stdint.h>
#include <assert.h>
#include <string.h>
#include "ilitek-pixel72.h"
static const uint8_t real_packet[72]={0x5b,0x00,0x48,0xf9,0x00,0xe7,0x01,0x41,0x0a,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0x12,0x12,0x00,0x02,0x20,0x09,0xe2,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x2e};
static unsigned count;static uint32_t event[64][4];
void touch_emit(uint32_t type,uint32_t finger,uint32_t x,uint32_t y){assert(count<64);event[count][0]=type;event[count][1]=finger;event[count][2]=x;event[count][3]=y;count++;}
static void checksum(uint8_t *p){unsigned sum=0;for(unsigned i=0;i<71;i++)sum+=p[i];p[71]=(uint8_t)(0u-sum);}
static void blank(uint8_t *p){memset(p,255,72);p[0]=0x5b;p[1]=0;p[2]=72;p[3]=0xf9;checksum(p);}
static void point(uint8_t *p,unsigned finger,unsigned x,unsigned y){unsigned at=4+finger*5;p[at]=x>>8;p[at+1]=x;p[at+2]=y>>8;p[at+3]=y;p[at+4]=10;checksum(p);}
int main(void){
 struct ilitek_track s={0};uint8_t p[72];memcpy(p,real_packet,72);
 assert(ilitek_pixel72(&s,p,72)&&count==1&&event[0][0]==1&&event[0][2]==3505&&event[0][3]==2191);
 point(p,0,4319,9599);assert(ilitek_pixel72(&s,p,72)&&count==2&&event[1][0]==2&&event[1][2]==65535&&event[1][3]==65535);
 point(p,1,3052,6744);assert(ilitek_pixel72(&s,p,72)&&count==4&&event[3][0]==1&&event[3][1]==1);
 blank(p);assert(ilitek_pixel72(&s,p,72)&&count==6&&event[4][0]==3&&event[5][0]==3&&event[5][1]==1);
 point(p,0,4320,9600);assert(ilitek_pixel72(&s,p,72)&&count==6);
 point(p,0,100,200);p[71]^=1;assert(!ilitek_pixel72(&s,p,72)&&count==6);
 checksum(p);p[0]=0x5a;checksum(p);assert(!ilitek_pixel72(&s,p,72)&&count==6);
 p[0]=0x5b;p[2]=43;checksum(p);assert(!ilitek_pixel72(&s,p,72)&&count==6);
 assert(!ilitek_pixel72(&s,p,43)&&count==6);return 0;
}
