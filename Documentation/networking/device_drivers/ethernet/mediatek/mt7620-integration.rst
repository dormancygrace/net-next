.. SPDX-License-Identifier: GPL-2.0-only

MT7620A/N net-next integration
==============================

Revision note: v7 adds TX VLAN insertion and converges the Ethernet fixes
with OpenWrt, as described in the final section. Earlier validation below
applies to its named source revision. V7 has not been booted on hardware.

This is an integration and hardware-validation tree, based on net-next
``6797f12ea40e788c7da47a7cf9ea4a9341548de0``. It follows Daniel Golle's
recommendation in `OpenWrt PR 24515`_ to integrate the frame engine first,
reuse the MT7530 DSA driver with a separate metadata tag protocol, and
provide a bootable public tree before proposing an Ethernet subset.

Initial status, 2026-09-04: builds and DT validation pass as described below.
RAM boot, PHY attachment and basic LAN1/WAN traffic have been obtained on
MT7620A ver2 ECO6 with 128 MiB RAM. Detailed validation below distinguishes
completed tests from work still pending.
The test board is a ZBTlink WE826-T2.
Historical OpenWrt test results are not evidence of this tree's operation.

Initial architecture and limits (historical)
--------------------------------------------

The FE driver owns PDMA and reset line 21. The MMIO switch driver owns ESW
reset 23, EPHY reset 24, MDIO, PHY tuning and link interrupts. Both use the
existing MT7620 system-controller binding. The base already contains the
MTMIPS clock and reset providers. SOC_MT7620 now selects CLK_MTMIPS because
early time_init needs it; no duplicate provider is added.

The initial topology is the five integrated 10/100 PHYs (ports 0--4) and
internal 1 Gbit/s CPU port 6. The integrated switch is supported through
``mt7530-mmio`` and ``mt7530``, not a separate downstream switch driver.
Port 5, PPE port 7, EEE and TBF offload are not supported in this stage.

The ``mtk-oob`` tagger puts the destination port in ``METADATA_HW_PORT_MUX``.
The FE translates that metadata to TXD4's eight-bit forwarding bitmap.
RXD4 supplies the ingress port. There is no in-band tag and no tag overhead.
An ordinary conduit packet has a zero TX bitmap, requesting normal
switch destination lookup; bit 24 would force physical port 4.

RX checksum offload is enabled. IPv4 TX checksum, SG, TSO, TSO6 and IPv6
TX checksum are enabled only for ECO >= 5, following the historical
driver workaround for early-ECO checksum/segmentation failures. This is
not an independently reproduced silicon erratum. The frame engine and
switch accept frames up to 2048 bytes including
Ethernet header and FCS, giving an untagged MTU ceiling of 2030. VLAN headers
consume part of that frame budget. XDP and hardware VLAN insertion are
outside this initial subset; VLAN frames are handled in software by the FE.

The switch uses 16 VLAN table slots with a separate VID-to-slot mapping.
Slot zero is reserved for VID zero and VLAN-unaware bridging; 15 nonzero
VIDs can be resident at once, including a bridge's default VID 1. Exhaustion
returns ENOSPC. VLAN IDs can span the normal 12-bit range. Shared MT7530
FDB, STP, bridge membership, flooding and mirroring operations are reused.

MT7620 switch MIBs have a different layout, including packed 16-bit counters.
A 20 ms worker extends counters in software. Sustained scheduling delays
longer than a counter wrap interval can lose wraps; saturation and CPU-port
counter consistency are therefore part of the hardware test plan.
Conduit rtnetlink statistics use software counters. Its ethtool statistics
also expose twelve CPU GDM1 counters, using the MT7620 register layout.
These clear-on-read 32-bit registers are accumulated into protected 64-bit
totals and polled once per second while the conduit is open. The worker is
cancelled before DMA shutdown; cached totals remain available while down.
PPE GDM2 counters are not included.

Initial implementation stages (historical)
------------------------------------------

1. **Platform prerequisites.** Correct the MT7620 SoC compatible, CPU node,
   bus range and UART alias. Describe the interrupt-controller compatible
   tuple and address cells. Select the required clock provider. Assert network
   resets before system restart.
   The restart delay uses udelay because restart runs in atomic context.
2. **Ethernet lifecycle prerequisites.** Attach NAPI before register_netdev,
   unwind partial registration, release phylink objects, and clear stale
   netdevice pointers on deferred MAC address lookup. Reset the PDMA TX
   completion cursor when allocating a new ring. Use BIT_ULL when testing the
   64-bit clock bitmap: BIT aliases clock 43 to clock 11 on MIPS32.
