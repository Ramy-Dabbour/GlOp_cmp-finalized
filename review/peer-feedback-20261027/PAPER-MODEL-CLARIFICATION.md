# Confirmed model interpretation and manuscript wording — 28 October 2026

The user has explicitly confirmed that the described model is correct: the realized lattice belongs to a half-band family, while the optimization targets may have rho=0.2,0.3,0.4,0.5. The targets are ordinary test cases and are not required to satisfy the realization family's identity. The earlier characterization of this situation as an implementation/specification defect, and the label "uncorrected model," are withdrawn. They resulted from conflating a restriction on realized responses with an admissibility requirement on desired targets.

The mathematical audit of the implemented lattice remains unchanged. Its half-band identity is an invariant of the implemented delay/coupler construction. A non-half-band target is a legitimate approximation objective even though the family cannot reproduce it exactly. No architecture change is required merely because the target does not share the invariant. This clarification does not establish that the full optimization benchmark is complete, that every returned solution is optimal, or that the original positive-exit-flag success definition is an accuracy criterion.

**Suggested manuscript paragraph**

> We compare the configured two-stage optimization pipelines for low-pass targets with passband ratios rho in {0.2,0.3,0.4,0.5}. The implemented lattice realizes power responses satisfying G(omega+pi)=1-G(omega); its zero-lag Fourier coefficient is therefore one half and its nonconstant even harmonics vanish. The desired targets are not required to satisfy this identity. For rho=0.2,0.3,0.4, optimization consequently seeks an approximation within the lattice family, with an unavoidable DC/even-harmonic contribution to the end-to-end error. The case rho=0.5 is structurally special: the truncated target itself has constant coefficient one half and zero even harmonics, so that particular error contribution vanishes. This compatibility does not guarantee exact realization or zero error, because physical power bounds, the lattice parameterization, and finite optimization can impose further limitations. All four ratios are treated as intended benchmark cases, and results are reported by ratio to make this distinction explicit.

**Mathematical statement for the model section**

For the raw target

\[
T_N(\omega;\rho)=\rho+\sum_{k=1}^{N}
\frac{2\sin(\pi\rho k)}{\pi k}\cos(k\omega),
\]

rho=1/2 implies t0=1/2 and t(2j)=0, hence

\[
T_N(\omega+\pi;1/2)=1-T_N(\omega;1/2).
\]

This statement concerns the raw truncated target; an approximate Stage-1 solve is not thereby guaranteed to preserve the identity exactly.

The existing decomposition E²=B(N,rho)²+Rodd² remains applicable to the unchanged lattice. At rho=1/2 its DC/parity bound B is zero; that does not assert that the true minimum E is zero. At the other ratios the positive bound is a property of the specified approximation problem, not evidence that the test case is invalid or that the optimizer malfunctioned. A bound-relative residual should not be described as purely optimization error because the bound may be unattainable within the full parameterization.

Only review documents were updated. The MATLAB model, frozen cloud source, solver options, saved results, and execution controls were not changed.
