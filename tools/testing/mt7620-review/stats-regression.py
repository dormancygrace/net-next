# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import subprocess, json, hashlib, tempfile, sys, re
_tmp=tempfile.TemporaryDirectory(prefix='mt7620-review-')
R=Path(_tmp.name);K=Path(__file__).resolve().parents[3]
def function(s,name):
 a=s.index(name);b=s.index('{',a);n=1;c=b+1
 while n:n+=(s[c]=='{')-(s[c]=='}');c+=1
 return s[a:c]
s=(K/'drivers/net/dsa/mt7530.c').read_text();a=s.index('struct mt7620_mib_desc');b=s.index('static void mt7620_get_stats64',a)
code='''#include <stdint.h>
#include <stdio.h>
#include <assert.h>
#include <string.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef uint64_t u64;
#define U16_MAX UINT16_MAX
#define U32_MAX UINT32_MAX
#define MT7530_NUM_PORTS 7
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define BIT(x) (1ul<<(x))
#define GENMASK(a,b) (((~0ul)>>(63-(a)))&((~0ul)<<(b)))
#define for_each_set_bit(p,m,n) for ((p)=0;(p)<(n);(p)++) if (*(m)&BIT(p))
#define ETH_FCS_LEN 4
struct mt7530_mib_counter { u64 value; u32 last; };
struct port { struct mt7530_mib_counter mib[13]; };
struct mt7530_priv { void *regmap; int stats_lock; struct port ports[7]; u8 mib_port_intervals; };
static int locked,reads[7]; static u64 tick;
static void spin_lock_bh(int *p) { assert(!locked); locked=1; }
static void spin_unlock_bh(int *p) { assert(locked); locked=0; }
static u64 packets(int p) {return tick*(p==6?29761:2976);}
static int regmap_read(void *map, u32 reg, u32 *val) {
 assert(!locked);int port=(reg-0x4000)/0x100;int off=(reg-0x4000)%0x100;
 assert(port>=0&&port<7);reads[port]++;
 u64 pk=packets(port);u32 good=(u32)pk&0xffff,bad=(u32)(tick*17)&0xffff;
 switch(off) {
 case 0x10:case 0x20:*val=good|(bad<<16);break;
 case 0x14:case 0x24:*val=(u32)(tick*2048);break;
 case 0x18:case 0x28:*val=(u32)(pk*64);break;
 case 0x1c:*val=(u32)(tick*3)&0xffff;break;
 case 0x2c:case 0x30:*val=((u32)(tick*7)&0xffff)|(((u32)(tick*11)&0xffff)<<16);break;
 default:assert(0);
 } return 0;
}
'''+s[a:b]+'''
int main(void) {
 struct mt7530_priv p={0};
 for(tick=1;tick<=4000;tick++) {
  int before[7];memcpy(before,reads,sizeof(reads));mt7620_mib_update(&p);
  for(int port=0;port<7;port++) {
   int sample=(port==6||tick%10==0);
   assert(reads[port]-before[port]==(sample?13:0));
   u64 t=(port==6?tick:(tick/10)*10);
   u64 pk=t*(port==6?29761:2976);
   assert(p.ports[port].mib[0].value==pk);
   assert(p.ports[port].mib[5].value==pk);
   assert(p.ports[port].mib[3].value==pk*64);
   assert(p.ports[port].mib[8].value==pk*64);
   assert(p.ports[port].mib[1].value==t*17);
   assert(p.ports[port].mib[9].value==t*11);
   assert(p.ports[port].mib[10].value==t*7);
  }
 }
 puts("PASS actual MT7620 switch updater: 4000 ticks, 7 ports, packed16 and byte32 wraps, cadence and MMIO outside cache lock");
}
'''
(R/'test-stats-switch.c').write_text(code)
for name in ['switch']:
 cmd=['gcc','-g','-O1','-fsanitize=address,undefined','-fno-pie','-no-pie',str(R/('test-stats-'+name+'.c')),'-o',str(R/('test-stats-'+name))]
 subprocess.run(cmd,check=True);r=subprocess.run([str(R/('test-stats-'+name))],capture_output=True,text=True,check=True);(R/('host-stats-'+name+'.log')).write_text(r.stdout+r.stderr);print(r.stdout,end='')
# Test the actual descriptor and MT7620 read-clear branch, with independent
# register/name expectations from the retained programming guide.
s=(K/'drivers/net/ethernet/mediatek/mtk_eth_soc.c').read_text();a=s.index('#define MT7620_MIB_STAT');b=s.index('static const char * const mtk_clks_source_name',a)
body=function(s,'void mtk_stats_update_mac(');a2=body.index('\t\tu64 *data');b2=body.index('\n\t} else if',a2)
prefix='''#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <assert.h>
#include <stdio.h>
typedef uint16_t u16; typedef uint32_t u32; typedef uint64_t u64;
#define ETH_GSTRING_LEN 32
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
struct mtk_hw_stats {u64 tx_bytes,tx_packets,tx_skip,tx_collisions,rx_bytes,rx_packets,rx_overflow,rx_fcs_errors,rx_short_errors,rx_long_errors,rx_checksum_errors,rx_flow_control_packets;};
struct reg_map {u32 gdm1_cnt;}; struct soc {struct reg_map *reg_map;};struct mtk_eth {struct soc *soc;};
static u32 regs[64];static int calls;
static u32 mtk_r32(struct mtk_eth *eth,u32 reg) {assert(reg>=0x1300&&reg<=0x133c);u32 *p=&regs[(reg-0x1300)/4];u32 val=*p;*p=0;calls++;return val;}
'''+s[a:b]+'static void update(struct mtk_eth *eth,struct mtk_hw_stats *hw_stats) {\n'+body[a2:b2]+'\n}\n'+'''
int main(void) {
 u32 expected[]={0,4,8,12,32,36,40,44,48,52,56,60};
 const char *names[]={"tx_bytes","tx_packets","tx_skip","tx_collisions","rx_bytes","rx_packets","rx_overflow","rx_fcs_errors","rx_short_errors","rx_long_errors","rx_checksum_errors","rx_flow_control_packets"};
 struct reg_map map={0x1300};struct soc soc={&map};struct mtk_eth eth={&soc};struct mtk_hw_stats stats={0};
 assert(ARRAY_SIZE(mt7620_mib)==12);
 for(int i=0;i<12;i++){assert(mt7620_mib[i].reg==expected[i]);assert(mt7620_mib[i].offset==i);assert(!strcmp(mt7620_mib[i].str,names[i]));regs[expected[i]/4]=UINT32_MAX-i;}
 update(&eth,&stats);assert(calls==12);
 update(&eth,&stats);assert(calls==24);
 for(int i=0;i<12;i++){assert(((u64*)&stats)[i]==UINT32_MAX-i);regs[expected[i]/4]=100+i;}
 update(&eth,&stats);
 for(int i=0;i<12;i++)assert(((u64*)&stats)[i]==(u64)UINT32_MAX+100);
 puts("PASS actual FE descriptor and read-clear loop: 12 names/offsets/registers, repeated reads and totals above32 bits");
}
'''
(R/'test-stats-fe.c').write_text(prefix);subprocess.run(['gcc','-g','-O1','-fsanitize=address,undefined','-fno-pie','-no-pie',str(R/'test-stats-fe.c'),'-o',str(R/'test-stats-fe')],check=True);r=subprocess.run([str(R/'test-stats-fe')],check=True,capture_output=True,text=True);(R/'host-stats-fe.log').write_text(r.stdout+r.stderr);print(r.stdout,end='')
