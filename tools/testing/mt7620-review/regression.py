#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Extract real driver functions into a mocked lifecycle/control-flow test.
This does not execute a kernel, DMA, interrupts, or hardware recovery.
"""
import pathlib, re, subprocess, sys, tempfile
source = pathlib.Path(sys.argv[1]).read_text()
def function(name):
    m = re.search(r'^static (?:int|void|bool) '+name+r'\([^;]+?\n\{', source, re.M)
    assert m, name
    end = source.index('\n}', m.end()) + 2
    return source[m.start():end]
probe = function('mtk_probe')
mac_failure = re.search(r'err = mtk_add_mac.*?goto (\w+);', probe, re.S).group(1)
unwind = probe[probe.index('err_unreg_netdev:'):]
prefix = r'''
#include <stdio.h>
#include <stdbool.h>
#include <stdlib.h>
#define MTK_MAX_DEVS 3
#define MTK_SOC_MT7620 1
#define MTK_QDMA 2
#define MTK_SHARED_INT 4
#define MTK_RESETTING 0
#define MTK_FE_IRQ_SHARED 0
#define MTK_FE_IRQ_TX 1
#define MTK_FE_IRQ_RX 2
#define NETREG_REGISTERED 1
#define MTK_HAS_CAPS(c,b) (((c)&(b))==(b))
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define netif_err(...) do {} while (0)
struct mtk_eth;
struct mtk_mac { struct mtk_eth *hw; int id, device_notifier; void *phylink; };
struct net_device { struct mtk_mac *priv; int reg_state, up, stopped; struct {int tx_errors;} stats; };
struct soc {int caps;};
struct meta {int dst;};
struct mtk_eth {struct soc *soc; struct net_device *netdev[3], *dummy_dev; struct mtk_mac *mac[3]; struct meta *dsa_meta[3]; int pending_work, tx_napi, rx_napi, irq[3]; void *dev, *sgmii_pcs[3]; unsigned long state; struct {int monitor_work;} reset;};
struct platform_device {struct mtk_eth *eth;};
static int failed, checks, bad, active, notifiers, reset_status, reads;
static struct mtk_eth *current;
#define netdev_priv(d) ((d)->priv)
#define platform_get_drvdata(p) ((p)->eth)
static bool test_bit(int b, unsigned long *s) {return *s & (1UL<<b);}
static bool mtk_hw_reset_check(struct mtk_eth *e) {reads++; return reset_status;}
static void schedule_work(int *w) {*w=1;}
static void cancel_work_sync(int *w) {*w=0;}
static void cancel_delayed_work_sync(int *w) {*w=0;}
static void phylink_destroy(void *p) {}
static void phylink_disconnect_phy(void *p) {}
static void mtk_pcs_lynxi_destroy(void *p) {}
static void dst_release(int *p) {}
static void unregister_netdevice_notifier(int *n) {if (!*n) bad++; else {notifiers--; *n=0;}}
static int mtk_stop(struct net_device *d) {
 if (!d->up || d->stopped || !current->tx_napi || !current->rx_napi) bad++;
 d->stopped++; return 0;
}
static void unregister_netdev(struct net_device *d) {
 if (d->reg_state != NETREG_REGISTERED) bad++;
 if (d->up) {mtk_stop(d); d->up=0;}
 d->reg_state=0;
}
static void free_netdev(struct net_device *d) {
 if (!d) return;
 if (current->pending_work || d->reg_state || (d->priv && d->priv->device_notifier)) bad++;
 if (d->priv) {active--; free(d->priv);}
 free(d);
}
static void netif_napi_del(int *n) {if (current->pending_work) bad++; *n=0;}
static void synchronize_irq(int i) {}
static void devm_free_irq(void *d, int i, struct mtk_eth *e) {}
static void mtk_hw_deinit(struct mtk_eth *e) {for(int i=0;i<3;i++) if(e->netdev[i] && e->netdev[i]->up) bad++;}
static void mtk_ppe_deinit(struct mtk_eth *e) {}
static void mtk_mdio_cleanup(struct mtk_eth *e) {}
static void mtk_wed_exit(void) {}
'''
funcs = '\n'.join(function(n) for n in ['mtk_tx_timeout','mtk_free_dev','mtk_unreg_dev','mtk_sgmii_destroy'])
if 'static int mtk_cleanup(' in source:
    funcs += '\n'+function('mtk_cleanup')
funcs += '\n'+function('mtk_remove')
# Retain exact error labels and the actual second-MAC failure target.
funcs += '\nstatic int failed_probe(struct mtk_eth *eth, int stage) { int err=-1;\n'
funcs += f'if(stage==0) goto {mac_failure};\n'
funcs += 'if(stage==1) goto err_free_dev;\nif(stage==2) goto err_deinit_ppe;\ngoto err_unreg_netdev;\n'+unwind
main = r'''
static void check(const char *name, bool ok) {checks++; printf("%s %s\n",ok?"PASS":"FAIL",name); if(!ok) failed++;}
static void init(struct mtk_eth *e, struct soc *s, int caps, int count, bool registered, bool up, bool napi) {
 *e=(struct mtk_eth){.soc=s}; s->caps=caps; current=e; active=notifiers=bad=reads=0;
 e->tx_napi=e->rx_napi=napi;
 if(napi) e->dummy_dev=calloc(1,sizeof(struct net_device));
 for(int i=0;i<count;i++) {
  struct net_device *d=calloc(1,sizeof(*d)); struct mtk_mac *m=calloc(1,sizeof(*m));
  m->hw=e; m->id=i; m->phylink=m; d->priv=m; d->reg_state=registered; d->up=up;
  if(caps&MTK_QDMA) {m->device_notifier=1;notifiers++;}
  e->netdev[i]=d;e->mac[i]=m;active++;
 }
}
int main(void) {
 struct mtk_eth e; struct soc s; struct platform_device p={.eth=&e}; char name[128];
 for(int caps=1;caps<=2;caps++) for(int reset=0;reset<2;reset++) for(int status=0;status<2;status++) {
  init(&e,&s,caps,1,0,0,0); e.state=reset; reset_status=status;
  mtk_tx_timeout(e.netdev[0],0);
  bool want=!reset && (caps==1 || status);
  snprintf(name,sizeof(name),"watchdog caps=%d resetting=%d status=%d",caps,reset,status);
  check(name,e.pending_work==want && e.netdev[0]->stats.tx_errors==want && (caps!=1 || reads==0));
  e.pending_work=0; mtk_free_dev(&e);
 }
 for(int stage=0;stage<4;stage++) {
  init(&e,&s,MTK_QDMA,stage==3?2:1,0,0,stage==3);
  if(stage==3) {e.netdev[0]->reg_state=1;e.netdev[0]->up=1;e.pending_work=1;}
  failed_probe(&e,stage);
  snprintf(name,sizeof(name),"probe unwind stage=%d (MAC/IRQ/PPE/register)",stage);
  check(name,!active && !notifiers && !bad && !e.pending_work);
  /* Leaked objects belong only to this short-lived harness process. */
 }
 for(int caps=0;caps<3;caps++) for(int up=0;up<2;up++) {
  init(&e,&s,caps==0?MTK_SHARED_INT:(caps==1?MTK_QDMA:MTK_SOC_MT7620|MTK_SHARED_INT),caps==1?2:1,1,up,1);
  mtk_remove(&p);
  snprintf(name,sizeof(name),"remove %s up=%d",caps==0?"legacy":(caps==1?"qdma":"mt7620"),up);
  check(name,!active && !notifiers && !bad);
 }
 printf("%d checks, %d failures\n",checks,failed);return !!failed;
}
'''
with tempfile.TemporaryDirectory(prefix='mtk-review-') as d:
    path=pathlib.Path(d)/'test.c'; path.write_text(prefix+funcs+main)
    subprocess.run(['cc','-std=gnu11','-Werror','-Wno-unused-label','-o',str(path.with_suffix('')),str(path)],check=True)
    sys.exit(subprocess.run([str(path.with_suffix(''))]).returncode)
