# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import subprocess, json, hashlib, tempfile, sys, re
_tmp=tempfile.TemporaryDirectory(prefix='mt7620-review-')
R=Path(_tmp.name);K=Path(__file__).resolve().parents[3]
c=(K/'drivers/net/ethernet/mediatek/mtk_eth_soc.c').read_text()
def function(name):
    match=re.search(r'^static[ \t]+[^;{}]*\b'+re.escape(name)+r'\([^;{}]*\)\n\{',c,re.M)
    assert match, name
    start=match.start();begin=c.index('{',start);depth=1;end=begin+1
    while depth:
        if c[end]=='{':depth+=1
        elif c[end]=='}':depth-=1
        end+=1
    return c[start:end]+'\n'
shim=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <arpa/inet.h>
#include <errno.h>
typedef uint32_t u32;
typedef uint16_t u16;
typedef uint16_t __be16;
typedef uint64_t netdev_features_t;
#define GENMASK(h,l) ((~0U << (l)) & (~0U >> (31-(h))))
#define MTK_SOC_MT7620 1
#define MTK_HAS_CAPS(caps,flag) (((caps)&(flag))==(flag))
#define IS_ENABLED(x) 1
#define MT7620_CDMA_VLAN_BASE 0x430
#define MT7620_CDMA_VLAN_SLOTS 16
#define NETIF_F_HW_VLAN_CTAG_TX 1
#define VLAN_VID_MASK 0x0fff
#define VLAN_CFI_MASK 0x1000
#define ETH_P_8021Q 0x8100
#define ETH_P_8021AD 0x88a8
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
static unsigned writes, reads, barriers;
static bool device_present = true;
struct mtk_soc_data { unsigned caps; };
struct mtk_eth { struct mtk_soc_data *soc; uint8_t *base; u16 mt7620_vlan_vid[16]; };
struct mtk_mac { struct mtk_eth *hw; };
struct net_device { struct mtk_mac mac; };
struct sk_buff { bool present; u16 vlan_tci; };
static void *netdev_priv(struct net_device *dev) { return &dev->mac; }
static bool netif_device_present(struct net_device *dev) { (void)dev; return device_present; }
static bool skb_vlan_tag_present(struct sk_buff *skb) { return skb->present; }
static u16 skb_vlan_tag_get_id(struct sk_buff *skb) { return skb->vlan_tci & VLAN_VID_MASK; }
static bool skb_vlan_tag_get_cfi(struct sk_buff *skb) { return !!(skb->vlan_tci & VLAN_CFI_MASK); }
static u32 readl(void *addr) { u32 val;memcpy(&val,addr,4);reads++;return val; }
static void writel(u32 val,void *addr) { memcpy(addr,&val,4);writes++; }
static void wmb(void) { assert(reads==writes*2);barriers++; }
'''
main=r'''
int main(void) {
 uint8_t mmio[0x500]={0};struct mtk_soc_data soc={MTK_SOC_MT7620};
 struct mtk_eth eth={.soc=&soc,.base=mmio};struct net_device dev={.mac={&eth}};
 unsigned tests=0;
 for(unsigned idx=1;idx<16;idx++){
  unsigned vid=400+idx;
  assert(mtk_mt7620_vlan_tx_add_vid(&dev,htons(ETH_P_8021Q),vid)==0);
  assert(eth.mt7620_vlan_vid[idx]==vid);
 }
 assert(writes==15 && barriers==15);
 assert(mtk_mt7620_vlan_tx_add_vid(&dev,htons(ETH_P_8021Q),400)==0);
 assert(mtk_mt7620_vlan_tx_add_vid(&dev,htons(ETH_P_8021Q),0)==0);
 assert(!eth.mt7620_vlan_vid[0] && writes==15);
 for(unsigned vid=0;vid<4096;vid++) for(unsigned prio=0;prio<8;prio++) for(unsigned dei=0;dei<2;dei++) {
  struct sk_buff skb={true,(u16)(vid|(prio<<13)|(dei<<12))};
  bool hw=!dei && eth.mt7620_vlan_vid[vid&15]==vid;
  assert(!!(mtk_mt7620_features_check(&skb,&dev,1)&1)==hw);
  assert(!mtk_mt7620_features_check(&skb,&dev,0));tests++;
 }
 struct sk_buff packet={true,(u16)(401|(5<<13))};
 assert(mtk_mt7620_features_check(&packet,&dev,1)==1);
 mtk_mt7620_vlan_tx_kill_vid(&dev,htons(ETH_P_8021Q),401);
 assert(!mtk_mt7620_vlan_tx_add_vid(&dev,htons(ETH_P_8021Q),417));
 assert(eth.mt7620_vlan_vid[1]==401 && mtk_mt7620_features_check(&packet,&dev,1)==1);
 packet.vlan_tci=417|(5<<13);assert(mtk_mt7620_features_check(&packet,&dev,1)==0);
 for(unsigned idx=0;idx<16;idx++){
  u32 word;memcpy(&word,mmio+0x430+(idx/2)*4,4);
  assert(((word>>(16*(idx&1)))&0xffff)==eth.mt7620_vlan_vid[idx]);
 }
 memset(mmio,0,sizeof mmio);mtk_mt7620_vlan_restore(&eth);
 for(unsigned idx=0;idx<16;idx++){
  u32 word;memcpy(&word,mmio+0x430+(idx/2)*4,4);
  assert(((word>>(16*(idx&1)))&0xffff)==eth.mt7620_vlan_vid[idx]);
 }
 struct mtk_eth fresh={.soc=&soc,.base=mmio};dev.mac.hw=&fresh;
 unsigned oldwrites=writes;
 assert(!mtk_mt7620_vlan_tx_add_vid(&dev,htons(ETH_P_8021AD),401));
 assert(!fresh.mt7620_vlan_vid[1] && oldwrites==writes);
 soc.caps=0;device_present=false;packet.vlan_tci=401|0x1000;
 assert(mtk_mt7620_features_check(&packet,&dev,1)==1);
 assert(!mtk_mt7620_vlan_tx_add_vid(&dev,htons(ETH_P_8021Q),401));
 assert(!fresh.mt7620_vlan_vid[1] && oldwrites==writes);
 soc.caps=MTK_SOC_MT7620;
 assert(mtk_mt7620_vlan_tx_add_vid(&dev,htons(ETH_P_8021Q),401)==-ENODEV);
 assert(!fresh.mt7620_vlan_vid[1] && oldwrites==writes);
 assert(!mtk_mt7620_vlan_tx_add_vid(&dev,htons(ETH_P_8021AD),401));
 fresh.mt7620_vlan_vid[1]=401;
 assert(!mtk_mt7620_vlan_tx_add_vid(&dev,htons(ETH_P_8021Q),417));
 assert(!mtk_mt7620_vlan_tx_add_vid(&dev,htons(ETH_P_8021Q),0));
 assert(oldwrites==writes);
 printf("PASS: %u VID/PCP/DEI cases; pinned aliases; delete with in-flight tag; MMIO pair preservation and restore; 802.1ad and other-SoC exclusion. Host API mocks, not hardware.\n",tests);
}
'''
names=['mtk_mt7620_vlan_write','mtk_mt7620_vlan_restore','mtk_mt7620_features_check','mtk_mt7620_vlan_tx_add_vid','mtk_mt7620_vlan_tx_kill_vid']
source=shim+''.join(function(name) for name in names)+main
(R/'test-vlan.c').write_text(source)
with (R/'host-vlan.log').open('w') as out:
    subprocess.run(['cc','-std=c17','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-fsanitize=address,undefined','-g','-fno-pie','-no-pie',str(R/'test-vlan.c'),'-o',str(R/'test-vlan')],stderr=subprocess.STDOUT,check=True)
    subprocess.run([str(R/'test-vlan')],stderr=subprocess.STDOUT,check=True)
print((R/'host-vlan.log').read_text(),flush=True)
