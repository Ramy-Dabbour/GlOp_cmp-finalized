# Mathematical audit of the photonic FIR pipeline

Read-only source audit and independent numerical calculation, 26 October 2026.
No benchmark source, checkpoint, setting, or active execution was changed.

## Main conclusion

The two-stage numerical pipeline has a coherent mathematical interpretation:
Stage 1 approximates a desired cosine power response by one bounded between
zero and one; Stage 2 approximates that reference by a lossless, periodic
lattice family. The end-to-end score uses the original target and has an exact
Parseval interpretation. These facts defend a comparison of specified solver
configurations on this particular pipeline.

They do not prove that Stage 1 requires a global optimizer, that every Stage-1
reference is realizable by this lattice, or that a positive solver exit flag
certifies accurate physical synthesis. Most importantly, the implemented
lattice is a half-band family: it forces DC power to one half and all even
power-response harmonics to zero. This gives a substantial unavoidable
end-to-end error for passband ratios other than 0.5. It is a demonstrable
topology restriction; whether the topology is the intended physical design
must be settled from its specification, not inferred from an optimizer result.

## 1. Stage 1 is convex, but the black-box implementation hides this structure

The code uses

\[
F(\omega;x)=x_0+\sum_{k=1}^{N}x_k\cos(k\omega),\qquad
J_1(x)=\frac{\|x-t\|_2}{\|t\|_2},
\]

with bounds `x0 in [0,1]`, `xk in [-1,1]`, and `0 <= F <= 1` at every
frequency. See `+fpf/optimizeReference.m:17-28` and
`+fpf/referenceObjective.m:6-16`.

For each fixed frequency the two inequalities are affine in x. Their
intersection with the box is a nonempty compact convex set (the constant
response 1/2 belongs to it). Minimizing the Euclidean distance has the same
minimizer as minimizing its square, which is strictly convex. Therefore the
exact mathematical projection is unique. The peer is correct on this point.

The supplied black box returns `realmax` for infeasible candidates. That finite,
flat exterior penalty is not a convex numerical representation of the problem;
it hides the useful constraint geometry and presents a discontinuous boundary
to a generic derivative-free solver. Nevertheless its global minimizer agrees
with the constrained problem because feasible distances are vastly below
`realmax`. Benchmarking global/general derivative-free methods on it is a
legitimate experimental choice, provided it is described as such. It does not
establish a need for a global method at Stage 1.

A frequency-grid QP is a discretized relaxation, not automatically an exact
continuous-frequency optimum. A numerical SDP is also solved to numerical
tolerances. A defensible reference optimum needs the chosen representation,
solver tolerances, an independent feasibility check, and an optimality gap or
residual report. The word "exact" should distinguish exact formulation from
floating-point solution.

## 2. The feasibility check is analytic in construction, numerical in execution

Let y=cos(omega). The response is the polynomial
`p(y)=x0+sum xk T_k(y)` on `[-1,1]`. Its extrema occur at the endpoints or real
roots of `p'(y)`. The code constructs the derivative using
`T'_k(y)=k U_(k-1)(y)` (`+fpf/signalValuePolynomials.m:10-16`), computes roots,
keeps those whose imaginary component is below `1e-12` and real component lies
in `[-1,1]`, and evaluates the polynomial there
(`+fpf/chebyshevExtrema.m:5-11`). Both endpoints are checked separately with a
`1e-12` feasibility tolerance (`+fpf/isReferenceNormalized.m:11-16`).

This is an exhaustive extremum characterization in exact arithmetic and avoids
the between-grid oversight of a simple sampled test. It is not an interval or
symbolic certificate: polynomial roots, monomial coefficients, and evaluations
are computed in floating point; roots near multiplicity or the acceptance
threshold can be numerically delicate. A precise paper description is
"continuous-frequency extrema test based on polynomial roots, evaluated
numerically with stated tolerances." Dense-grid agreement is useful validation,
not a proof of certification.

## 3. Feasible initialization is a sound construction

The generator chooses DC d in (0,1) and harmonics satisfying

\[
\sum_{k=1}^{N}|x_k|\leq\min(d,1-d).
\]

Since `|cos(k omega)| <= 1`, this guarantees `0 <= F <= 1` for all frequencies.
Exponential simplex weights, independent signs, and radius proportional to
`U^(1/N)` sample the conditional L1 ball, with a rounding margin
(`+fpf/generateInitialPoints.m:41-48`). This is a conservative subset of the
admissible set, not the entire admissible set and not a uniform distribution on
the entire feasible region. Feasible initialization removes the need to
discover feasibility from scratch. It does not make coefficient refinement
trivial or make all initialized points equally accurate. It also does not prove
that every future solver implementation must retain a feasible output; actual
return validity should continue to be checked.

## 4. Losslessness and the additional half-band restriction

With M=N+1 stages, the implemented stage is

