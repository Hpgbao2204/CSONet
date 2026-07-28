# UpgradeGuard

UpgradeGuard is a research prototype for analyzing Solidity proxy upgrades. It
combines compiler-derived storage-layout checks with bounded relational
verification of preserved entry points and validates solver witnesses through
independent interpretation and Foundry Anvil replay.

The analyzer is intentionally conservative: unsupported semantics return
`Unknown`, and `Safe` means safe within the encoded model and declared input
domain.

## Artifact

- 20 Solidity contracts across 10 application families;
- 180 controlled upgrade pairs: 60 safe, 60 storage-unsafe, and 60
  behavior-unsafe;
- ABI, AST, bytecode, and storage-layout artifacts produced with solc 0.8.30;
- 5,400 full-configuration and 37,800 ablation measurements;
- OpenZeppelin validation and bounded differential-testing baselines;
- raw CSV/JSON results, aggregate summaries, counterexamples, and replay data.

All recorded outputs use seed `26072026` and
[`configs/experiment.json`](configs/experiment.json).

## Reproduction

Run the complete pipeline from Windows PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_all.ps1
```

Dependencies are installed only under the repository in `.venv/`,
`node_modules/`, `.tools/`, and `.cache/`. No global package installation is
required.

## Repository structure

```text
upgradesafe/             analysis implementation
dataset/originals/       original Solidity contracts
dataset/pairs/           candidate versions and ground truth
dataset/artifacts/       compiler outputs
dataset/metadata/        corpus and mutation indexes
dataset/results/raw/     per-run measurements
dataset/results/summary/ aggregate results and validation reports
dataset/scripts/         dataset and experiment runners
tools/                   compiler, baseline, and Anvil adapters
tests/                   analyzer soundness regression tests
```

Dataset schemas, verdict semantics, and the statistical protocol are documented
in [`dataset/README.md`](dataset/README.md). The artifact is released under the
[`LICENSE`](LICENSE).