3. **FE binding and driver.** Add the single-conduit binding, legacy PDMA
   register map, independent FE reset, software counters, revision-gated
   offloads and receive-length programming. Skip newer GMAC/PPE register
   accesses, including the reset recovery path. RX does not interpret a
   VLAN indication as an in-band DSA tag or use inactive PPE fields as a
   flow hash. Honor the RX checksum feature setting. Keep PDMA skbs until the
   last mapped descriptor completes and unwind every mapped segment on
   errors. Use aligned DMA addresses with hardware RX_2B_OFFSET.
4. **Metadata protocol.** Add the tagger separately, then add FE descriptor
   translation. Allocate RX metadata before DMA starts and before the
   MT7620 netdevice is published.
5. **Switch binding and driver.** Reuse the MT7530 MMIO frontend and common
   switch operations. Add MT7620 setup, EPHY tuning, relocated MDIO access,
   VLAN slots, MIBs and link IRQs. Register IRQs after the MDIO bus and mask
   them before resource unwind so PHY objects outlive the handler. Keep each
   PHY interrupt masked until its DSA port opens, and synchronize it when
   the port closes. Use the MT7620 GMACCR offset 0x3fe0 for frame limits.
6. **DT and demos.** Add FE and switch nodes to the common DTSI, an MT7620N
   include, A/N evaluation demos and a WE826-T2 RAM demo. The WE826-T2 port
   order is LAN1=3, LAN2=2, LAN3=1, LAN4=0, WAN=4. It detects RAM and uses
   ttyS0 at 115200 8N1. Evaluation demos assume 32 MiB and 57600 baud.
7. **Review subset.** Publish the NAPI/lifecycle, PDMA cursor and clock-bitmap fixes, FE
   binding and base Ethernet support as five patches on clean net-next.
   The subset compiles without DSA enabled. Its runtime validation uses
   the complete integration tree because the switch must be initialized.
   OOB metadata, switch support, DTS and platform patches are separate.
   MT7620 PPE support is not included.

Building
--------

Use a separate output directory and a MIPS little-endian toolchain::

    export ARCH=mips
    export CROSS_COMPILE=/path/to/mipsel-toolchain/bin/mipsel-linux-musl-
    make O=/path/to/output mt7620_dsa_defconfig
    make O=/path/to/output -j8 vmlinux modules dtbs

For a WE826-T2 RAM image, change the built-in DT and supply an initramfs::

    scripts/config --file /path/to/output/.config \
        -d DTB_MT7620A_EVAL -e DTB_ZBT_WE826_T2 \
        --set-str INITRAMFS_SOURCE '/path/to/rootfs /path/to/devices.list'
    make O=/path/to/output olddefconfig
    make O=/path/to/output -j8 uImage.bin dtbs

The host PATH must contain mkimage. With an OpenWrt toolchain, export its
STAGING_DIR. The defconfig has no MTD/block drivers or local initramfs path.

The initramfs needs /init, a shell, mount and diagnostic tools, the ELF
interpreter and all shared libraries if dynamically linked. Include this
line in devices.list so the kernel can open the early console::

    nod /dev/console 0600 0 0 c 5 1

Mount proc, sysfs and devtmpfs in /init. The RAM-test initramfs includes BusyBox,
iproute2 ip/bridge and iperf3 binaries plus their libraries, and a separately
cross-built ethtool. Their dynamic dependencies were checked with readelf
and execution under qemu-mipsel. This does not emulate MT7620 hardware.

RAM boot must use the bootloader's RAM loading and bootm facility. The
RAM transfer address must be selected from the actual RAM/bootloader
memory layout and must not overlap the kernel load destination. Read load
and entry addresses from the built uImage, rather than copying addresses
from another build. Do not erase, install firmware, saveenv or write flash.
A serial/recovery arrangement and a permitted service interruption are
required before running the hardware step.

Validation record
-----------------

The validation workspace retains complete command output and configurations.
The compiler for MIPS builds is OpenWrt GCC 13.3.0 with musl. Checks include:

* Full MIPS built-in kernel and demo DT builds.
* Full MIPS kernel and modules with the FE, DSA core, MT7530 frontends and
  metadata tagger built as modules.
* x86_64 allmodconfig COMPILE_TEST builds of the changed Ethernet, MT7530
  core/MMIO and tagger objects, with warnings treated as errors. The initial
  build caught a 64-bit complement narrowing issue in the IRQ mask; it was
  corrected with GENMASK_U32 and the build passed.
* dt_binding_check for the changed Ethernet, switch, interrupt-controller
  and platform schemas and their examples. One later run emitted a Python
  jobserver-pipe warning; there were no binding diagnostics.
* Full dt-validate against processed schemas for MT7620A, MT7620N and
  WE826-T2 demo DTBs: no diagnostics.
* git diff --check and per-patch checkpatch review.
  The atomic restart delay and new-file MAINTAINERS reminders are reviewed
  informational findings, not suppressed hardware failures.

