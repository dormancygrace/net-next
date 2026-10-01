# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import subprocess, json, hashlib, tempfile, sys, re
_tmp=tempfile.TemporaryDirectory(prefix='mt7620-review-')
R=Path(_tmp.name);K=Path(__file__).resolve().parents[3]
def function(s,name):
 a=s.index(name);b=s.index('{',a);n=1;c=b+1
 while n:n+=(s[c]=='{')-(s[c]=='}');c+=1
 return s[a:c]
prefix=r'''#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
typedef uint32_t u32;
#define MTK_MAX_DEVS 3
#define MTK_SOC_MT7620 1
#define MTK_HAS_CAPS(c,m) (((c)&(m))==(m))
#define MTK_GDMA_TO_PDMA 1
#define MTK_TX_DONE_INT 1
#define MTK_CDMP_IG_CTRL 0x400
#define MTK_CDMP_STAG_EN 1
#define MTK_CDMP_EG_CTRL 0x404
#define HZ 100
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
struct mtk_eth;
struct mtk_mac {struct mtk_eth *hw;void *phylink,*of_node;int id,ppe_idx;};
struct net_device {struct mtk_mac *mac;};
struct regmap {u32 gdma_to_ppe[3];};
struct mtk_soc_data {int caps,ppe_num,offload_version;struct regmap *reg_map;struct{u32 irq_done_mask;}rx;bool v2;};
struct mtk_eth {struct mtk_soc_data *soc;void *prog;int dma_refcnt,tx_napi,rx_napi,mt7620_stats_work;struct net_device *netdev[3];void *ppe[3];};
static int metadata_calls,phy_calls,dma_calls,disconnect_calls,napi_calls,queue_calls,poll_calls;
static int metadata_error,phy_error,dma_error;static bool dsa;
static struct mtk_mac *netdev_priv(struct net_device *d){return d->mac;}
static bool mtk_uses_dsa(struct net_device*d){return dsa;}
static bool mtk_uses_ralink_dsa(struct net_device*d){return false;}
static bool mtk_uses_mtk_oob(struct net_device*d){return false;}
static bool mtk_is_netsys_v2_or_greater(struct mtk_eth*e){return e->soc->v2;}
static int mtk_dsa_metadata_init(struct mtk_eth*e){metadata_calls++;return metadata_error;}
static int phylink_of_phy_connect(void*p,void*n,int x){phy_calls++;return phy_error;}
static void phylink_disconnect_phy(void*p){disconnect_calls++;}
static void phylink_start(void*p){}
static int mtk_start_dma(struct mtk_eth*e){dma_calls++;return dma_error;}
static int refcount_read(int*p){return *p;}
static void refcount_set(int*p,int n){*p=n;}
static void refcount_inc(int*p){(*p)++;}
static void mtk_ppe_start(void*p){}
static void mtk_ppe_update_mtu(void*p,int m){}
static void mtk_gdm_config(struct mtk_eth*e,int id,u32 val){}
static int mtk_max_gmac_mtu(struct mtk_eth*e){return 1500;}
static void napi_enable(int*p){napi_calls++;}
static void mtk_tx_irq_enable(struct mtk_eth*e,u32 v){}
static void mtk_rx_irq_enable(struct mtk_eth*e,u32 v){}
static void netif_tx_start_all_queues(struct net_device*d){queue_calls++;}
static void schedule_delayed_work(int*p,int t){poll_calls++;}
static u32 mtk_r32(struct mtk_eth*e,u32 r){return 0;}
static void mtk_w32(struct mtk_eth*e,u32 v,u32 r){}
#define netdev_err(...) ((void)0)
'''
suffix=r'''
static void reset(void){metadata_calls=phy_calls=dma_calls=disconnect_calls=napi_calls=queue_calls=poll_calls=0;metadata_error=phy_error=dma_error=0;dsa=true;}
int main(void){
 struct regmap map={0};struct mtk_soc_data soc={.caps=MTK_SOC_MT7620,.reg_map=&map};struct mtk_eth eth={.soc=&soc};struct mtk_mac mac={.hw=&eth};struct net_device dev={.mac=&mac};eth.netdev[0]=&dev;
 reset();metadata_error=-12;assert(mtk_open(&dev)==-12);assert(metadata_calls==1&&phy_calls==0&&dma_calls==0&&napi_calls==0&&queue_calls==0&&poll_calls==0&&eth.dma_refcnt==0);
 reset();phy_error=-19;assert(mtk_open(&dev)==-19);assert(metadata_calls==1&&phy_calls==1&&dma_calls==0&&queue_calls==0&&poll_calls==0);
 reset();dma_error=-5;assert(mtk_open(&dev)==-5);assert(disconnect_calls==1&&queue_calls==0&&poll_calls==0&&eth.dma_refcnt==0);
 reset();assert(mtk_open(&dev)==0);assert(metadata_calls==1&&phy_calls==1&&dma_calls==1&&napi_calls==2&&queue_calls==1&&poll_calls==1);
 reset();eth.dma_refcnt=0;soc.caps=0;soc.v2=true;metadata_error=-12;int ret=mtk_open(&dev);
 if(ret||metadata_calls){fprintf(stderr,"FAIL newer NETSYS was made dependent on unused DSA metadata allocation: return=%d calls=%d\n",ret,metadata_calls);return 3;}
 assert(phy_calls==1&&dma_calls==1&&queue_calls==1&&poll_calls==0);
 puts("PASS actual open function: metadata/PHY/DMA failures, MT7620 success and preserved newer NETSYS allocation behavior");
}
'''
for name,s in [('linux',(K/'drivers/net/ethernet/mediatek/mtk_eth_soc.c').read_text())]:
 out=R/('test-open-'+name+'.c');out.write_text(prefix+function(s,'static int mtk_open(')+suffix)
 exe=out.with_suffix('');subprocess.run(['gcc','-O1','-g','-fsanitize=address,undefined','-fno-pie','-no-pie',str(out),'-o',str(exe)],check=True)
 ret=subprocess.run([str(exe)],capture_output=True,text=True);(R/('host-open-'+name+'.log')).write_text(ret.stdout+ret.stderr);print(name,ret.returncode,ret.stdout+ret.stderr,flush=True)
 if ret.returncode:raise SystemExit(ret.returncode)