\[
U_k(z)=C(\theta_k)\,\operatorname{diag}(p_k z^{d_k},1),
\quad
C(\theta)=\begin{bmatrix}c&i s\\i s&c\end{bmatrix},
\quad c=\cos(2\pi\theta),\ s=\sin(2\pi\theta),
\]

where `|p_k|=1`, delay orders are `[2,...,2,1]`, and the final coupler is

\[
Q=\frac1{\sqrt2}\begin{bmatrix}1&i\\i&1\end{bmatrix}.
\]

These are literal source choices in `+fpf/mziSMatrixCoefficients.m:18-35`.
Every factor is unitary when `|z|=1`; their product is unitary. Consequently
every exact-arithmetic design is a lossless two-port and its powers are bounded
between zero and one. The normalized variables cover periodic angles:
`theta -> 2*pi*theta`, and phase `phi -> exp(-2*pi*i*phi)`.
`+fpf/unpackMziDesign.m:11-13` wraps variables modulo one. This proves physical
validity within the ideal lossless model; it says nothing about fabricated
losses, phase errors, or representability of all bounded target functions.

Because all preceding delays are even, absorb their product and the last
variable coupler into a matrix B(z^2). The last phase is zero in the actual
alternating pattern, but even a constant last phase could be absorbed into B.
Then

\[
S(z)=B(z^2)\operatorname{diag}(z,1)Q.
\]

Write the first row of B as `(a(z^2), b(z^2))`. Its unitary row norm is one,
and therefore

\[
|S_{11}(z)|^2
=\frac{|a|^2+|b|^2}{2}+\Re[-i a\bar b z]
=\frac12+\Re[-i a(z^2)\overline{b(z^2)}z].
\]

The second term has only odd Fourier harmonics. Replacing z by -z changes its
sign. Hence, for diagonal power response g,

\[
g(\omega+\pi)=1-g(\omega),\qquad g_0=\tfrac12,
\qquad g_{2j}=0\quad(j\ne0).
\]

Unitarity of a 2-by-2 matrix additionally gives the power matrix
`[[g,1-g],[1-g,g]]`. The shared phase can generate sine as well as cosine odd
harmonics, but cannot remove the DC/even-harmonic restriction.

This is why a generic Stage-1 admissible reference need not be representable by
the lattice. In particular, a degree-N truncated low-pass reference with
rho=0.2,0.3,0.4 has DC rho, not 1/2, and generally nonzero even harmonics.
Calling it "admissible as a bounded power response" is justified; calling it
"realizable by the implemented lattice" is not.

The source's degree is also important. M=N+1 stages have total delay degree
`2M-1=2N+1`, giving up to `2N+2` field coefficients and power lags
`-(2N+1),...,(2N+1)`. N is the reference-series order and a stage-count
parameter. The skeleton's simple description of the realized device as an
order-N FIR with N+1 field taps does not match this code. Some coefficients
vanish for special settings, but this is the generic degree bound.

## 5. What the end-to-end metric measures

Define the DC-first Hermitian lag vector

\[
L(t)=[t_0,t_1/2,\ldots,t_N/2,0,\ldots,0,t_N/2,\ldots,t_1/2]
\]

with padding to the realized degree, and let delta be the constant-one lag
vector. The target matrix has rows `[L(t);delta-L(t);delta-L(t);L(t)]`
(`+fpf/referenceSMatrixCoefficients.m:8-12`,
`+fpf/expandReferenceLagVector.m:14-17`). The actual power rows have the same
complementary structure with g in place of L(t). Thus the implemented score is

\[
E^2=\frac{4\|g-L(t)\|_2^2}{D},\qquad
D=2\big[t_0^2+(1-t_0)^2+\sum_{k=1}^{N}t_k^2\big].
\]

See `+fpf/endToEndError.m:24-43`. The metric includes all harmonics, with correct
padding between positive and negative lags. By Parseval it is exactly the
normalized integrated squared error of the four power responses over a full
frequency period, expressed through coefficients rather than a sampled grid.
This is a strong, legitimate defense of the metric. It is a power-transfer
error, not a complex optical-field S-matrix error: field phases are not directly
scored. For a lossless two-port, the four powers are related, so using all four
does not supply four independent quality criteria.

For another cosine vector x at the same degree, its E numerator is
`4*(x0-t0)^2 + 2*sum_(k>=1)(xk-tk)^2`. Stage 1 instead minimizes
`(x0-t0)^2 + sum_(k>=1)(xk-tk)^2`, divided by `||t||^2`.
The weighting and normalization are different. Therefore Stage 1's reported
objective optimum is not automatically a floor for E. Converting the optimum
vector to E is better, but even that is not a guaranteed lower bound on the
actual lattice when its available degree is larger than N.

## 6. A rigorous topology floor and exact residual decomposition

Let `t_k=0` for k>N. With `g_k` the positive-lag complex coefficients of the
realized power response, the proven half-band restrictions give