The first raw image exposed a missing CLK_MTMIPS selection; the next boot
exposed the 32-bit clock bitmap test. Once FE probe passed, premature PHY
link interrupts caused a NULL PHY driver dereference. These were fixed and
r7 booted cleanly with all five DSA user ports. Larger-MTU testing then found
the GMACCR relocation, corrected in r8. Earlier failed images are superseded.
The WE826 U-Boot tested here rejects gzip and failed to decode the tested
LZMA stream; use the uncompressed uImage for this RAM procedure.

Do not add a Tested-by trailer without a human tester's authorization.
MT7620N and other boards/revisions have not been hardware tested.

Completed hardware checks (WE826-T2, MT7620A ECO6)
--------------------------------------------------

The following short tests used two external 100BASE-T full-duplex links.
They establish basic integration behavior, not long-duration qualification.
The application rate was deliberately capped below wire rate.

.. list-table:: RAM validation results
   :header-rows: 1
   :widths: 38 62

   * - Test
     - Result
   * - Boot and PHY attachment
     - Clean serial boot; five PHYs and DSA ports; LAN1=PHY3, WAN=PHY4.
   * - IPv4 TCP, separate LAN1/WAN RX and TX
     - Four 10-second runs at 85 Mbit/s: receiver 84.93--84.95 Mbit/s,
       zero retransmissions (r7).
   * - IPv4 TCP, simultaneous WAN RX/TX
     - About 84.99/84.89 Mbit/s for 10 seconds; six retransmissions in
       peer-to-DUT direction (r7). This is not a zero-loss result.
   * - Checksum/SG/TSO disabled
     - WAN TCP TX at 50 Mbit/s for eight seconds; 49.93 Mbit/s received,
       zero retransmissions (r9).
   * - IPv6 TCP, RX and TX with offloads enabled
     - Eight seconds each at 70 Mbit/s; 70.03/69.99 Mbit/s received,
       zero retransmissions (r9).
   * - IPv4 UDP TX
     - Eight seconds, 1000-byte payload, 40 Mbit/s; zero receiver loss (r9).
   * - MTU and DMA restart
     - IP MTU 2030 passes both connected ports; 2031 is rejected.
       Large packets still pass after ports and conduit are stopped and
       reopened (r8).
   * - Bridge and VLANs
     - Standalone ports are isolated; joining a VLAN-unaware bridge enables
       peer traffic. Different PVIDs 4093/4094 isolate peers; a common PVID
       4094 restores traffic. CPU access through the bridge VLAN passes.
   * - VLAN table capacity
     - Fifteen nonzero VIDs accepted; the next returns ENOSPC. Deleting one
       VID permits slot reuse (r8).
   * - Tagged WAN, untagged LAN1
     - VLAN 120 passes peer-to-peer and peer-to-CPU with no WAN PVID (r9).
       The bench explicitly transported the tag; an earlier double-tag
       setup stripped it and was excluded from driver results.
   * - Unbind/rebind
     - Switch and FE unbound, then FE and switch rebound; DSA tree recreated
       without exceptions, interfaces reopened and LAN1 ping restored (r9).

R7--r9 are local artifact labels, not upstream release versions. The code
revision after consolidating these fixes is
``3100a3103fb0926b2d98c4ea24fd4616b84b9887``. Artifact hashes and raw test output
are retained with the local build record. Final image validation records
its own hash rather than reusing a previous image's result.

The FE IRQ row in /proc/interrupts remains zero on this base despite working
traffic and NET_RX progress. The MIPS CPU IRQ chip uses handle_percpu_irq
without the per-CPU descriptor flag for the device IRQ; the current genirq
reporting path emits zeros when tot_count is zero. This base IRQ-accounting
issue remains a platform follow-up and is not used as a traffic measurement.
The original revision did not expose FE ethtool counters. The FE-counter
revision below adds the separate CPU GDM1 layout, not the NETSYS layout.

LAN2--LAN4 physical traffic, older ECOs, MT7620N hardware, sustained
minimum-frame load, exhaustive multicast/mirror/STP tests and fault injection
remain unvalidated. A manual STP-state request with bridge STP disabled was
immediately restored to forwarding by the bridge core; it is not counted
as a successful STP-blocking test. The plan below identifies further work.

Hardware acceptance plan
------------------------

Record the exact Git revision, image SHA-256, U-Boot version, silicon
revision, RAM size, serial log, peer setup and commands for each result.

* Boot: serial initialization, expected five PHYs, DSA port creation,
  single FE IRQ, switch link IRQ and no deferred probes or exceptions.
* Each port: ping in both directions, negotiated speed/duplex, unplug/replug
  with IRQ accounting, and repeated interface down/up after traffic.
* Isolation: traffic addressed to each DSA user port must leave only that
  physical port. Check both known unicast and broadcast/unknown traffic.
* Bridge: learning, FDB dump/add/delete, STP blocking, port leave/rejoin and
  broadcast/multicast flooding. Verify packet captures on a separate peer.
