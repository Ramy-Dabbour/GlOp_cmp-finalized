# Assessment of the paper feedback and the benchmark's validity

**Confirmed interpretation, 28 October:** The user has confirmed the described model: a half-band realization family approximates targets that need not be half-band. All four passband ratios are ordinary intended test cases, with rho=0.5 structurally special. The intervening diagnosis of an implementation/specification defect is withdrawn. The mathematical audit remains applicable; its topology bound explains an inherent component of the specified approximation error. See [the manuscript clarification](C:/Users/Dell/Documents/MATLAB/GlOp_cmp/review/peer-feedback-20261027/PAPER-MODEL-CLARIFICATION.md).

Prepared October 26, 2026 from the attached feedback, the current MATLAB source, immutable saved trial checkpoints, installed R2026a solver code, and independent numerical checks. The attached document is being evaluated as peer feedback; its proposed manuscript instructions are not treated as instructions to execute or as verified facts.

The two-stage experiment has a defensible mathematical and experimental structure. Several criticisms correctly identify limits on what the current score means. Other criticisms incorrectly infer that information was lost because a summary field is zero. A further restriction in the implemented optical topology explains much of the observed error and needs explicit treatment in the paper.

The earlier cloud termination was caused by the configured 72-hour MATLAB runnable timeout. That was a deployment configuration failure. It does not establish that the mathematical experiment is invalid, but it makes durable result storage and restart essential for its replication.

**What was checked.** I inspected the source and audited 5,066 immutable local checkpoint files. The subset with global IDs 1–4,947 reproduces the peer's 1,042 positive-flag successes and 3,905 nonsuccesses. This is strong correspondence with the reported snapshot, although I have not independently opened the exact archive the peer received. Scientific quantities below are diagnostics from that incomplete prefix, not final benchmark conclusions. No optimizer trials were rerun for this audit. The MATLAB static-analysis connector could not attach to a MATLAB session; validation here consists of source inspection, reconstruction from existing data, and separately implemented numerical checks.

| Check on IDs 1–4,947 | Verified finding |
|---|---:|
| Trials meeting the legacy success rule | 1,042 |
| Trials not meeting that rule | 3,905 |
| Trials with a recoverable final design, end-to-end error and total evaluation count | 4,938 |
| Nonsuccesses with recoverable final error and count | 3,896 |
| Trials without a returned Stage-2 result | 9 |
| Finite saved Stage-1 elapsed times | 4,947 |
| Finite saved Stage-2 elapsed times | 4,938 |
| Largest difference between reconstructed and saved successful-trial error | 3.33 × 10⁻¹⁶ |
| Difference in reconstructed successful-trial evaluation counts | 0 |

See [checkpoint audit](C:/Users/Dell/Documents/MATLAB/GlOp_cmp/review/peer-feedback-20261026/CHECKPOINT-AUDIT.md), [reconstructed trial data](C:/Users/Dell/Documents/MATLAB/GlOp_cmp/review/peer-feedback-20261026/checkpoint-reconstruction.csv), and [mathematical audit](C:/Users/Dell/Documents/MATLAB/GlOp_cmp/review/paper-feedback-20261026/MATHEMATICAL-AUDIT.md).

**1. What is valid about the program structure.** The program defines an intelligible sequential design procedure. Stage 1 adjusts a truncated ideal-low-pass cosine series to satisfy a power bound. Stage 2 adjusts physical lattice parameters to approximate that reference. A common final error evaluates the realized lattice against the original target. Comparing all 36 ordered pairs is a legitimate way to investigate how the reference-generation method affects subsequent fitting.

The Stage-2 matrix construction is physically meaningful for the ideal lossless model. Each coupler uses T = cos(2πθ), K = sin(2πθ), so T² + K² = 1. Its phase and delay factors have unit magnitude on the unit circle. Products of these unitary matrices remain unitary. This explains complementary power responses and bounded transmitted power. It does not establish that every bounded target is representable by the particular cascade.

The final metric also has a sound basis. It compares aligned Laurent-polynomial coefficients of all four power responses, including the higher harmonics of the realized network. By Parseval's identity, the squared coefficient norm equals the corresponding integrated squared frequency-response error, up to a common normalization factor that cancels in the ratio. It is therefore a legitimate spectrum-wide error measure without a frequency sampling grid. It is not a maximum ripple, stopband attenuation, or field-phase error, and the manuscript should not describe it as those quantities.

