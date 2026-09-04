.. SPDX-License-Identifier: GPL-2.0-only

MT7620A/N net-next integration
=============================

This is an integration and hardware-validation tree, based on net-next
``6797f12ea40e788c7da47a7cf9ea4a9341548de0``. It follows Daniel Golle's
recommendation in `OpenWrt PR 24515`_ to integrate the frame engine first,
reuse the MT7530 DSA driver with a separate metadata tag protocol, and
provide a bootable public tree before proposing an Ethernet subset.

Status on 2026-09-04: builds and DT validation pass as described below.
RAM boot, PHY attachment and basic LAN1/WAN traffic have been obtained on
MT7620A ver2 ECO6 with 128 MiB RAM. Detailed validation below distinguishes
completed tests from work still pending.
The available test board is a ZBTlink WE826-T2. Its production OpenWrt
buildtree is kept separate and is not used as a build output directory.
Historical OpenWrt test results are not evidence of this tree's operation.

Architecture and limits
-----------------------

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

IPv4 TX checksum and RX checksum offload are enabled. SG, TSO, TSO6 and IPv6
TX checksum are enabled only for ECO >= 5, following the source Ethernet
work. The frame engine and switch accept frames up to 2048 bytes including
Ethernet header and FCS, giving an untagged MTU ceiling of 2030. VLAN headers
consume part of that frame budget. XDP and hardware VLAN insertion are
outside this initial subset; VLAN frames are handled in software by the FE.

The switch uses 16 VLAN table slots with a separate VID-to-slot mapping.
Slot zero is reserved for VID zero and VLAN-unaware bridging; 15 nonzero
VIDs can be resident at once, including a bridge's default VID 1. Exhaustion
returns ENOSPC. VLAN IDs can span the normal 12-bit range. Shared MT7530
FDB, STP, bridge membership, flooding and mirroring operations are reused.

MT7620 MIBs have a different layout, including packed 16-bit counters.
A 20 ms worker extends counters in software. Sustained scheduling delays
longer than a counter wrap interval can lose wraps; saturation and CPU-port
counter consistency are therefore part of the hardware test plan.
Conduit statistics use software counters, not the later NETSYS MIB layout.

Implementation stages
---------------------

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
STAGING_DIR. Do not run these commands inside a production OpenWrt output
directory. The defconfig has no MTD/block drivers or local initramfs path.

The initramfs needs /init, a shell, mount and diagnostic tools, the ELF
interpreter and all shared libraries if dynamically linked. Include this
line in devices.list so the kernel can open the early console::

    nod /dev/console 0600 0 0 c 5 1

Mount proc, sysfs and devtmpfs in /init. Keep interfaces down until cables
and the test subnet are agreed. Use a serial shell; do not copy production
configuration or credentials. The local candidate uses whitelisted BusyBox,
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
* git diff --check and per-patch checkpatch review. Human DCO sign-off is
  intentionally absent; it must be supplied by a human before submission.
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
------------------------------------------------

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
The FE does not expose the unavailable NETSYS ethtool counter set. Use
rtnetlink software counters and switch MIBs instead.

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
* Lifecycle: FE and switch module reload/unbind only while the serial
  console controls the test; clean IRQ/work teardown, re-probe and traffic.
  Finish with a normal reboot back to the unchanged production firmware.

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

New commits disclose assistance with ``Assisted-by: LLM`` and have no
invented Signed-off-by, Reviewed-by or Tested-by trailers. Follow
Documentation/process/coding-assistants.rst: a human must review the code
and certify DCO before an actual upstream submission. Preparing these
branches and an RFC cover letter does not send a mailing-list submission.

.. _OpenWrt PR 24515: https://github.com/openwrt/openwrt/pull/24515#issuecomment-5546101426
.. _OpenWrt PR 24493: https://github.com/openwrt/openwrt/pull/24493
.. _OpenWrt PR 24557: https://github.com/openwrt/openwrt/pull/24557
.. _MT7620 Programming Guide: https://w.electrodragon.com/w/images/5/51/MT7620_ProgrammingGuide_20121101.pdf