* VLANs: tagged and untagged membership, PVID changes, VID 1 and a high VID,
  mixed VLAN-aware/unaware ports, all 15 slots, ENOSPC on the next VID,
  deletion and slot reuse. Check isolation, not just successful commands.
* Offloads: IPv4/IPv6 TCP and UDP in both directions, then checksum and
  TSO/SG on/off comparisons. Capture checksums at the receiving peer;
  transmit-side captures alone can show pre-offload placeholders.
* MTU: 1500, intermediate sizes, the 2030 untagged limit, rejection beyond
  the limit and reduced payload with VLAN headers. Repeat after down/up.
* Load: iperf3 both directions and simultaneous flows, CPU use, IRQ/NAPI
  progress, no DMA stalls, narrow-counter wraps and counter monotonicity.
* Lifecycle: FE and switch module reload/unbind, clean IRQ/work teardown,
  re-probe and traffic.

A successful WE826-T2 result establishes that tested board/revision only.
MT7620N and older ECO revisions need separate hardware evidence.

Sources and submission
----------------------

Primary source work is `OpenWrt PR 24493`_ (DSA) and `OpenWrt PR 24557`_
(Ethernet), pinned through OpenWrt commit
``17e5c923a083f60b0d55ef08f47fc88fc2efbff8``. The implementation is checked
against the `MT7620 Programming Guide`_, E4 v1.3, sections 2.19 (FE/PDMA)
and 2.20 (switch). The guide is linked, not redistributed in this tree.
EPHY tuning retains attribution to the OpenWrt gsw_mt7620.c authors.

.. _OpenWrt PR 24515: https://github.com/openwrt/openwrt/pull/24515#issuecomment-5546101426
.. _OpenWrt PR 24493: https://github.com/openwrt/openwrt/pull/24493
.. _OpenWrt PR 24557: https://github.com/openwrt/openwrt/pull/24557
.. _MT7620 Programming Guide: https://w.electrodragon.com/w/images/5/51/MT7620_ProgrammingGuide_20121101.pdf

Offline review revision (2026-09-05)
------------------------------------

The hardware results above belong to ``mt7620-integration`` at
``4104956dceab`` (code ``3100a3103fb0``). The separate
``mt7620-integration-v2`` candidate with offline review corrections at
``e22091a10e90`` was initially reviewed without a bench. Do not transfer
the earlier hardware results to that exact intermediate revision. Its
corrections are included in the later FE-counter RAM tests below.

The revised standalone ``mt7620-ethernet-review-v2`` branch is six patches
on net-next ``761ae184f850``. It fixes partial-probe cleanup and general
netdevice/NAPI removal ordering, removes the NETSYS-only status gate from
the MT7620 TX watchdog, and preserves other SoCs' DT resource constraints.
Shared PDMA buffer ownership changes are now a separate prerequisite.
MT7620 PPE remains outside the series.

Review evidence and reproducible host-side models are in
``tools/testing/mt7620-review/``. They complement compile and DT checks;
they do not validate actual DMA recovery or interrupt concurrency. The
original branches remain published for reproducibility. The six-patch
RFC draft remains a draft.

FE-counter RAM revision (2026-09-05)
------------------------------------

Code revision ``142693f0ec22`` adds CPU GDM1 ethtool statistics and includes
the earlier lifecycle corrections. IPv4 TX checksum now shares the ECO5
gate with the other TX offloads; ECO6 features remain enabled. The image
was built from this source before committing it, with a diagnostic
initramfs. Its SHA-256 is
``2bde2250a3bcdbf479f48b8aa642af53c7fb4a56ebde937b83cf5aa11da6057a``.
The final local manifest records the image hash and source-file hashes.

The following tests ran on the same WE826-T2 MT7620A ECO6 with two 100BASE-T
full-duplex links. They do not establish support for early ECOs or MT7620N.

* Consecutive MMIO reads on the probe image confirmed clear-on-read GDM1
  counters. Ethtool on the counter image reports twelve FE counters in
  addition to the DSA conduit port statistics.
* UDP: fourteen cases, three datagrams each, repeated with RX checksum
  enabled and disabled. IPv4 options, IPv6 hop-by-hop headers and both IP
  versions' fragmentation were included. Each matrix delivered all 21
  valid datagrams and none of the 21 invalid ones. IPv4 zero UDP checksum
  was accepted; IPv6 zero UDP checksum was rejected. Each matrix added
  exactly nine hardware checksum errors; other invalid packets were
  rejected by software. Disabling RX checksum trust does not disable
  the GDMA checksum checker. Packet socket checksum metadata can also
  reflect software processing; it is not a raw RXD4 capture.
* TCP: twelve good SYNs produced twelve RST replies with verified correct
  wire checksums; twelve SYNs with bad checksums produced no RST. The
  cases covered both IP versions and IPv4 options/IPv6 hop-by-hop headers.
  The hardware checksum-error counter increased by nine.
