# Read-only checkpoint audit for the October 24 peer feedback

Audit date: October 26, 2026. No solver was run. No benchmark source, checkpoint, manifest, live telemetry, or benchmark MAT/CSV was changed. The Python audit script reads committed MAT files with SciPy and writes derived review files in this directory.

## Scope and snapshot qualification

The archive originally sent to the peer was not available as an identified immutable archive. I inspected the current immutable checkpoint files and separately selected global IDs 1 through 4,947. That selection exactly reproduces the peer's headline counts: 4,947 records, 1,042 flagged successful, 3,905 flagged unsuccessful, and nine missing Stage-2 results. It also reproduces the reported surrogate and annealing exit-flag counts and the SA-to-SA favorability to the stated precision. This is a matching diagnostic subset, not a claim that I identified the original archive byte for byte.

The current scan contained 5,066 checkpoint files, IDs 1 through 5,067 except 5,065; execution can commit out of order with two workers. The audit froze its list of files at startup rather than inspecting mutable aggregate files. Of those records, 1,047 are successful under the existing gate, 4,019 are not, and 5,057 retain both stage results. Counts below use IDs 1 through 4,947 unless explicitly stated otherwise.

## What was actually saved

| Quantity | Existing summary fields | Full checkpoint result | Verified recovery in the 4,947-record subset |
|---|---|---|---|
| End-to-end error | Written only for `success=true`; otherwise zero | Raw target and realized coefficient matrix retained when Stage 2 returns | 4,938 errors; includes 3,896 unsuccessful trials |
| Total objective evaluations | Written only for `success=true`; otherwise zero | Per-stage function evaluations retained | 4,938 full two-stage totals; Stage-1 counts also exist for the nine exceptions |
| Stage-1 residual | Not a CSV column | `referenceResult.objectiveValue`, target, and optimized vector retained | All 4,947; independent vector-norm recomputation possible |
| Stage-2 residual | Not a CSV column | `mziResult.objectiveValue` and `normalizedFrobeniusError` retained | All 4,938 returned Stage-2 results |
| Stage runtime | Not a CSV column | `metrics.elapsedSeconds` for each returned stage | 4,947 positive finite Stage-1 times and 4,938 positive finite Stage-2 times |
| Whole trial elapsed time | Not a CSV column | Separate live JSON has `elapsed_seconds` | Verified for the nine exceptions; this is measured before durable checkpoint publication |
| Exception information | No explicit CSV breakdown | Failure stage, identifier, and message retained in MAT and readable live JSON | Nine exceptions classified below |

`runCheckpointTrial.m:4-12` explicitly stores the entire result and separately zero-initializes the summary error and evaluations. `runSweep.m:35-43` uses the same success gate for summary measurements. `run.m:51-54` and `run.m:76-84` retain returned stage results before forming success from both validity and positive-exit-flag conditions. Therefore “failed trials have zero summary accuracy” is correct; “there is no end-to-end accuracy recoverable anywhere for those trials” is too strong for these checkpoint files.

Independent Python reconstruction reproduced every successful checkpoint's stored end-to-end error within `3.3306690738754696e-16` and evaluation totals exactly. All 4,938 retained Stage-2 results report `isValidSolution=true`, as do all 4,947 Stage-1 results. The nine exceptions lack a returned final Stage-2 design: their final error and complete Stage-2 cost cannot be invented or recovered from a missing result.

### Examples of unsuccessful but fully measurable trials

| Global ID | Pair | Stage flags | Stored summary E / C | Reconstructed E | Reconstructed C | Stage 1 / Stage 2 seconds |
|---|---|---|---|---:|---:|---:|
| 41 | GA → surrogateopt | 1 / -1 | 0 / 0 | 0.5447290723 | 76,141 | 11.8562 / 25.2574 |
| 101 | GA → paretosearch | 1 / 0 | 0 / 0 | 0.5442710863 | 95,820 | 13.4429 / 64.5935 |
| 241 | surrogateopt → GA | -1 / 1 | 0 / 0 | 0.7190340685 | 19,831 | 3.4554 / 58.4356 |
| 481 | patternsearch → GA | 1 / 0 | 0 / 0 | 0.5478868939 | 23,416 | 0.1449 / 71.2433 |

The first two examples directly show that a nonpositive flag does not establish an inaccurate design. They also show why summary zeros must never be interpreted as zero error or zero work. New post hoc accuracy tables should be separate from the original convergence-gated score, preserving what the original protocol measured.

## Timing: a genuine criticism of the index, but not absent data

The index does exclude elapsed time by definition; it uses `P / E / log(C)` with C defined as objective evaluations (`aggregateFavorability.m:3-8`). Evaluation counts and elapsed time answer different questions, especially for surrogate fitting overhead. That methodological criticism remains valid.

However, the assertion that the inspected run necessarily has NaN times is contradicted by these checkpoint files. `runReportedTrial.m:19` supplies `CollectDiagnostics=liveDirectory~=""`; the local runner has a live directory. `optimizeReference.m:26-35`, `optimizeMzi.m:30-39`, and `extractSolverMetrics.m:30-36` consequently record stage durations. Both times are positive and finite in every result that returned the corresponding stage.