\[
E^2=
\underbrace{\frac{4(1/2-\rho)^2+
2\sum_{\substack{2\le k\le N\\ k\text{ even}}}t_k^2}{D}}_{E_{\rm parity}^2}
+\frac{8\sum_{\substack{1\le k\le 2N+1\\ k\text{ odd}}}
|g_k-t_k/2|^2}{D}.
\]

This is an equality, and the second term is nonnegative. It proves a lower
bound valid for every parameter choice and every optimizer. The lower bound
does not claim that its equality case is always bounded or representable by
the restricted shared-phase lattice.

| rho | N=4 | N=10 | N=12 |
|---|---:|---:|---:|
| 0.2 | 0.5401209664 | 0.5440034891 | 0.5453565101 |
| 0.3 | 0.4357750792 | 0.4403652593 | 0.4422374331 |
| 0.4 | 0.2848836005 | 0.3035589312 | 0.3045678203 |
| 0.5 | 0 | 0 | 0 |

The zero entry for rho=0.5 says only that DC/parity imposes no mismatch; the
raw target still overshoots and physical admissibility can impose a nonzero
floor. For rho=0.2, the peer's reported errors around 0.543-0.547 are close to
this topology floor. The correspondence is a structural explanation supported
by the formula, not proof that every reported solver attained its global
optimum. A matched per-order/per-trial check is needed for that stronger claim.

There is also a simple way to demonstrate that generic bounded-response
admissibility alone cannot explain a 0.54 floor. If the raw polynomial has
minimum a and maximum b, the degree-N response `(F-a)/(b-a)` is admissible.
At rho=0.2, this explicit response has E=0.10502 (N=4), 0.09826 (N=10),
and 0.12134 (N=12), all much smaller than the lattice's guaranteed error.
These are upper bounds on the best generic admissible-response error, not
estimates of the exact optimum.

An improved convex lower-bound problem for the lattice would use the SAME E
metric and degree 2N+1, impose power bounds, DC=1/2, and zero even harmonics,
and relax the particular shared-phase factorization. The actual lattice family
is a subset of that convex response family, so the exact relaxed optimum is a
lower bound on the lattice optimum. The target is even; reflection symmetry
and convexity allow a best relaxed response to be chosen even, so cosine-only
odd coefficients suffice for this relaxation. A finite-grid solution further
relaxes continuous-frequency constraints; its objective is a lower bound on
the continuous optimum in exact arithmetic, while its candidate might violate
constraints between sampled frequencies. Feasible candidate objectives are
upper bounds on their own optimization problem. These directions should not
be interchanged.

## 7. Two-stage residuals do not generally add

Write T for the raw target coefficient matrix, R for the Stage-1 reference
matrix, and A for the realized matrix. Then

\[
\|A-T\|_F^2=\|R-T\|_F^2+\|A-R\|_F^2
+2\Re\langle R-T,A-R\rangle_F.
\]

The cross term need not vanish or have a fixed sign for this program. Also,
Stage 2 normalizes by `||R||`, whereas E normalizes by `||T||`. Logging Stage-1
residual and Stage-2 fitting residual is informative, but it does not yield an
additive split of E without the cross term and denominator conversion.
The parity/odd-lag decomposition above is different: its components are
orthogonal coefficient subspaces, so its squared-error split is exact.

## 8. Numerical verification performed for this audit

`math_audit.py` independently implements the existing transfer matrices in
NumPy. It checked 108 random parameter vectors across all 36 (N,rho) settings,
without running any benchmark optimizer. The accompanying JSON records all
36 target extrema and topology bounds. Maximum discrepancies were:

- DC versus 1/2: 4.45e-16.
- Even-lag magnitude: 1.29e-16.
- Four-row power complementarity: 8.89e-16.
- Frequency half-band identity: 1.47e-14.
- Coefficient metric versus Parseval frequency calculation: 4.45e-16.
- Exact floor-plus-odd-residual identity: 8.89e-16.

These checks support the algebraic derivation; they are not a substitute for
the proof or a validation of every MATLAB solver execution. The actual raw
target extrema across the grid range from minima -0.1184756080 to -0.0636494135,
and maxima 1.0401362468 to 1.1722957943. The peer's qualitative overshoot claim
is correct, but its approximate lower maximum of 1.06 misses N=7,rho=0.2.

## Defensible wording for the response to the peer

"We agree that the first-stage bounded-response problem is convex, and will
not claim that a global method is mathematically necessary. We study the
behavior of fixed derivative-free solver configurations within a two-stage
pipeline, including their effects on the reference supplied to Stage 2. The
initialization guarantees an admissible starting response, and the final
coefficient metric is equivalent by Parseval to an integrated power-response
error against the common raw target. Our review also identifies an additional
structural issue: the implemented delay pattern and balanced output coupler
enforce half-band complementarity. Consequently the passband-ratio sweep
includes deliberate or unintended model mismatch, and this topology imposes
a rigorous error floor that must be separated from optimizer performance.
The unweighted Stage-1 objective is not itself that floor. We can draft the
verified model, methods, protocol, and limitations now, while reserving all
rankings and performance claims for a defined and correctly analyzed dataset."
