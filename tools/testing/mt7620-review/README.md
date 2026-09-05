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