| Solver | Mean Stage-1 evaluations | Mean Stage-1 seconds | Mean Stage-2 evaluations | Mean Stage-2 seconds |
|---|---:|---:|---:|---:|
| GA | 144,447.76 | 34.6703 | 34,213.24 | 186.4594 |
| PSO | 118,008.00 | 27.0269 | 132,306.55 | 663.4769 |
| surrogateopt | 211.36 | 4.1586 | 583.66 | 43.0357 |
| simulated annealing | 147.98 | 0.1277 | 106.86 | 0.7593 |
| patternsearch | 1,385.85 | 0.5512 | 2,436.22 | 14.0451 |
| paretosearch | 20,000.00 | 6.8078 | 20,000.00 | 90.6630 |

These are diagnostics from an incomplete, imbalanced prefix, not published comparative performance estimates. They were recorded on this desktop during parallel execution; they do not establish cloud runtimes or machine-independent computational cost. They are nevertheless available for supplementary cost analysis without repeating trials.

## Exception breakdown

Nine exceptions are `9/4947 = 0.1819%`. Their failure identifiers distinguish two different causes:

| IDs | Count | Identifier | Recorded meaning |
|---|---:|---|---|
| 35, 1597, 2170, 3743, 4480 | 5 | `fpf:TelemetryWrite` | Cannot publish live record because the file is in use by another process |
| 114, 234, 594, 4585 | 4 | `MATLAB:eig:NoConvergence` | “Algorithm did not succeed.” |

All were recorded at the MZI stage. The five telemetry failures are instrumentation failures, not evidence that the optimizer failed mathematically. The four eigenvalue errors are numerical exceptions; these messages alone do not establish their root cause or stack location. The saved live JSON paths and exact messages are in `checkpoint-audit-summary.json`. Treating all nine as a single numerical or optimizer reliability category would be misleading. No failure was rerun or relabeled during this audit.

## Stage-1 residuals, end-to-end error, and the alleged floor

The full result already allows three separate norms to be reported. Let T be the raw target's four-row lag matrix, R the Stage-1 reference matrix, and A the realized lattice matrix, all aligned to the same lag order. Define `a = ||R-T||F / ||T||F`, `b = ||A-R||F / ||T||F`, and `E = ||A-T||F / ||T||F`. Then:

`E^2 = a^2 + b^2 + 2 Re< R-T, A-R >F / ||T||F^2`.

The two residuals generally do not add, and the cross term need not vanish. The triangle bounds are `|a-b| <= E <= a+b`. The actual, approximate Stage-1 residual is not itself a universal lower bound on realized E. A true feasible-set distance can be a lower bound only for the appropriate feasible set and metric. The Stage-1 objective uses an unweighted cosine-vector norm, while the end-to-end metric uses a differently weighted lag representation; equating those numbers would be incorrect.

Trial 1 demonstrates the scale difference: Stage-1's own normalized vector objective is 0.15894302096; its residual in the end-to-end metric is 0.09189739973; Stage-2's residual with the common raw-target denominator is 0.50577792100; the cross term is 0.03256065141; E is 0.54480922244. Its stored Stage-2 objective, with the Stage-1 target denominator, is 0.52919785878.

Across the diagnostic subset, mean Stage-1 own objectives are GA 0.136936, PSO 0.132950, surrogateopt 0.877549, annealing 1.026708, patternsearch 0.218260, paretosearch 0.401581. Their mean corresponding common-metric residuals are approximately 0.082669, 0.079953, 0.527301, 0.702203, 0.136885, and 0.254255. The actual Stage-1 choice therefore still matters, but a single Stage-1 floor explanation is not demonstrated by the snapshot.

Independent of a theoretical proof of the model, the entire current sample of 5,057 retained Stage-2 coefficient matrices has DC 0.5 in every row to a maximum deviation of `8.881784197001252e-16`; all even positive-lag coefficients have magnitude at most `1.790229612425054e-16`. This strongly supports the independently derived half-band restriction. For rho=0.2 the target does not share those coefficients, providing a model-family explanation for much of the observed E. This audit does not change that model.

## Convergence-gated score verification

The recovered prefix reproduces surrogateopt's Stage-1 flags `-1` in 840/840 and Stage-2 flags `-1` in 820/820. paretosearch uses exactly 20,000 evaluations and exits 0 in all returned Stage-1 and Stage-2 results. Annealing exits 1 for every returned stage. In Stage 2, GA has 33 positive flags out of 839 results (3.93%), PSO 733/822 (89.17%), and patternsearch 8/820 (0.98%). These support the peer's core objection about interpreting native stop flags as interchangeable outcome criteria.

There are 20 pairs involving surrogateopt or paretosearch and none has a positive gated success count here. There are actually 21 zero-score pairs in the matching prefix: PSO → patternsearch additionally has no successful trial in this sample. The latter is a finite-sample observation, distinct from the mechanism excluding the other 20.

SA → SA reproduces `P=1`, successful-trial mean `E=0.6770421873678284`, mean `C=246.36428571428573`, and `F=0.26821562604921756`. That number is correct for the implemented formula; it does not establish that annealing returned the most accurate designs. Full post hoc accuracy is now recoverable for all 36 pairs with returned Stage-2 results.

## Review artifacts

- `audit_checkpoint_data.py`: reproducible read-only MAT reconstruction.
- `checkpoint-reconstruction.csv`: one derived row per currently captured checkpoint; successful and unsuccessful outputs are distinguished explicitly.
- `checkpoint-audit-summary.json`: both subset definitions, per-solver exit flags and time/evaluation statistics, pair scores, examples, and exact exception evidence.

These files supplement the original benchmark outputs. They do not overwrite or silently redefine them.
