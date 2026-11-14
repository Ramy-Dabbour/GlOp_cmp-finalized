# Response to the peer's revised feedback

**Confirmed interpretation, 28 October:** The user has confirmed that the described model is correct: the lattice's realized responses satisfy the half-band identity, while the desired targets need not. All four passband ratios are intended ordinary test cases. The earlier defect diagnosis and label "uncorrected model" are withdrawn. No architecture change is required on this ground. The paper should explain the special structural compatibility at rho=0.5. See [the manuscript wording](C:/Users/Dell/Documents/MATLAB/GlOp_cmp/review/peer-feedback-20261027/PAPER-MODEL-CLARIFICATION.md).

Prepared 27 October 2026. This assesses the feedback pasted into the conversation. The revised outline itself was not supplied; the previously attached Downloads document still contains earlier claims. No scientific source, solver setting, running computation, checkpoint, or original export was changed. The numerical checks below use the frozen reconstructed CSV for global trial IDs 1–4,947 and re-open the nine original exception records.

The revised feedback supports the recoverability of the data and the mathematical characterization of the implemented pipeline. The four-ratio grid is a legitimate set of approximation test cases for the confirmed lattice family. Its structural restriction must be distinguished from optimizer performance, and rho=0.5 should be identified as the case where the raw target shares the half-band identity. Valid returned accuracy and cost remain preferable primary analysis measures to positive solver flags.

**What is confirmed.** There are 4,938 returned valid Stage-2 designs, including 3,896 outcomes excluded by the original success gate. The reconstructed error agrees with the saved successful-trial error to 3.33e-16 in the earlier independent MAT reconstruction. Stage durations are available for every returned stage. This is a substantive defense of saving the full result: revising outcome classification does not require rerunning those 4,938 designs. It cannot recover an unreturned design in the remaining nine cases.