* Eight separate IPv4/IPv6 TCP RX/TX runs on LAN1 and WAN, eight seconds
  each at 80 Mbit/s, received 79.87--80.01 Mbit/s with no retransmissions.
  A WAN bidirectional run received 79.86/79.73 Mbit/s, also without
  retransmissions. These are paced application rates, not maximum rates.
* TSO enabled: 1105/1109 software TX skbs corresponded to 31322/31664
  GDM1 packets for IPv4/IPv6. TSO disabled: software and hardware counts
  matched at 31321/31666. The four six-second runs received about
  59.93--59.94 Mbit/s at a requested 60 Mbit/s.
* MTU 1500: only IP length 1500 was delivered; lengths 1501, 2026 and
  2030 caused nine GDM1 length errors. MTU 2030: all four lengths passed
  without new GDM1 length errors. Length 2031 was not delivered in either
  mode; the GDM1 count does not attribute that earlier drop to the FE.
* Three close/open cycles preserved monotonically increasing FE totals;
  repeated reads while down remained unchanged. Unbinding the switch
  then FE, and binding FE then switch, recreated the interfaces and
  restored LAN1/WAN ping without kernel warnings. Reprobe creates a new
  netdevice/statistics lifetime.

Full MIPS RAM-kernel and MIPS/x86_64 MediaTek driver builds passed with
warnings treated as errors. The existing 18 host-side lifecycle checks
also passed. Forced watchdog recovery, sustained counter-wrap stress,
bad Ethernet FCS injection and exhaustive VLAN/PPPoE offload combinations
were not tested in this revision. No MT7620 PPE support was added.

The published candidate is ``mt7620-integration-v3``. The corresponding
``mt7620-ethernet-review-v3`` is seven patches on ``761ae184f850``: four
shared fixes, the binding, frame-engine support, and CPU GDM1 statistics.
It excludes MT7620 PPE, DSA and platform/board support. The RFC draft is
still a draft.

DSA review revision (v4)
------------------------

The ``mt7620-integration-v4`` branch addresses Daniel Golle's three review
comments on the original switch commit. Both MediaTek tag protocols are
now implied rather than selected by NET_DSA_MT7530, so a configuration may
omit the unused protocol. MMIO compatible entries retain alphabetic order.
MT7620 state allocation and syscon/EPHY-reset/IRQ acquisition now occur in
``mt7620_setup()`` before hardware configuration; the shared MMIO probe no
longer calls an MT7620-specific exported initialization helper.

A full MIPS vmlinux/modules build passed with warnings treated as errors,
with only the OOB tagger enabled. An x86_64 build of the MT7530 core, MMIO,
MDIO and ordinary MTK tagger objects passed with the OOB tagger disabled.
Both explicit tagger choices survive olddefconfig. The original hardware
record above belongs to v3; additional v4 RAM results follow below.
The seven-patch Ethernet review subset is unchanged by this DSA-only
follow-up, and MT7620 PPE remains outside it.

V4 RAM validation (2026-09-05)
------------------------------

The image built from ``1fa22db7d645`` was loaded by U-Boot into RAM on the
same WE826-T2 MT7620A ECO6. Its SHA-256 is
``894584e2f128b5fd37bcf4d373f7ca6bf6864e2592f85292203965bec73ccfaf``.
Only NET_DSA_TAG_MTK_OOB was enabled; NET_DSA_TAG_MTK was disabled. The
switch initialized, all five embedded PHYs registered with irq=MAC, and
DSA tree setup completed. Physical traffic used LAN1 and WAN only.

* Eight eight-second IPv4/IPv6 TCP RX/TX runs on LAN1/WAN received
  79.87--80.01 Mbit/s at a requested 80 Mbit/s, with zero retransmissions.
* An eight-second WAN bidirectional run received 79.87/79.74 Mbit/s with
  7/0 retransmissions. Three repeats after FE/switch rebind received
  79.72--80.00 Mbit/s per direction, with 12/0, 1/0 and 4/0 retransmissions.
* To check whether those retransmissions were specific to v4, the retained
  v3 RAM image was then booted on the same bench. Three identical runs
  received 79.73--79.87 Mbit/s per direction, with 7/0, 17/0 and 4/0
  retransmissions. FE, CPU-port and both physical-port error/drop counters
  remained zero during the repeat sets on both revisions. This comparison
  does not identify the cause of the occasional TCP retransmissions.
* At WAN MTU 2030, three UDP packets of each IP length 1500, 1501, 2026
  and 2030 were delivered with no GDM1 length errors. At MTU 1500, only
  length 1500 passed and the larger lengths produced nine length errors.
