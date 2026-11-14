# Architecture requirement correction — 27 October 2026

**Superseded on 28 October 2026.** The user has confirmed that the described half-band realization family with potentially non-half-band optimization targets is the correct model. The defect diagnosis and architectural-change recommendation below are withdrawn; they are retained only as a record of the prior interpretation. The half-band source-code findings remain valid. See [the confirmed interpretation and paper wording](C:/Users/Dell/Documents/MATLAB/GlOp_cmp/review/peer-feedback-20261027/PAPER-MODEL-CLARIFICATION.md).

The user clarified that rho=0.2,0.3,0.4,0.5 are ordinary intended benchmark cases and that half-band complementarity is optional. This clarification controls the intended experiment. The previous recommendation to retain the current model and recast three quarters of the grid as target-mismatch conditions is withdrawn.

The current benchmark configuration already lists all four passband ratios. However, `+fpf/mziSMatrixCoefficients.m` unconditionally sets the stage delay orders to `[2,...,2,1]` at line18 and appends a balanced output coupler at line34. In combination these choices enforce the previously proved half-band frequency identity for every allowed design vector. No option in the inspected benchmark configuration or lattice call path disables that restriction. Optimizing the existing shared phase does not remove it.

Thus the mathematical audit remains a correct description of the currently coded transfer model, but that description identifies an implementation/specification discrepancy. It cannot establish that the user's intended general test cases are invalid or should be relabeled as deviations from a half-band operating point. The half-band error bound is diagnostic of the restricted implementation, not a requirement imposed on the intended experiment.

The local lattice function and the frozen production source for `matlab-glop-cmp-20261026-1405` have identical SHA-256:

`F3F5D432F57F1D5883FC732AAD00E57FA5B3BD59C23C83A401ABF77D7AE8C7F4`

Consequently, the replication inherited this modeling restriction. Preserving the same source fulfilled the replication aspect but does not establish fidelity to the intended optional-constraint architecture. Existing results remain records of the constrained implementation; changing their labels or success criterion cannot turn them into results for a different forward model.

The appropriate correction is to establish the intended general lattice transfer model and its optional half-band specialization, then validate the implementation against that model. The exact replacement delay/coupler/phase parameterization has not been established by this clarification alone. Changing a delay pattern or making a coupler tunable without checking the intended physical architecture would be an unsupported model change. A general mode should be tested on known non-half-band realizations, and an optional half-band mode should recover its expected identity. The four intended target cases must remain in the benchmark.

Any revised physical model needs a distinct configuration/source identity and separate results. Existing checkpoints must not be resumed into a changed model as if they were compatible. The topology-derived lower bound and related attainment metrics from the earlier audit apply only to the old constrained model unless rederived for the corrected architecture.

This correction updates the scientific interpretation and review documents only. It does not modify or stop either benchmark, change solver settings, deploy a replacement physical model, or discard saved data. The investigation here does not establish when or by whom the mandatory restriction was introduced.
