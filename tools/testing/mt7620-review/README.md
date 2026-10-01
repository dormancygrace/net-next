# MT7620 offline review checks

These are temporary integration-tree review aids, outside the upstream
Ethernet patch series. They execute extracted C functions with mock kernel
APIs and validate a projection of resource constraints from the processed DT
binding. They do not run a kernel, reproduce a physical TX stall, or validate
DMA ordering, interrupt concurrency, or hardware recovery.

Run from a Linux tree with Python 3 and a host C compiler:

```sh
python3 tools/testing/mt7620-review/regression.py drivers/net/ethernet/mediatek/mtk_eth_soc.c
```

To reproduce the original failure, export `mtk_eth_soc.c` from the published
integration commit `4104956dceab` to a temporary file and pass that file instead.
The harness extracts the real watchdog, free/unregister/remove functions,
probe error labels and failed-MAC goto target. Other operations are mocks.
Probe stages model a failed second MAC, IRQ setup failure, PPE/dummy setup
failure, and registration failure after a previously registered MAC opens and
queues recovery. Removal covers open and closed legacy, QDMA and MT7620 MACs.

The recorded original run has 10 failed assertions among 18 checks. Two are
watchdog checks (including an unnecessary status read); four cover failed
probe cleanup and four cover pre-existing non-MT7620 removal problems. The
corrected run passes all 18. These are not ten distinct hardware bugs.

For binding checks, install `dtschema` and its dependencies into an isolated
Python environment and run:

```sh
python3 tools/testing/mt7620-review/binding-regression.py .
```

The script uses the original upstream and integration binding commits from
this repository's history. MT7620's single clock/reset must be accepted;
existing MT7621 reset and RT5350 clock minimum counts must remain enforced.
The original MT7620 binding accidentally accepted the two invalid cases.
This focused check complements `make dt_binding_check`; it is not full board
DTS validation.

Results apply to the code change at `e22091a10e90`. They do not transfer the
previous WE826 RAM-boot results to the new candidate. Additional board tests
are required once hardware is available.


V7 transfer checks (2026-10-01)
-----------------------------

The following scripts compile functions extracted from the current tree
under ASan/UBSan. They run in temporary directories and need Python 3 and
a host C compiler. From the Linux root:

```sh
python3 tools/testing/mt7620-review/vlan-regression.py
python3 tools/testing/mt7620-review/stats-regression.py
python3 tools/testing/mt7620-review/open-regression.py
```

They cover all 65536 VID/PCP/DEI combinations and pinned table ownership,
the actual switch MIB updater/read-clear FE counter branch, and metadata,
PHY and DMA open failures including a newer NETSYS control. Resource,
locking and MMIO APIs are mocked. The checks do not validate real memory
ordering, interrupt concurrency, forced DMA stalls or driver runtime on
other SoCs. `validation-v7.json` records the separate build and downstream
hardware scopes. Linux v7 has not booted on the current bench.