* The original short ping probe after the second close/open received no
  replies; a later ten-packet probe passed without driver intervention.
  With bounded reachability waiting after reopening, three repeated
  close/open cycles each passed ten pings. FE totals remained monotonic
  and reads while closed remained unchanged. This records a transient
  reachability delay, not a demonstrated persistent driver failure.
* Switch/FE unbind followed by FE/switch bind restored both ports, each
  passing ten pings after reachability returned. The complete dmesg had
  no BUG, WARNING, Oops or refcount diagnostics.

No forced deferred-probe failure or long-duration soak was tested.

DSA architecture review revision (v5)
-------------------------------------

The ``mt7620-integration-v5`` branch addresses the four subsequent review
comments on allocation, duplicate private state, PHY ownership and model
checks. Published v4 history is retained. The tested code revision is
``e4dc39ef2a184bd57b1b60ec29f66943dab72da4``; the following documentation
commit does not change that code.

* The common probe devm-allocates VLAN mapping and per-port counter storage
  in ``mt7530_priv``/``mt7530_port``. The duplicate ``mt7620_switch`` is
  removed. Hardware initialization stays in setup; there is no exported
  MT7620-specific probe helper.
* ``drivers/net/phy/mt7620-ephy.c`` owns the embedded PHY tuning. It uses
  phylib package lifetime and locking, saves/restores MDIO pages, propagates
  errors, and only marks global tuning initialized after success. Package
  identification uses the documented syscon on the internal MDIO node.
  The switch resets the shared PHY block before MDIO enumeration. Binding,
  DTS, Kconfig and the existing MediaTek PHY MAINTAINERS entry are updated.
* Chip register/frame data and MAC, MDIO/IRQ, statistics, VLAN mapping and
  optional traffic-control operations replace the newly introduced model
  conditionals in shared operations. ``ID_MT7620`` remains in chip/match
  tables only. Existing models retain their earlier operations and data.

The source review covered the actual PHY/package/phylink call chains,
MDIO and package lock ordering, IRQ masking before devres teardown,
work cancellation, per-port counter lifetime, and VLAN slot allocation
rollback. This is a source review, not fault-injection evidence.

V5 build coverage
~~~~~~~~~~~~~~~~~

Changed driver objects and the ordinary MTK tagger passed ``W=1``,
``KCFLAGS=-Werror`` and ``C=2`` with sparse ``37156835e3d7`` on six configs:

* MIPS MT7621 little-endian SMP, and MIPS EN7528 big-endian.
* ARMv7 multi_v7_defconfig with MediaTek/Airoha enabled.
* ARM64 defconfig with MediaTek/Airoha enabled.
* x86_64 allmodconfig/allyesconfig-derived configs, explicitly disabling
  the OOB tagger and BTF.

These checks build the MT7530 core, both bus wrappers, ordinary MTK tagger
and MT7620 PHY objects. They are not full kernel/module links or runtime
validation on those other platforms. The full WE826 uImage/modules target
links with ``W=1`` and only the OOB tagger enabled. Unchanged MIPS
traps/math-emu code emitted warnings during an earlier full rebuild;
the changed objects separately passed warnings-as-errors. Switch binding
schema/examples and the eval/WE826 DTBs pass the selected binding checks.

V5 RAM validation (2026-09-05)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The final image SHA-256 is
``3825c74aa0121eaaaf3398c4949e504c9f1aee9c7eee7dc20e7c7b0ef2c17984``.
It booted from RAM on WE826-T2 MT7620A ECO6, with five PHYs bound to the
new driver and irq=MAC. All five observed PHY IDs are ``0x03a2940d``;
this does not establish coverage of other silicon revisions or QFN tuning.
Physical traffic used LAN1 and WAN at 100BASE-T full duplex.

* Eight initial eight-second IPv4/IPv6 TCP RX/TX runs received
  79.88--80.05 Mbit/s at a requested 80 Mbit/s, with no retransmissions.
  The initial WAN bidirectional run received 79.87/79.74 Mbit/s with
  2/0 retransmissions.
* At MTU 2030, three UDP packets of each IP length 1500, 1501, 2026 and
  2030 arrived with no new GDM1 length errors. At MTU 1500, only length
  1500 arrived and the three larger lengths caused nine length errors.
  Length 2031 was not delivered; its earlier drop is not attributed to FE.
* Three close/open cycles preserved FE totals while down and monotonically
  increasing totals after open. Switch/FE unbind followed by FE/switch bind
  restored both links, each passing ten pings, without BUG, WARNING, Oops
  or refcount diagnostics in the captured kernel log.
* Tagged CPU traffic passed five pings at IP MTU 2026. VLAN100 bridge
  forwarding passed twenty pings in each direction with zero FE and CPU
  switch-port counter deltas. Removing the destination port from VLAN100
  blocked all three isolation probes. Fifteen nonzero VLANs filled the
  table; the next VID returned ENOSPC. Deleting one entry allowed a new
  VID, and existing VLAN100 traffic still passed. Switching the bridge
  to VLAN-unaware forwarding passed five pings.
