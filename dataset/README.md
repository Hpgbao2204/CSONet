# Dataset and experiment protocol

## Composition

The corpus contains two contracts from each family: token, vault, staking,
voting, registry, access control, escrow, crowdfunding, marketplace, and
reward distribution. Each original has 7--8 public/external functions, eight
compiler-visible storage variables (including inherited state), events,
owner-based access control, a mapping, and either a dynamic array or a storage
gap. Proxy metadata alternates between Transparent and UUPS.

Each V1 has nine V2 variants and every V2 contains one primary mutation:

- three safe mutations;
- three storage-unsafe mutations;
- three behavior-unsafe mutations.

Generation is deterministic. Before writing, the generator deletes only the
resolved `dataset/originals` and `dataset/pairs` directories, preventing stale
pairs from surviving across configuration changes.

## Metadata

`metadata/pairs.csv` is the authoritative index. Its core fields are:

```text
pair_id, contract_name, contract_family, proxy_type,
v1_path, v2_path, expected_verdict, safety_category,
mutation_operator, changed_function, changed_variable, affected_slot,
compiler_version, LOC, number_of_functions,
number_of_storage_variables, number_of_branches, external_call_count
```

Every pair also has `ground_truth.json`. `affected_slot` is resolved from the
compiler layout during validation rather than guessed by the generator.

## Verdict semantics

- `Safe`: layout compatibility holds and the negated relational obligation is
  unsatisfiable for every changed preserved function in the supported domain.
- `Unsafe`: a layout violation exists or the solver finds an observational
  difference.
- `Unknown`: the source uses an unsupported construct or another analysis
  failure prevents a proof.
- `Timeout`: the solver returns `unknown` because the configured limit expires.

An observable behavior is the tuple of success/revert status, return or revert
data, events, related post-storage, and external-call/effect trace.

## Raw outputs

`results/raw/full_results.csv` has one row per pair and measured run. Timings
are split into artifact extraction, storage analysis, function mapping,
product-program/solver, counterexample replay, and total time. It also records
memory, constraints, symbolic paths, complexity covariates, issues, and the
counterexample.

`results/raw/ablation_results.csv` contains 30 runs for:

```text
Full, NoBehavior, NoStorageType, NameOnly, SlotOffsetType,
NoReplay, NoSkipUnchanged
```

`results/raw/scalability_results.csv` contains 30 observations for batches of
one through ten relational obligations. This is a controlled workload study,
not a claim that one V2 contains ten independent mutations.

`results/raw/fuzz_budget_sweep.csv` contains 480 observations for deterministic
trial budgets 16, 32, 64, and 128. It is retained as a supplementary
sensitivity result even though the final four-figure paper layout does not
use a budget panel.

The figure generator emits thirteen independent square vector PDFs. The first
experimental figure assembles storage panels 1a--1d and behavior panels 2a--2d
in a two-by-four layout. The second combines the obligation and symbolic-path
scalability panels. The third assembles three matched ablation panels in one
row. All panels use 21-point Matplotlib-default typography.

Panels 1a, 1b, 2d, and 3a--3c connect Jeffreys posterior estimates or measured
timing summaries using shape-preserving cubic profiles. The
interpolation is only a visual guide and cannot overshoot the marked range.
The three diagnostic panels use an identical square canvas, configuration
order, one-column upper-right legend, and paired-curve grammar. Timing densities
use Gaussian KDE with Scott's bandwidth. The generator never changes a
measured value or categorical outcome.

## Statistical protocol

The runner performs three warm-up passes and thirty measured passes. It reports
median, IQR, and p95. Classification summaries retain TP, TN, FP, FN,
precision, recall, F1, FPR, FNR, unknown rate, timeout rate, and accuracy.
Plots read only checked-in CSV files.

## Compiler warnings

Four behavior-unsafe `omit_state_update` variants intentionally leave the
computed local `next` unused. solc reports warnings, not errors; the warnings
are retained in `results/raw/compile_result.json`.