The experiment's randomization is another strength: each stage resets a deterministic substream, so the first solver's random-number consumption cannot change the second stage's assigned starting randomness. The full checkpoint records make the analysis auditable. These strengths survive the criticisms of the success gate.

The defensible overall claim is a comparison of **these six configured solver implementations, paired across this two-stage procedure, for this target and lattice family**. An intrinsic, universally applicable ranking of six optimization algorithms would require stronger evidence.

**2. Issues 1 and 2: a positive exit flag is a termination category, not a common accuracy standard.** The code in [extractSolverMetrics.m](C:/Users/Dell/Documents/MATLAB/GlOp_cmp/+fpf/extractSolverMetrics.m:35) sets `converged = exitFlag > 0`. [run.m](C:/Users/Dell/Documents/MATLAB/GlOp_cmp/+fpf/run.m:82) then requires both stages to be valid and both flags to be positive. That is an explicit, reproducible operational rule. It does not ask whether the final optical response is accurate enough.

Four events need separate names: a solver returned; its output is valid; it met its own convergence test; and its achieved error is acceptable. They need not coincide. Budget exhaustion can return an excellent design. Stagnation can return a mediocre design. An exception can return no design at all.

The surrogate configuration contains a specific inconsistency with this gate. It stops after 200 evaluations without sufficient improvement through an output callback. MATLAB reports such an intentional callback stop as −1. Other solvers can report their native stagnation stop as +1. Thus similar practical events receive opposite success classifications. The callback is not evidence that the optimization crashed. Its reason should be recorded separately. [MathWorks surrogate options](https://www.mathworks.com/help/gads/surrogate-optimization-options.html)

Surrogate optimization also has an ObjectiveLimit of 10⁻¹⁰. For a problem whose minimum objective exceeds that value, reaching the target is impossible; budget and callback stops then dominate. This is particularly problematic when Stage 1 intentionally projects an inadmissible raw target and necessarily has a nonzero residual. A stopping rule tied to virtually zero residual is poorly aligned with such an approximation task.

The peer overstates the case for Pareto search. The installed R2026a implementation explicitly supports a scalar objective and has a single-objective convergence branch. [checkConvergence.m](<C:/Program Files/MATLAB/R2026a/toolbox/globaloptim/+globaloptim/+paretosearch/checkConvergence.m:94>) dispatches scalar versus multiobjective logic; its scalar branch at line 162 can return +1 after the relevant mesh convergence condition. Therefore scalar use is supported, and a positive flag is possible. The observed 20,000-evaluation exits describe this configuration and snapshot; they do not prove that the solver is structurally incapable of convergence. Public documentation also distinguishes convergence from budget exhaustion. [paretosearch reference](https://www.mathworks.com/help/gads/paretosearch.html)

Two solvers having zero accepted outcomes removes their union of rows and columns from the 6×6 score matrix: 36 − 4² = 20 pairs. In the reconstructed prefix there is an additional zero-success pair, PSO→patternsearch. This is an observation about the current score, not proof that those pairs cannot produce useful designs.

A direct counterexample is already saved. These three trials use the same N = 4, ρ = 0.2, seed and repetition, and the same GA reference result:

| Trial | Pair | Stage-2 flag | Legacy success | Reconstructed final E | Total objective evaluations |
|---|---|---:|---|---:|---:|
| 1 | GA → GA | +1 | Yes | 0.54480922 | 97,150 |
| 41 | GA → surrogateopt | −1 | No | 0.54472907 | 76,141 |
| 101 | GA → paretosearch | 0 | No | 0.54427109 | 95,820 |

The two rejected trials have slightly lower error than the accepted trial. This does not establish a solver ranking from three observations. It decisively shows that the existing binary flag is not an accuracy indicator.

My recommendation is to preserve the existing flag-based score as a reproducible legacy measure and add separate outcome measures. Record every finite valid final error, every stage count and duration, and the precise termination reason. Define engineering acceptability using a stated tolerance when an application supplies one. For benchmarking without such a specification, report accuracy-versus-budget behavior or gap to a clearly identified reference bound. A best-observed value is an empirical reference, not a certified optimum; tolerances chosen after seeing results must be disclosed as exploratory. Merely recoding the surrogate callback as a success would explain its intent but would not make all solvers' success criteria comparable.

**3. Issue 3: the summaries omit nonsuccess accuracy, but the checkpointed program retained it.** The peer correctly identifies the conditional assignments in [runSweep.m](C:/Users/Dell/Documents/MATLAB/GlOp_cmp/+fpf/runSweep.m:35) and [runCheckpointTrial.m](C:/Users/Dell/Documents/MATLAB/GlOp_cmp/+fpf/runCheckpointTrial.m:4). The top-level error and evaluation fields remain zero when the success flag is false. These zeros exist to support sums conditional on success; they must never be interpreted as observed perfect error or zero computational expense.

However, the checkpoint also stores the entire `result` structure. That includes the raw target, optimized reference, returned lattice coefficients, solver outputs, and metrics whenever those stages returned. Furthermore, [runReportedTrial.m](C:/Users/Dell/Documents/MATLAB/GlOp_cmp/+fpf/runReportedTrial.m:20) computes telemetry error whenever a realized coefficient matrix exists, independently of the success flag.

I reconstructed final error and count for 3,896 of the 3,905 nonsuccess trials in the matching prefix. Thus the strong claim that their accuracy information is unavailable anywhere is not supported by these saved files. The repair is mainly an analysis/export repair: expose observed quantities for every usable result, use missing values for quantities that genuinely do not exist, and keep outcome classification separate. The scientific computation does not need to be repeated merely to obtain those errors.

This is a substantial defense of the modified desktop program: it retained the scientific objects needed to reassess its scoring rule. It does not defend the misleading zero placeholders in a flat export; those should be labeled or replaced in a new, explicitly versioned analysis table.

**4. Issue 4: feasible initialization is a valid design choice.** The initializer samples DC d in (0,1) and nonconstant cosine coefficients with sum of absolute values at most min(d,1−d). For every frequency,

\[
\left|\sum_{k=1}^{N}x_k\cos(k\omega)\right|\le\sum_{k=1}^{N}|x_k|\le\min(d,1-d),
\]

so the initial response lies in [0,1]. This proof is valid. Feasible starts remove a severe nuisance from a flat-penalty formulation: a solver no longer has to find a narrow feasible region before it receives informative objective values. It is reasonable to study refinement from a common feasible-start distribution.

The limitation is interpretive. A high Stage-1 validity rate is no longer evidence of superior feasibility discovery. This protocol differs from an earlier infeasible-start experiment and should be reported separately. Initial feasibility also does not certify every candidate generated later or every numerical return.

The distribution should be described precisely: DC is uniform, and conditional on DC the remaining coefficients are uniform in the corresponding L1 ball, up to a roundoff margin. It is not uniform over the entire admissible set, nor uniform over the combined variable-radius region. Cross-sectional volume depends on DC. This intentional shared distribution is defensible; claims of unbiased sampling of all feasible filters are not.

**5. Issue 5: evaluation count is useful, but timing is already available.** Function evaluations measure calls to the declared objective. They are reproducible accounting units and useful when objective evaluation is the dominant cost. They are not elapsed compute time: different solver overheads, different stage objectives, and different orders change work per evaluation.

The peer is right that surrogate model construction can make evaluations an incomplete cost measure. It would be unjustified to conclude that 100 times fewer evaluations necessarily means 100 times faster. The benchmark should report both counts and durations, and distinguish time spent on unsuccessful attempts from time on accepted outcomes.

The statement that timing is absent needs correction for the saved run. Live reporting enables `CollectDiagnostics`; all 4,947 Stage-1 results and all 4,938 returned Stage-2 results in the matching prefix contain finite elapsed times. Trial telemetry also records overall elapsed time. For trial 41, the stage times are 11.8562 and 25.2574 seconds. The wrapper can produce NaN timings when diagnostics are disabled, but that conditional code path is not evidence that this run's timing was missing.

Wall-clock comparisons still require care: these are concurrent runs on one device, and OS load, worker count, logging, and platform affect them. Report hardware and concurrency and avoid treating them as isolated-machine timing experiments.

**6. The favorability index is a coherent utility function with a limited interpretation.** The implementation uses

\[
\mathcal F=P/(\bar E\ln\bar C),
\]

where P is computed over all scheduled outcomes in the relevant completed set, while E and C are averaged only over accepted successes. The formula is explicit and monotone in the intended directions: higher P, lower positive E, and lower C > 1 improve the score. A logarithm deliberately compresses large evaluation-count differences. Changing the logarithm's base multiplies all scores by a common constant, so it cannot change their ordering.

SA→SA ranking highly despite worse error is not an arithmetic contradiction. It means the chosen utility rewards its combination of accepted stopping behavior and low cost enough to offset that error. It would be wrong to translate that directly into “most accurate” or “best optical design.”

The logarithmic sensitivity is

\[
d\ln\mathcal F=d\ln P-d\ln\bar E-\frac{d\ln\bar C}{\ln\bar C}.
\]

This makes the preference tradeoff explicit. Other limitations are substantial: the gate determines which observations enter E and C; pairs can be averaged over different, selectively easy instances; a few accepted outcomes produce unstable means; and expensive failed runs do not increase the conditional C. This C is not expected total compute per acceptable design.

Retain the score with its original definition for auditability, but display P, E, C, wall time, failure expense, and nondominated alternatives alongside it. Check whether the substantive conclusions survive reasonable success definitions and scalarizations. Performance profiles are an established complementary presentation, provided the performance target and cost accounting are comparable. [Dolan and Moré](https://doi.org/10.1007/s101070100263)

**7. Issue 8: Stage 1 is convex; that does not invalidate comparing search methods there.** For every fixed ω, the response F(ω;x) is linear in x. The inequalities 0 ≤ F ≤ 1 define half-spaces; intersecting them over all frequencies and with the coefficient box gives a closed convex feasible set. It is nonempty, for example at a constant response. The objective is a normalized Euclidean distance to a fixed target. Squaring that distance preserves its minimizer and gives a strictly convex quadratic objective. Hence the nearest feasible coefficient vector is unique. This is a projection problem, not a problem that fundamentally requires global stochastic search. [Boyd and Vandenberghe](https://www.stanford.edu/~boyd/cvxbook/bv_cvxbook.pdf)

The legitimate defense is experimental: one can deliberately compare derivative-free black-box methods on a structured problem and study how their imperfect outputs affect a later nonconvex stage. A certified or tightly bounded convex baseline would make that experiment stronger. It should not be presented as a proof that a global optimizer is necessary or that no direct formulation exists.

The current objective implementation also changes what the algorithms experience. It hides the continuous constraints behind a `realmax` penalty rather than giving them explicit linear/semi-infinite constraints. The underlying feasible optimization problem is convex; the finite penalty wrapper has a discontinuity at the boundary and can be numerically difficult. Using a nearly maximum double can be particularly awkward for methods that fit models or subtract objective values. That is a property of the formulation-plus-solver combination, not proof of intrinsic algorithm weakness.

The peer's proposed “exact convex optimum” needs qualification. A dense-grid quadratic program enforces only its sampled constraints, so its optimal value is generally a relaxation bound until continuous feasibility is checked. An exchange procedure can add violating extrema; a suitable nonnegative-polynomial/semidefinite formulation can represent the continuous constraints. Numerical solvers still have tolerances. Report primal feasibility, objective bounds or gaps, and numerical precision rather than calling an unchecked grid answer exact.

Likewise, the current feasibility test is analytically exhaustive in its idea—endpoints and all relevant stationary points—but the implementation uses floating-point polynomial roots and root filtering. It is more precise to say “continuous-domain extrema test implemented numerically” than “certified exact test.” Dense-grid agreement is a useful diagnostic, not a proof that narrow violations are impossible.

**8. Issue 6: residuals do not simply add, and Stage 1's objective is not the final error's floor.** If T denotes the raw-target coefficient matrix, R the Stage-1 reference matrix, and A the realized matrix, then

\[
\|A-T\|_F^2=\|R-T\|_F^2+\|A-R\|_F^2+
2\operatorname{Re}\langle R-T,A-R\rangle_F.
\]

The cross term can be positive or negative. A poor intermediate reference can sometimes be partly corrected by the restricted second-stage family. One cannot write final error as Stage-1 error plus Stage-2 error, or assume the actual Stage-1 residual is a lower bound for every final design.

There is also a metric mismatch. A cosine vector x maps to complex lag coefficients L(x) with DC x₀ and positive/negative coefficients x_k/2. Therefore

\[
\|L(x)-L(t)\|_2^2=(x_0-t_0)^2+\tfrac12\sum_{k=1}^{N}(x_k-t_k)^2.
\]

Stage 1 instead minimizes the unweighted cosine-vector distance. Its denominator is also different from the four-response end-to-end denominator. Its optimum is therefore not automatically the exact minimum of E.

Finally, the realized network can contain harmonics through order 2N+1, while Stage 1 uses reference order N. A projection restricted to degree N is not automatically a lower bound for optimization over a larger degree space. A valid lower bound must use the same error metric and a feasible set that contains the realized family. These qualifications matter even before the additional topology restriction below.

**9. The central additional finding: this implementation is a half-band lattice.** [mziSMatrixCoefficients.m](C:/Users/Dell/Documents/MATLAB/GlOp_cmp/+fpf/mziSMatrixCoefficients.m:18) uses stage delays [2,…,2,1] followed by a fixed balanced coupler at line 34. This gives a stronger constraint than losslessness alone:

\[
R(\omega+\pi)=1-R(\omega),\qquad g_0=\tfrac12,\qquad g_{2k}=0\quad(k\ne0).
\]

Here R is a port power response and g its complex Fourier/lag coefficients. Its mean is one half and every nonconstant even harmonic vanishes. This matches the half-band family associated with the cited optical-filter literature; it does not establish that the intended target family was chosen correctly. [Jinguji and Oguma, Optical Half-Band Filters](https://opg.optica.org/jlt/abstract.cfm?uri=jlt-18-2-252)

A short proof comes directly from the code. All stages before the final one depend only on z². Absorb the last tunable coupler into a unitary matrix B(z²). Multiplying B(z²) by diag(z,1) and the fixed balanced coupler makes each output field a sum of an even polynomial and z times an even polynomial. The sum of their squared magnitudes contributes 1/2 by unitarity; their cross term contains only odd harmonics. Replacing z by −z changes that cross term's sign, giving the half-band identity. Phase factors do not remove the even/odd distinction.

This was checked independently with 108 random designs and against every one of the 5,057 returned Stage-2 matrices in the current checkpoint set. The largest saved-matrix DC deviation from 1/2 was 8.88×10⁻¹⁶; the largest even positive-lag coefficient magnitude was 1.79×10⁻¹⁶. These numerical checks support the algebraic proof; they are not substitutes for it.

The raw target has t₀=ρ. Thus ρ=.2, .3 and .4 specify a mean that this lattice cannot attain. They also generally contain nonzero even harmonics that it cannot realize. At ρ=.5 those particular restrictions match, although truncation ripple and the restricted parameterization can still prevent exact realization.

There is a calculable lower bound in the program's actual E metric. Put

\[
D=2\left[\rho^2+(1-\rho)^2+\sum_{k=1}^{N}t_k^2\right].
\]

Every realized design obeys

\[
E\ge E_{\rm topology}=
\sqrt{\frac{4(1/2-\rho)^2+2\sum_{2\mid k,\,1\le k\le N}t_k^2}{D}}.
\]

| Reference order N | ρ=.2 | ρ=.3 | ρ=.4 | ρ=.5 |
|---:|---:|---:|---:|---:|
| 4 | .540121 | .435775 | .284884 | 0 |
| 10 | .544003 | .440365 | .303559 | 0 |
| 12 | .545357 | .442237 | .304568 | 0 |

The zero entries mean only that this particular DC/parity bound vanishes; they do not certify zero achievable error. The bound need not be attainable within the actual angle/phase family.

More precisely, with g_k the realized positive-lag coefficients and t_k extended by zero above N,

\[
E^2=E_{\rm topology}^2+
\frac{8}{D}\sum_{\substack{k\le2N+1\\k\text{ odd}}}|g_k-t_k/2|^2.
\]

This is an exact squared-error decomposition for the implemented ideal family. It identifies an unavoidable component and the remaining odd-harmonic mismatch. It is much stronger than guessing that the observed .54 error comes mainly from Stage 1.

The peer's PSO errors around .543–.547 at ρ=.2 are close to these order-dependent bounds. That is a legitimate defense of the optimization's accuracy: a normalized error near .54 is not, by itself, evidence of poor optimization. The topology already forces a floor of roughly that magnitude. However, it also prevents claiming successful unrestricted low-pass synthesis at arbitrary passband ratios. If the intended study concerns this half-band architecture under target mismatch, the experiment is meaningful with that framing. If arbitrary passband realization is the engineering aim, the topology or target family needs a separately versioned change.

The symbol N also needs care. In this code it is the raw-reference order and determines N+1 tunable stages. The field polynomial degree can be 2N+1, and the power response can have lags through ±(2N+1). Calling every realized response an order-N FIR response would be inaccurate.

A stronger convex lower-bound reference could project the target, in the E metric, onto all bounded half-band responses of degree up to 2N+1. That is a relaxation of the actual angle/phase family unless surjectivity is proved. It supplies a bound, not automatically an achievable lattice design.

**10. Issue 7: exceptions need classification, not just a percentage.** The nine missing Stage-2 results are real, but their causes differ. Saved telemetry identifies five `fpf:TelemetryWrite` exceptions caused by Windows file-sharing errors and four `MATLAB:eig:NoConvergence` exceptions. The former are instrumentation/infrastructure failures, not evidence that a particular optimizer could not fit a filter. The latter are numerical exceptions; their identifiers alone do not prove the optimizer's search mechanism was the root cause.

The current wrapper can catch a logging exception inside objective evaluation as a trial failure and commit it. Resume then correctly skips that committed record according to the existing policy. For replication, logging must not turn a recoverable telemetry publication problem into a scientific failure. Infrastructure attempts should retain their audit trail and follow an explicit retry policy. A rerun should never silently replace an old failed record in the legacy analysis.

**11. The factorial and random-stream design supports paired inference, not 77,760 independent problems.** The count is correct:

\[
6\times6\times9\times4\times3\times20=77,760.
\]

There are 36 deterministic (N,ρ) target instances, 36 ordered solver pairs, and 60 seed/repetition labels per instance and pair. At completion there will be 2,160 pipeline observations per pair. The random stream key contains seed, repetition and stage, but not the solver pair or the instance. Shared starting randomness is a useful control; the resulting observations are statistically paired and coupled across instances.

For a fixed instance, seed/repetition and Stage-1 solver, the program repeats the same Stage-1 solve for six Stage-2 choices. When time limits and numerical differences do not intervene, those are repeated executions of the same stochastic configuration rather than six independent Stage-1 replicates. There are 12,960 distinct Stage-1 solver/instance/randomization configurations in the full grid. Recomputing them can be justified when measuring a fresh full pipeline, but it does not multiply independent evidence.

Bootstrap and other uncertainty estimates should preserve the matching. For stochastic uncertainty over this fixed instance grid, resampling whole seed/repetition blocks across pairs and instances is more defensible than independently resampling individual rows. Three seeds each with twenty substreams are neither only three trials nor a license to ignore dependence. Wilson intervals on a pooled correlated sample are not automatically justified.

MathWorks distinguishes known substream spacing from separately seeded streams, for which the same separation guarantee is absent. There is no evidence here that the present seeds overlap in practice; the claim should simply stay within what the construction guarantees. [Random-number streams and substreams](https://www.mathworks.com/help/matlab/math/creating-and-controlling-a-random-number-stream.html)

The code assigns random numbers independently of scheduling. It does not guarantee identical complete solver outputs on all hardware or worker counts: surrogate and Pareto search have 400-second limits, which can bind after different numbers of evaluations under different loads. Numerical libraries can also differ. The earlier synthetic serial/parallel tests establish scheduler and bookkeeping properties; they do not prove numerical invariance of every real solver run.

Unequal native budgets can be defended as a comparison of the stated configurations. They are not an equal-effort comparison, and the chosen custom settings should not be called universal practitioner defaults. A GA generation, a PSO iteration and an annealing iteration involve different work. Pattern search is fundamentally a local direct-search method; “six derivative-free solver configurations” is more precise than implying that every method supplies global-optimality guarantees. Fair benchmarking requires these scope distinctions. [Beiranvand, Hare and Lucet](https://doi.org/10.1007/s11081-017-9366-1)

**12. What can be drafted while the computation runs.** Drafting now is reasonable. The introduction, mathematical definitions, intended experiment, exact implemented options, data schema, execution/recovery protocol, limitations, analysis plan and table/figure layouts can be written from known facts. Describe 77,760 as planned until that many trials are accounted for. Distinguish the ideal model from fabrication tolerances and experimental validation that have not been studied.

The results section can have an explicit exhibit plan and diagnostic notes. Final winner claims, final confidence intervals, completed coverage, recommendations and the abstract's numerical findings must wait for the appropriate final analysis. The snapshot covers only a blocked prefix of the factor grid, not a representative random fraction of all intended conditions. Algorithms that are currently running also make completion-time samples biased toward faster outcomes.

The peer's numbered outline is largely useful editorial scaffolding, not an obligation to write every paragraph exactly as prescribed. Its invented model sentences and example results must remain examples. The proposed literature gap also needs an actual review: the cited benchmarking literature does not, by itself, establish that nobody has studied solver pairings in engineering pipelines. Hypotheses suggested after inspecting these diagnostics should be labeled exploratory or tested on a separately designated confirmatory analysis; they should not be presented as having been specified before the observations.

The strongest paper would explain the configured pipeline comparison, its paired randomization, the distinction between termination and achieved accuracy, and the topology-induced approximation floor. That is a more defensible scientific contribution than publishing only a 6×6 score matrix.

**A response you can send to the peer.**

> Thank you for separating the scoring concerns from the manuscript structure. I agree that native positive exit flags are not a solver-independent definition of an acceptable optical design. The existing score will be described as conditional on that termination rule, and the analysis will distinguish returned/valid designs, termination categories, attained error, evaluation counts and elapsed time.
>
> The checkpoint data support a more favorable conclusion about recoverability than the zero summary fields suggest. An audit of global trial IDs 1–4,947 reproduces the 1,042 accepted and 3,905 unaccepted outcomes. It recovers final error and total counts for 4,938 trials, including 3,896 unaccepted outcomes; finite per-stage times are also present wherever the stages returned. Those quantities can be reported without repeating the optimization. The nine missing final designs include five telemetry failures and four numerical exceptions, which should be separated.
>
> Stage 1 is indeed a convex projection problem. Its use here is as a controlled reference-generation component in a solver-pair experiment, not because global search is mathematically necessary. A convex baseline is appropriate, but its relation to final error requires matching the metric and response space. The current Stage-1 coefficient norm is not the same as the final S-matrix power-response norm, and intermediate and final residuals include a cross term.
>
> A further audit establishes that the implemented delays and balanced output coupler enforce half-band responses: DC equals one half and all even harmonics vanish. This yields a calculable error lower bound of approximately .54 for the inspected ρ=.2 targets, explaining much of the reported error level. We will distinguish topology mismatch from optimizer shortfall and describe the modeled architecture precisely.
>
> Scalar Pareto search also has an explicitly supported convergence branch in the installed R2026a implementation, so its observed budget exits should not be described as a structural impossibility of convergence. The experiment remains a valid comparison of the stated configurations and their cross-stage effects, with these corrections to success semantics, inference and physical scope. We can draft formulation and methods now while keeping final performance claims provisional.

**Implications for the authorized cloud replication.** Preserve the scientific solver settings and trial identity mapping in a frozen source snapshot to maintain comparability. Changing success interpretation in an analysis export does not require changing the optimizer trajectories. Changes to topology, targets, optimization objectives or stopping settings would constitute a different scientific protocol and must receive a separate version and result namespace.

The execution changes should preserve complete records for converged, nonconverged and exceptional attempts; publish committed records to durable cloud storage during execution; reconstruct partial MAT/CSV outputs regardless of whole-job success; and resume only the missing compatible work. A final cleanup step alone cannot protect data from a hard VM kill. Already committed records can be guaranteed recoverable within the storage design; arbitrary in-flight optimizer state cannot honestly be promised unless its state or incumbent is explicitly checkpointed. Infrastructure retries must be auditable and separate from solver outcomes. The unintended 72-hour cutoff must not recur as a silent loss-of-work boundary.

For maximum similarity, the original allocation was four e2-standard-8 VMs with eight process workers each, standard provisioning, 30,000 MiB task memory and 100 GB balanced boot disks in us-central1. Availability and quota must be checked at submission. These are execution controls, not evidence of identical wall-clock-sensitive solver trajectories across desktop and cloud.
