# MT7620 Ethernet offline review, 2026-09-05

The original five-patch draft ends at 45c71288fbe1, on net-next
6797f12ea40e. The revised six-patch draft ends at
bf0efb3b43206e56efb6272a196cf92ca891091b, on net-next
761ae184f850f33d1bbf6c4530c7f237be780d21. No changes to the MediaTek Ethernet
driver or its FE binding occurred between these upstream bases.

The updated integration code is e22091a10e90, based on the previously
published integration 4104956dceab. The old integration and review branches
remain available. New code is not hardware validated: the user reserved the
bench for another task. No bench connections or production-buildtree writes
were made during this offline review.

## Confirmed findings and corrections

1. **Partial probe cleanup was incomplete** (original lifecycle prerequisite
   9753cca86aea). A later mtk_add_mac failure jumped past mtk_free_dev,
   leaking earlier MACs. IRQ/MDIO/PPE/dummy setup failures could free QDMA
   MAC storage without unregistering its netdevice notifier. A registration
   failure could delete NAPI while pending recovery work remained queued by
   an already published MAC. These paths were inherited or incompletely
   addressed by the original prerequisite, not all introduced by MT7620.
   The revised prerequisite frees earlier MACs, associates notifier cleanup
   with MAC destruction, and cancels pending work after unregistering MACs
   and before NAPI deletion.

2. **The existing general removal path stopped MACs incorrectly.**
   mtk_remove called mtk_stop directly even for a closed MAC, then
   unregister_netdev could call ndo_stop again on an open MAC. mtk_stop
   decrements the shared DMA reference count and may disable NAPI/free DMA.
   The old path also disabled clocks/deleted NAPI before core unregister.
   This predates the series; the original MT7620-only removal branch avoided
   it. The revised prerequisite uses core unregister for all variants,
   drains monitor/recovery work, frees IRQ handlers, and only then deletes
   NAPI, phylink/PCS/netdev resources and disables clocks. The model covers
   one legacy MAC, two QDMA MACs and one MT7620 MAC, each open/closed.
   Real MT7628/QDMA hardware regression testing is still needed.

3. **MT7620 watchdog recovery used NETSYS status definitions** (original
   hardware support 45c71288fbe1). The call chain is netdev watchdog ->
   mtk_tx_timeout -> mtk_hw_reset_check -> FE offset 0x08. MT7620 Programming
   Guide E4 v1.3, section 2.19, gives different meanings to this register's
   bits. A timeout with zero status was discarded; the separate NETSYS
   periodic monitor is intentionally disabled on MT7620. The revised
   hardware patch queues existing FE recovery without this status gate on
   MT7620, retaining MTK_RESETTING exclusion and other SoCs' status gate.
   A mocked zero-status timeout demonstrates the control-flow correction;
   an actual stalled DMA engine/recovery has not been injected on hardware.

4. **The MT7620 binding relaxed other SoCs' resource constraints** (original
   binding 663165516052). Lowering global minimum counts allowed one reset
   for MT7621 and one clock for RT5350. The revised binding keeps the single
   resource exception in the MT7620 branch and restores the original
   minima for other compatibles. The processed-schema regression test
   demonstrates rejection on upstream, accidental acceptance in v1, and
   rejection again in v2, while a valid MT7620 node remains accepted.

## Per-patch review coverage

| Original patch | Result |
| --- | --- |
| 9753cca86aea NAPI/netdevice lifetime | Corrections 1 and 2 folded into the revised prerequisite. |
| 7a3a9b33981d PDMA completion cursor | Allocation resets software cursor consistently with hardware ring index reset; no additional defect confirmed. |
| 048a0e40cdb3 required clocks | BIT_ULL matches the u64 bitmap and avoids MIPS32 shifts beyond unsigned long; no additional defect confirmed. |
| 663165516052 FE binding | Correction 4 restores existing-compatible validation. |
| 45c71288fbe1 MT7620 FE | Correction 3; shared PDMA mapping/ownership changes split into their own prerequisite. |

Reviewed areas: probe/unwind/remove ownership; workqueue and NAPI lifetime;
IRQ teardown ordering; descriptor mapping/unmapping; ring allocation and
completion; RX alignment and checksum flags; 32-bit statistics; phylink
callbacks and MT7620 register guards; reset/watchdog paths; capability gates;
DT compatible/resource constraints; absence of MT7620 PPE in the subset.

PDMA paths inspected include linear heads, both slots of one descriptor,
fragments crossing descriptors, split fragments, first-fragment mapping
failure, failure in the second slot, ring-tail exhaustion and completion of
the final descriptor. The single-map head flag takes precedence over page
flags on a mixed descriptor. The last successfully mapped descriptor bounds
unwind, and PDMA holds the skb until the last descriptor completes. QDMA
retains its previous skb placement. These conclusions are source review,
not new hardware fault-injection evidence.

A suspected MT7620 XDP devmap entry path was rejected after following the
caller: kernel/bpf/devmap.c checks NETDEV_XDP_ACT_NDO_XMIT before enqueue;
MT7620 has no such xdp_features. An ndo_xdp_xmit pointer alone does not expose
this path. Internal phylink callbacks were checked through their mode/MAC
ID guards before identifying any MMIO access as invalid.

The review used the call-path, ownership, failure-path and false-positive
checks from masoncl/review-prompts with rg/git and full relevant functions.
No semcode backend was available; no autonomous upstream review bot report
or human Reviewed-by is claimed. Model tests do not establish IRQ races,
DMA memory ordering, actual phylink behavior or all possible failure paths.
No security boundary crossing was demonstrated; these are correctness and
validation findings for human review.

## Validation and intermediate failure

- Full independent MIPS vmlinux/modules build with CONFIG_NET_DSA=n passed.
- x86_64 MediaTek COMPILE_TEST with WERROR=1 passed on the final source.
- FE dt_binding_check, including generated example, passed.
- Extracted-function model: original 10 failed assertions among 18 checks;
  corrected source 18/18 passes. These are not ten independent bugs.
- Processed-binding model: four baseline and four revised cases pass; two
  invalid existing-SoC cases deliberately demonstrate v1's regression.
- Full integration MIPS vmlinux/modules build passed, including modular
  Ethernet, MT7530 DSA and the metadata tagger configuration.
- Per-commit x86 compilation initially caught two MT7620-specific descriptor
  writes accidentally placed in the new general PDMA prerequisite. They
  were moved to the hardware-support patch before publication. The final
  cumulative tree is unchanged. All six corrected intermediate commits now
  compile successfully. The first failing log is retained locally.
- Strict checkpatch is run with --no-signoff because the draft deliberately
  lacks a human DCO certification. This is not a claim of submission readiness.

Hardware tests recorded in the previous integration document apply only to
4104956dceab / code 3100a3103fb0. Retest open/close, FE/switch unbind/rebind,
TX timeout recovery and bidirectional traffic on the new integration once
the bench is released. Other SoCs, MT7620N and older ECOs need separate tests.

## Submission state

The authorized update was posted at:
https://github.com/openwrt/openwrt/pull/24515#issuecomment-5548184950

No mailing-list series has been sent. The initial upstream scope still
excludes MT7620 PPE, switch/tagger implementation and platform/board patches.
The standalone subset needs the separate integration for a booting board.
A human must review the code, certify DCO and own the submission. No
Signed-off-by, Reviewed-by or Tested-by trailers were fabricated.