The four-event distinction is sound: whether a result returned; whether it is valid; why the solver terminated; and whether its achieved quality satisfies a stated requirement. A positive termination flag is not interchangeable with an accuracy test or a global-optimality certificate. For example, MathWorks documents that an intentional surrogateopt output-function stop gives -1, while objective-limit termination gives +1. The configured stagnation callback therefore explains why useful surrogate designs were excluded by the original gate. [MathWorks stopping criteria](https://www.mathworks.com/help/gads/surrogate-optimization-options.html)

**The half-band finding needs precise interpretation.** The delay pattern `[2,...,2,1]` and balanced output coupler imply

\[
G(\omega+\pi)=1-G(\omega),\qquad g_0=\tfrac12,\qquad g_{2j}=0\ (j\ne0).
\]

Here g0 is the zero-lag Fourier coefficient, or average power over a frequency period. It does not say that G(0), the response at zero frequency, is necessarily one half. These identities hold algebraically for the ideal model; stored floating-point coefficients obey them to rounding precision.

The previously derived lower bound B(N,rho) and exact decomposition are

\[
D=2\left[\rho^2+(1-\rho)^2+\sum_{k=1}^{N}t_k^2\right],
\qquad
B^2=\frac{4(1/2-\rho)^2+2\sum_{\substack{1\le k\le N\\k\text{ even}}}t_k^2}{D},
\]

\[
E^2=B^2+\frac8D\sum_{\substack{1\le k\le2N+1\\k\text{ odd}}}|g_k-t_k/2|^2,
\]

where tk is extended by zero above N. The first term cannot be changed by the optimizer. The second is the remaining odd-harmonic mismatch, including any restriction imposed by the particular lattice parameterization. Therefore B is a rigorous lower bound, but not automatically an attainable minimum. It must not be called the exact lattice optimum without an attainability argument.

All 4,938 returned designs satisfy this bound; the smallest observed E²−B² in the checked prefix is 0.0008123938828. A reported E near 0.54 can therefore coexist with good optimization: much of its magnitude is forced by the model family. Conversely, subtracting the floor does not make an engineering target physically achievable.

At rho=0.5 the DC/parity restriction agrees with the raw target. That does not guarantee zero error: the truncated target can leave the physical [0,1] range, and the implemented parameterization can impose further restrictions. Across the full N=4..12 grid, the rho=0.2 bound reaches approximately0.54536; the peer's 0.540–0.544 range describes its smaller N=4..10 prefix.

**The new numerical comparisons mostly hold, but one timing number does not reproduce.** The table uses all returned valid designs in IDs1–4947, without a positive-exit-flag filter, grouped by the Stage-2 solver. E is still the final end-to-end error against the original target; seconds are Stage-2 solve durations only.

| Stage-2 solver | Returned designs | Mean final E | Mean seconds | Median seconds |
|---|---:|---:|---:|---:|
| GA | 839 | 0.591366 | 186.46 | 160.18 |
| PSO | 822 | 0.591413 | 663.48 | 321.87 |
| surrogateopt | 820 | 0.591304 | 43.04 | 34.48 |
| simulated annealing | 820 | 0.619588 | 0.759 | 0.618 |
| patternsearch | 820 | 0.591585 | 14.05 | 12.37 |
| paretosearch | 817 | 0.592419 | 90.66 | 84.70 |

The five non-annealing means span only0.00111537, consistent with the stated0.002 observation. Annealing is the sixth solver: it is faster in this sample and has higher mean final error. Similar aggregate means do not establish pointwise equivalence, statistical equivalence, or equal performance across target instances.

The number822 is the count of returned PSO Stage-2 results in this selection. Its mean duration is663.48 seconds, not822 seconds. A different filter could yield a different mean, but it must be specified; the pasted timing claim is not reproduced by this stated selection.

Grouping instead by Stage-1 solver, across all six Stage-2 choices, gives mean final errors GA0.552260, PSO0.551998, patternsearch0.556653, paretosearch0.576343, annealing0.663493, and surrogateopt0.674290. Thus the qualitative reference-quality observation holds. The approximate0.545 figure for GA/PSO needs its aggregation specified: it is close to several individual pair means, but is not the mean across all six Stage-2 solvers. This prefix is unbalanced, especially in its final order, and these summaries are diagnostics rather than estimates of the full factorial comparison.

A useful mechanism follows from the same orthogonal decomposition. For a fixed Stage-1 reference, its DC and even-harmonic mismatch contributes a constant to Stage2's squared fitting objective. Changing those reference coefficients alone cannot change that objective's exact minimizing lattice design, although normalization and stopping tolerances can change finite algorithm behavior. The reference's odd coefficients determine the variable part of the fit. The observed Stage-1 influence is consequently meaningful: it changes the realizable portion of the target supplied to Stage2. It is a reason to study the pipeline, not proof that every two-stage procedure outperforms direct fitting of the original target. Such a superiority claim would need a direct-fitting baseline.

**The two unresolved factual points can be documented locally.** The installed R2026a source dispatches `numberOfObjectives == 1` at line99 of `checkConvergence.m` to `testSinglobjStopping`. That function starts at line162 and assigns `EXITFLAG = 1` at line170 when its feasible archive/mesh stopping condition is satisfied. This establishes an implemented scalar positive-convergence path. It does not show that it was reached in this benchmark; all observed scalar Pareto exits in the prefix remain zero. No additional optimizer run was performed for this check. [Installed source](<C:/Program Files/MATLAB/R2026a/toolbox/globaloptim/+globaloptim/+paretosearch/checkConvergence.m:99>)

The original per-trial JSON records identify five `fpf:TelemetryWrite` file-sharing failures at IDs35,1597,2170,3743,4480 and four `MATLAB:eig:NoConvergence` failures at IDs114,234,594,4585. The verification JSON records each path, message and SHA-256 hash. This is evidence for five distinct affected trials, not a count of duplicate log lines. The peer's four-entry log needs reconciliation against those IDs; I cannot identify its missing entry without its particular log. Instrumentation failures should be separated from scientific numerical exceptions, with their costs and any retries retained rather than silently removed.

The peer's inability to verify cloud statements is reasonable because its scientific archive is not a cloud audit. Separate evidence records the original72-hour timeout, the new launch and export checks, and an actual eight-worker hard-termination/retry test. That test restored ten committed synthetic trials, completed fourteen remaining trials, and verified all24 MAT/sidecar hashes. It is evidence of recovery behavior, not proof that the77,760-trial production run has finished. [Launch verification](C:/Users/Dell/Documents/MATLAB/GlOp_cmp/cloud/replication-20261026/LAUNCH-VERIFICATION.md), [recovery verification](C:/Users/Dell/Documents/MATLAB/GlOp_cmp/cloud/replication-20261026/evidence/recovery-verification.json)

**Decision one, confirmed on 28 October:** Preserve all four ratios as ordinary intended benchmark cases for the existing lattice family. The targets need not share the realization family's half-band identity. Make rho=0.5's structural compatibility explicit in the model and results sections. Explain the unavoidable DC/even-harmonic error contribution for the other ratios without describing those cases as invalid or deviant operating points. The existing data remain relevant to this specified approximation experiment; no architecture change or rerun is justified solely by this distinction.

**Decision two: use outcome-based quality, and retain the original flag as metadata.** The recommended primary outputs are validity/return rates, all valid final E values, the topology bound, remaining squared error E²−B², evaluation counts, durations and termination reasons. Do not condition error and cost distributions only on positive-flag runs. Preserve the original success flag and favorability index in a clearly identified legacy analysis for reproducibility.

The bound and bound-relative measures below apply to the existing, now-confirmed lattice model. Their interpretation and the original success classification remain analysis questions; the presence of non-half-band targets does not itself require a physical-model correction.

For actual engineering acceptability, define

\[
S_{\rm application}=\mathbf1\{\text{complete, valid outcome and }E\le\tau_{N,\rho}\}.
\]

The tolerance should come from a stated application requirement, with additional ripple/attenuation constraints if those are the real requirements. If tau is below the topology bound, zero success is the correct physical finding. No defensible numerical acceptance threshold follows from these data alone.

For a benchmark-specific, topology-aware comparison, report the whole attainment curve

\[
P_{N,\rho}(\varepsilon)=
\frac{\#\{\text{valid completed outcomes with }E^2-B^2\le\varepsilon^2\}}
{\#\{\text{accounted-for logical trials in that comparison}\}}.
\]

At the final analysis, account for every planned trial and show missing/infrastructure/numerical categories explicitly. Pending trials in a live snapshot are pending, not failures. For infrastructure exclusions or retries, state the scientific and operational denominators separately. The condition above means attaining a stated tolerance of a lower bound; it is not equivalent to being within epsilon of a certified optimum. A materially negative E²−B² signals an inconsistency to investigate; only numerical roundoff should be clipped for plotting.

Curves over a disclosed tolerance range avoid selecting one cutoff that favors an observed solver. If one binary headline score is necessary, state the tolerance and rationale before the final comparison, and disclose that the analysis rule was developed after inspecting this prefix. Use matched seed/repetition blocks and per-instance comparisons; retain stage-pair interactions. A best-observed design can be an additional empirical reference, but it is not a certified optimum and it depends on which methods have been sampled.

These changes are analysis changes. The4,938 returned designs can be reclassified directly. They do not require changing the active run or repeating solvers merely to replace the gate. Obtaining designs for the nine unreturned cases, obtaining a complete optimization trajectory that was never logged, or comparing genuinely different budgets would be separate work.

**Suggested reply to the peer, updated on 28 October:** “All four passband ratios are intended ordinary approximation test cases. The lattice realizes half-band responses, but its optimization targets are not required to satisfy that property. We will make rho=0.5's special structural compatibility explicit and report the unavoidable topology contribution for the other targets. The half-band bound does not prove that it is attainable or that a solver has reached its optimum. We will also report valid returned accuracy and cost independently of positive exit flags. The installed R2026a source confirms a scalar paretosearch positive-convergence branch. Original per-trial records identify five telemetry failures and four eigensolver exceptions. For IDs1–4947, PSO has822 returned Stage-2 results, mean duration663.48seconds and median321.87seconds; any other timing figure needs its selection specified.”

Reproducibility: `verify_feedback.py` writes `feedback-verification.json`, including the input hash, precise selection, statistics, exception evidence and installed source hash. This review does not automatically adopt new acceptance rules in production or edit the peer's outline.
