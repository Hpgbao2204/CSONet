# UpgradeGuard: Selective Relational Verification of Solidity Upgrades

This repository is the reproducible research artifact for a CSONet manuscript
on proxy-upgrade safety. It contains a compiler-backed Solidity corpus, a
slot/type/packing compatibility checker, a bounded relational SMT checker,
counterexample generation, Foundry Anvil replay, baselines, ablations, raw
measurements, vector figures, and LaTeX tables.

The prototype is deliberately conservative about its scope. It is a research
artifact for the generated Solidity subset, not a production replacement for
an audit or an unrestricted Solidity verifier.

## One-command reproduction

On Windows PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_all.ps1
```

The command creates every dependency under this repository:

- `.venv/` for Python;
- `node_modules/` for solc-js, OpenZeppelin Upgrades Core, and ethers;
- `.tools/foundry/` for pinned Foundry v1.7.1 binaries;
- `.cache/` for downloads and temporary manifests.

No package is installed globally. Deleting those four ignored directories
removes the complete tool environment without changing user-level settings.

## Artifact at a glance

- 20 original Solidity contracts from 10 families;
- 180 single-mutation upgrade pairs: 60 safe, 60 storage-unsafe, and
  60 behavior-unsafe;
- Transparent/UUPS metadata split evenly;
- compiler artifacts for ABI, AST, bytecode, and storage layout;
- 5,400 raw full-system observations (30 runs per pair);
- 37,800 raw ablation observations;
- OpenZeppelin layout-validation and 128-trial differential baselines;
- 300 controlled scalability observations;
- solver counterexamples with independent summary replay and Foundry Anvil
  EVM/trace replay;
- vector PDF figures and generated LaTeX tables.

The checked-in outputs are tied to seed `26072026` and the configuration in
`configs/experiment.json`.

## Repository map

```text
configs/                    experiment configuration
dataset/
  originals/                20 generated V1 contracts
  pairs/                    V2 source and per-pair ground truth
  artifacts/                solc ABI/AST/bytecode/storage layout
  metadata/                 contracts, pairs, and mutation operators
  results/raw/              per-run and baseline observations
  results/summary/          aggregate statistics and validation reports
  results/figures/          vector PDF plots
  results/tables/           generated LaTeX tables
  scripts/                  generation, validation, experiments, plots
upgradesafe/                layout and relational-analysis implementation
tools/                      Node compiler, OpenZeppelin, and Anvil adapters
main.tex, ref.bib            CSONet manuscript and bibliography
```

See [dataset/README.md](dataset/README.md) for schemas, verdict semantics,
mutation coverage, and limitations.

## Reproducibility checks

The pipeline refuses to report success unless:

1. every V1/V2 source compiles;
2. exactly 20 originals and 180 metadata rows exist;
3. no V2 pair is duplicated for the same V1;
4. source metadata agrees with per-pair ground truth;
5. every indexed compiler artifact exists; and
6. each controlled mutation realizes its expected safety distinction.

The machine-readable outcome is
`dataset/results/summary/validation_report.json`.

## Important limitations

- The behavioral frontend covers the documented generated Solidity fragment;
  unsupported guards produce `Unknown`.
- The dataset is synthetic and controlled. No real-world upgrade pairs are
  claimed in the current artifact.
- The 128-trial baseline is a deterministic bounded differential fuzzer, not
  Forge's built-in fuzzer.
- Foundry Anvil is used for EVM and opcode-trace validation of solver-generated
  counterexamples.
- Inline assembly is handled only for literal `sstore(slot, value)` legacy-slot
  writes; computed namespaces require a stronger points-to analysis.