* Customer VIDs 1, 80, 81, 100, 126 and 4094 each passed three CPU pings
  at IP MTU 2026 through the corrected service-tag transport.

Two lab transport problems initially prevented VLAN tests. An outer
802.1Q/inner 802.1Q setup did not preserve the customer tag in that test
path. A direct tagged control reached the CPU correctly; moving the lab
transport to outer 802.1ad allowed ordinary customer VLAN interfaces.
Separately, provider-bridge BPDUs traversed the DUT's VLAN-unaware bridge
and caused the lab switch to mark one test port as an RSTP backup with
forwarding disabled. Disabling RSTP on the lab switch changed the same
three failed probes to five successful probes. The complete VLAN suite
then passed. No kernel change was made during this diagnosis; temporary
register probes were restored before the successful suite.

After the lab corrections, eight more paced TCP runs received
79.87--79.95 Mbit/s with zero retransmissions. Bidirectional TCP received
79.71/79.71 Mbit/s with 6/0 retransmissions. These are short paced tests,
not maximum-rate or loss-free soak results; the occasional bidirectional
retransmissions remain unexplained.

Before an upstream submission, standard-statistics uAPI review (including
previous FE counters), full-tree allmod/allyes validation, wider runtime
and error-path coverage remain outstanding. Only
WE826 ECO6 has runtime evidence here. The separate seven-patch Ethernet
RFC is unchanged and unsent, and MT7620 PPE remains outside its first series.


V6: shared SoC identification (2026-09-08)
------------------------------------------

The code head is ``8c2044391cbf412d16192f47d7ae99c89babc6c2``, based on
v5 ``065e3d4a9c24970198eaefadbd687378e4e2f57c``. This addresses Daniel
Golle's request to centralize model/revision identification in
``drivers/soc/mediatek/``, in comment 199560899 on the PHY commit
``cafded13060f7adf2e3d8fdc3625ad58afda6342``.

``mt7620-socinfo`` registers the existing ``Ralink`` family and
``mt7620a``/``mt7620n`` model IDs, adding decimal ``version.ECO`` revision.
It shares the syscon regmap with the clock/reset driver without binding a
second platform driver to the same device. Its built-in subsys initcall
runs after SoC bus registration and before PHY/Ethernet device initcalls;
the linked MIPS kernels' initcall tables confirm this ordering. Early
architecture setup and the old MT7628/MT7688 registration remain intact;
MT7620A/N no longer get a second registration from arch code.

PHY and Ethernet use ``soc_device_match()`` and fail probe if the model
cannot be identified. The PHY selects the same BGA/QFN tuning values.
Ethernet retains ECO >= 5 TX offloads, matching both single- and
two-digit decimal ECO values. The raw MAC ``chip_rev`` field and the
identity-only FE/MDIO phandles are removed. The switch syscon phandle
remains for operational PHY/pin mode control. No PHY tuning, packet-path
logic or PPE support was changed.

V6 verification
~~~~~~~~~~~~~~~

* Full MIPS vmlinux/modules/DT builds with built-in and modular network
  drivers. Changed objects also pass ``W=1 KCFLAGS=-Werror`` and sparse.
* Changed provider/PHY/Ethernet object builds on ARMv7, ARM64 and x86_64
  allmodconfig/allyesconfig-derived configs. These are object checks,
  not full links or hardware tests on those platforms.
* Existing MIPS Ethernet sparse diagnostics were reproduced on v5 with
  the same configuration; no new diagnostics were introduced by v6.
  The new SoC provider and modified PHY objects emit none. Existing
  full-build MIPS traps/math-emu warnings are outside this change.
* Selected Ethernet/switch binding schemas and examples pass
  ``dt_binding_check``. A/N eval and WE826 DTBs pass the selected
  ``dtbs_check`` validations. A Python jobserver warning occurred without
  schema diagnostics. These are selected-schema checks.
* Host tests compile the actual provider body, consumer tables and kernel
  glob/SoC attribute matcher under ASan/UBSan. All 512 package/version/ECO
  combinations and six discovery/resource-error cases pass, including
  ECO 4/5 and 9/10 boundaries. Kernel resource APIs are mocked; these are
  not hardware fault-injection tests.
* All four code/binding/DTS patches pass strict checkpatch with sign-off
  checking disabled.

V6 RAM results
~~~~~~~~~~~~~~

The WE826-T2 boots Linux 7.3.0-rc1 from RAM with one SoC device reporting
``Ralink``, ``mt7620a``, ``2.6``. All five PHYs bind to the dedicated driver.
TX IPv4/IPv6 checksum, SG, TSO and TSO6 remain enabled.

