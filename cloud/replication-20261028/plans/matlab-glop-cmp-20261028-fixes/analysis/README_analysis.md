# fpf_analysis: outcome-based analysis of GlOp_cmp trials

This is a separate Python script. It does not touch the MATLAB program, so the
source-hash resume guard is unaffected and no rerun is needed.

## What it reads

The per-trial records the program already writes, from any mix of:

- local live records: `local-results/live/<attempt>/trials/trial_*.json`
- cloud live history: `outputs/<JOB_ID>/live/tasks/*/trials/*.jsonl.gz` (copy it down first,
  for example `gsutil -m cp -r gs://BUCKET/outputs/JOB_ID/live ./cloud_live`)
- MAT checkpoints, optionally, as a cross-check only (`--checkpoints`)

The merged final MAT shards are not enough: they keep only the legacy arrays.

## Run

    python fpf_analysis.py local-results/live cloud_live --out results \
        --plan analysis_plan.json --expect-trials 77760 \
        --checkpoints local-results/checkpoints

Needs Python 3.9+, numpy, pandas and scipy. Add `--allow-partial` for interim looks
(a short trial count then prints WARN instead of FAIL). Duplicate global trial IDs stop the
run; pass `--duplicates first` or `--duplicates last` once you have decided which attempt
is authoritative. The exit code is 1 if any check fails.

## What it writes (in `--out`)

| File | Content |
|---|---|
| `validation_report.txt` | every check, PASS / FAIL / INFO, with the script and plan hashes |
| `pair_summary.csv` | per pair: legacy P, F and exit-flag success; P(tau), expected cost per success (evaluations and seconds) at each tau; the same against the best E in the instance; failure counts |
| `pair_bootstrap_ci.csv` | 95% block-bootstrap intervals for P(tau) and cost per success |
| `tolerance_profiles.csv` | P and cost per success on a fine tau grid (for the P-against-tau figure) |
| `stage_summary.csv` | per solver and stage: cost, exit-flag counts, Stage-1 gap to the convex bound, Stage-2 gap to the best solver sharing the same reference |
| `cell_attainability.csv` | per (order, ratio, seed): the half-band bound, best and median E |
| `stage1_convex_baseline.csv` | convex Stage-1 optimum per (order, ratio): lower bound and feasible upper bound |
| `exceptions.csv` | every trial with no Stage-2 result or a failure identifier |
| `trial_table.csv` | one row per trial with everything above, for any further analysis |
| `analysis_plan_used.json` | the plan that produced the tables |

## Definitions

- Success at a rung of the delta ladder: both stages valid and delta <= 10^(dB/20), where
  delta = sqrt(E^2 - E_bound^2) is the part of E the solvers control (E^2 = E_bound^2 + delta^2 exactly).
  The default ladder is -20 to -60 dB in 5 dB steps (main-text subset: every 10 dB). The E-excess and best-in-instance criteria are secondary.
- Cost per success: total evaluations (or seconds) over all trials of the pair, failures
  included, divided by the number of successes.
- Legacy: P over all trials, mean E and mean total evaluations over trials where both exit
  flags are positive and both stages are valid; F = P / (mean E * ln mean C).
- Block bootstrap: blocks are (seed, repeat), resampled across all orders and ratios, with the
  same resampled blocks used for every pair, so differences between pairs stay paired.

## Checks the script runs

1. Recomputed E equals the program's saved E (tolerance 1e-12).
2. No E below its half-band bound.
3. DC equals 1/2 and every even-lag coefficient is zero on every returned matrix.
4. MAT checkpoints agree with the recomputed values on successes (if supplied).
5. No Stage-1 result beats the convex lower bound.
6. Unique IDs and coverage against `--expect-trials`.

## Fix the plan before opening the full data

`analysis_plan.json` holds the tau lists. Edit it, then do not change it after you
have looked at the full-run tables; anything added later is exploratory. The current grid was
fixed a priori as a 5 dB ladder on delta. Only the step size was set after the 4,947-trial snapshot (rho = 0.2, seed 0, orders 4 to 10 only), and the plan records that.

## Things this does not settle

- Tested here on the 4,947 local records and on a synthetic JSONL.gz built from them. It has
  not seen a real cloud file, so the first cloud run may need a loader tweak; the schema it
  expects is the one in `cloud/README.md`.
- The Stage-1 baseline is an SLSQP solve on a 4,001-point grid. The grid solution is a lower
  bound; it is shifted toward x = [0.5, 0, ..., 0] until the program's own continuous
  feasibility test passes, which gives an upper bound. The two agree to under 1e-6 here.
- The half-band bound is derived for this lattice (stage delays [2,...,2,1] and a fixed balanced
  output coupler). If the lattice changes, the bound and the identity checks must be redone.
- Exceptions: `MATLAB:eig:NoConvergence` occurs inside the Stage-2 objective (the extrema test
  calls `roots`), and the objective has no guard, so one bad candidate ends the whole trial.
  It is counted as a failure. `fpf:TelemetryWrite` is a Windows file-lock error while saving
  the live record, not a solver result. It is counted as a failure in the main columns and
  excluded in the `_P_exclinfra` sensitivity columns.