WAN and LAN1 each pass five IPv4 and five IPv6 pings. Eight eight-second
TCP RX/TX tests across both ports and address families receive
79.88--80.01 Mbit/s at a requested 80 Mbit/s, without retransmissions.
The WAN bidirectional run receives 79.87/79.74 Mbit/s with 7/0
retransmissions. This is a short paced check, not a maximum-rate or
loss-free soak result; the earlier v5 tests also had occasional
bidirectional retransmissions, whose cause is not established here.

Unbinding the switch and FE, then rebinding FE and switch, restores all
PHY ports after init memory has been released. SoC identity and offload
features remain available; both ports again pass five IPv4 and five IPv6
pings. The captured kernel log has no BUG, WARNING, Oops or refcount
diagnostics.

Runtime coverage is MT7620A version 2 ECO6 with built-in drivers. MT7620N,
earlier ECOs, MT7628/MT7688 and runtime module loading are not covered by
this hardware test. No earlier v5 VLAN, jumbo or fault-injection results
are claimed for this revision. The Ethernet RFC needs the shared provider
prerequisite when it is next refreshed; it remains unsent, with PPE
excluded. Subsystem review and the wider upstream validation items above remain
outstanding.

V7: TX VLAN insertion and OpenWrt convergence
-------------------------------------------

Linux changes
~~~~~~~~~~~~~

* Add separate TX VLAN registration callbacks without advertising RX
  filtering. First/last VID references run under RTNL; failed TX
  registration unwinds RX registration. Detached notifications retain
  explicit driver ownership and MMIO checks.
* Enable conduit CTAG TX insertion in the metadata tagger. CDMA slot zero
  remains VID zero; each other slot retains its first VID until removal.
  Aliases and DEI=1 use software insertion. Complete paired MMIO writes
  before publishing the shadow map; restore it on every DMA start.
* Report twelve CPU GDM1 ethtool counters. Sample switch CPU-port MIBs
  every 20 ms and other ports every 200 ms, following OpenWrt's cadence;
  read MMIO before taking the cache lock. Multiple counter wraps during
  worker starvation cannot be reconstructed.
* Limit early DSA metadata allocation to legacy NETSYS, preserving newer
  NETSYS independence from unused metadata allocations.

`OpenWrt PR 24557 <https://github.com/openwrt/openwrt/pull/24557>`_
receives the shared SoC provider, decimal version/ECO matching, ECO >= 5
TX checksum/GSO gating, DEI fallback, FE/rtnetlink counters, RX-checksum
feature handling, early metadata allocation and busy-DMA reset fallback.
Linux receives VLAN insertion and the existing switch-MIB cadence. The
downstream VLAN registration workaround remains local to OpenWrt; the
Linux TX API requires subsystem review.

Validation
~~~~~~~~~~

``tools/testing/mt7620-review/validation-v7.json`` records the tested
source revisions and build/runtime scopes. Portable checks extract the
actual implementation under ASan/UBSan with mocked resource/MMIO APIs:
65536 VID/PCP/DEI combinations, pinned aliases and map restoration, 4000
switch sampling ticks with counter wraps, twelve FE register offsets and
read-clear accumulation, and metadata/PHY/DMA open failures with a newer
NETSYS control. They do not test real ordering or interrupt concurrency.

Full MIPS built-in/modular kernel, module and DTB builds pass. ARMv7 and
ARM64 changed-object builds pass. The x86 allmod/allyes-derived builds
enable OF/COMPILE_TEST and disable BTF/debug information; their results
are recorded separately. Changed objects pass W=1, Werror and sparse.
Bindings/DTS are unchanged from v6's selected-schema checks.

The OpenWrt backport passes native prepare/refresh and full kernel/module
builds; changed FE objects also pass Werror/sparse. On WE826-T2, MT7620A
version 2 ECO6, Linux 6.18.44 with modular FE and DSA:

* 50 IPv4/IPv6 ICMP and bidirectional TCP/UDP checks pass for VIDs
  0/400/401/417/402, with wire-tag verification and CDMA slots 401/402.
* 256 frames preserve mapped/alias VID, all PCP values and both DEI values
  with insertion enabled and disabled.
* Eight VID delete/recreate cycles under traffic and conduit close/open
  preserve the map. DSA user ports are explicitly reopened.
* TSO/RX-checksum toggles, FE/rtnetlink counter growth, cached down-state
  reads and monotonic close/open totals pass.

The author also confirms working OpenWrt operation on D-Link DWR-921 C3
(MT7620N), comparable to MT7620A. The detailed matrix above is from WE826-T2.

These are short paced correctness tests. Linux v7 has not booted on
hardware. Older ECO-specific coverage, other MediaTek runtime, forced
busy-DMA failure and long scheduler stalls remain untested. Standard-statistics
uAPI and the new netdevice/tagger API need subsystem review. The Ethernet
RFC still needs the shared-provider prerequisite; PPE and Wi-Fi remain
outside this transfer.
