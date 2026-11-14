#!/usr/bin/env python3
"""fpf_analysis.py -- outcome-based analysis of GlOp_cmp trial records.

Reads the per-trial records the program ALREADY writes (local live JSON records,
Google Cloud live JSONL/JSONL.GZ history, or local MAT checkpoints), recomputes
every quantity from the stored matrices, and writes tables for the paper.
It never changes, imports, or re-runs any MATLAB code, so it cannot affect the
manifest source hash or the scientific protocol.

Usage (see README_analysis.md):
    python fpf_analysis.py SOURCE_DIR [SOURCE_DIR ...] --out OUTDIR [--plan analysis_plan.json]
                           [--checkpoints CHECKPOINT_DIR] [--expect-trials 77760]
"""
import argparse, glob, gzip, hashlib, json, os, sys, time
import numpy as np
import pandas as pd

SOLVERS = ["ga", "particleswarm", "surrogateopt", "simulannealbnd", "patternsearch", "paretosearch"]
DEFAULT_PLAN = {
    "plan_version": 1,
    "comment": "Fix these values BEFORE opening the full-run data. Any tolerance added later is exploratory.",
    "tolerances_delta_dB": [-20, -25, -30, -35, -40, -45, -50, -55, -60],
    "tolerances_excess_over_bound": [0.005, 0.01, 0.02, 0.05, 0.1],
    "tolerance_grid_provenance": "Primary success rule: delta = sqrt(E^2 - E_bound^2) <= 10^(dB/20), a fixed ladder in 5 dB steps from -20 to -60 dB, chosen a priori and independent of the instance (after the COCO convention of fixed, log-spaced target precisions); the main-text table uses the 10 dB subset -20, -30, -40, -50, -60 and the 5 dB rungs between are supplementary. The ladder was not derived from results; only its step size was set after the 4,947-trial snapshot (rho=0.2, seed 0, orders 4-10), where success fell from about 98% at -20 dB to 0% at -30 dB (best delta 0.029-0.051), so 10 dB steps would leave one informative rung. The snapshot says nothing about rho=0.5, hence the range down to -60 dB. The E-excess ladder is secondary and is NOT comparable across rho: the same excess is a 15x different delta at rho=0.5 than at rho=0.2.",
    "tolerances_gap_to_cell_best": [0.001, 0.002, 0.005, 0.01, 0.02],
    "stage2_gap_tolerances": [0.0001, 0.001, 0.01],
    "profile_grid_delta": {"min": 0.0003, "max": 0.3, "points": 80},
    "infrastructure_failure_identifiers": ["fpf:TelemetryWrite"],
    "numeric_exception_identifiers": ["MATLAB:eig:NoConvergence"],
    "duplicate_policy": "error",
    "baseline_grid_points": 4001,
    "bootstrap_replicates": 2000,
    "bootstrap_seed": 20261028,
    "bootstrap_block": ["seed", "trial"],
}

# ----------------------------------------------------------------------------- loading
def _num(v):
    return np.nan if v is None else float(v)

def _mat(m):
    """Decode a MATLAB jsonencode matrix: {'real','imag','size'} or nested list."""
    if m is None:
        return None
    if isinstance(m, dict) and "real" in m:
        re = np.array(m["real"], dtype=float)
        im = np.array(m["imag"], dtype=float) if m.get("imag") is not None else 0.0
        a = re + 1j * im if np.any(im) else re
        if m.get("size") and a.size == int(np.prod(m["size"])) and a.shape != tuple(m["size"]):
            a = a.reshape(tuple(int(s) for s in m["size"]))
        return a
    return np.array(m, dtype=float)

def _reference_matrix(x, tap, lag_count):
    x = np.asarray(x, float).ravel()
    pos = np.zeros(lag_count - 1)
    pos[: tap - 1] = 0.5 * x[1:]
    lag = np.concatenate([[x[0]], pos, pos[::-1]])
    cross = -lag.copy()
    cross[0] += 1.0
    return np.vstack([lag, cross, cross, lag])

def end_to_end_error(raw, A):
    """Exact port of fpf.endToEndError (validated against saved values to 3e-16)."""
    raw = np.asarray(raw, float).ravel()
    A = np.asarray(A)
    L = A.shape[1]
    rlc = (L + 1) // 2
    tap = raw.size
    lag_count = max(tap, rlc)
    ref = _reference_matrix(raw, tap, lag_count)
    pad = lag_count - rlc
    Ap = np.hstack([A[:, :rlc], np.zeros((4, 2 * pad)), A[:, rlc:]])
    d = np.linalg.norm(Ap - ref, axis=1)
    r = np.linalg.norm(ref, axis=1)
    return float(np.linalg.norm(d.reshape(2, 2).T) / np.linalg.norm(r.reshape(2, 2).T))

def half_band_bound(raw):
    """Closed-form lower bound on E imposed by the half-band lattice (see outline, P1b)."""
    t = np.asarray(raw, float).ravel()
    rho, tk = t[0], t[1:]
    D = 2.0 * (rho ** 2 + (1 - rho) ** 2 + np.sum(tk ** 2))
    return float(np.sqrt((4 * (0.5 - rho) ** 2 + 2 * np.sum(tk[1::2] ** 2)) / D))

def half_band_deviation(A):
    A = np.asarray(A)
    rlc = (A.shape[1] + 1) // 2
    dc = float(np.max(np.abs(A[:, 0] - 0.5)))
    ev = [k for k in range(2, rlc, 2)]
    even = float(np.max(np.abs(A[:, ev]))) if ev else 0.0
    return dc, even

def row_from_record(rec):
    """Normalise one live-JSON trial record (local or cloud) into a flat row."""
    res = rec.get("result") or {}
    ref = res.get("referenceResult") or {}
    mzi = res.get("mziResult") or {}
    rm, mm = ref.get("metrics") or {}, mzi.get("metrics") or {}
    raw = res.get("rawSincReference")
    A = _mat(mzi.get("realizedCoefficientMatrix"))
    row = dict(
        gid=int(rec["global_trial_id"]), order=res.get("firOrder"), ratio=res.get("passbandRatio"),
        seed=res.get("randomSeed"), trial=res.get("trialIndex"),
        refSolver=res.get("referenceSolver"), mziSolver=res.get("mziSolver"),
        status=rec.get("status"), legacy_success=bool(res.get("success", False)),
        failureStage=res.get("failureStage") or "", failureIdentifier=res.get("failureIdentifier") or "",
        failureMessage=(res.get("failureMessage") or "")[:200],
        ref_present=bool(ref), ref_exit=_num(rm.get("exitFlag", ref.get("exitFlag"))),
        ref_valid=bool(ref.get("isValidSolution", False)), ref_conv=bool(rm.get("converged", False)),
        ref_evals=_num(rm.get("functionEvaluations")), ref_seconds=_num(rm.get("elapsedSeconds")),
        ref_objective=_num(ref.get("objectiveValue")), ref_message=(ref.get("output") or {}).get("message", ""),
        mzi_present=A is not None, mzi_exit=_num(mm.get("exitFlag", mzi.get("exitFlag"))),
        mzi_valid=bool(mzi.get("isValidSolution", False)), mzi_conv=bool(mm.get("converged", False)),
        mzi_evals=_num(mm.get("functionEvaluations")), mzi_seconds=_num(mm.get("elapsedSeconds")),
        mzi_objective=_num(mzi.get("normalizedFrobeniusError")), mzi_message=(mzi.get("output") or {}).get("message", ""),
        E_saved=_num(rec.get("end_to_end_error")), record_elapsed_seconds=_num(rec.get("elapsed_seconds")),
        completed_at=rec.get("completed_at", ""),
    )
    row.update(E=np.nan, E_bound=np.nan, hb_dc_dev=np.nan, hb_even_dev=np.nan)
    if raw is not None and len(raw):
        row["E_bound"] = half_band_bound(raw)
        row["raw_rho"] = float(raw[0])
    if A is not None and raw is not None and len(raw):
        row["E"] = end_to_end_error(raw, A)
        row["hb_dc_dev"], row["hb_even_dev"] = half_band_deviation(A)
    return row

def iter_json_records(paths):
    for root in paths:
        for dirpath, _, files in os.walk(root):
            for f in files:
                p = os.path.join(dirpath, f)
                if f.startswith("trial_") and f.endswith(".json"):
                    with open(p, "r", encoding="utf-8") as fh:
                        yield p, json.load(fh)
                elif f.endswith(".jsonl.gz") or f.endswith(".jsonl"):
                    op = gzip.open if f.endswith(".gz") else open
                    with op(p, "rt", encoding="utf-8") as fh:
                        for line in fh:
                            line = line.strip()
                            if line:
                                yield p, json.loads(line)

def load_trials(paths, duplicate_policy="error"):
    rows, seen, dups = [], {}, []
    for p, rec in iter_json_records(paths):
        if not isinstance(rec, dict) or "global_trial_id" not in rec:
            continue            # summary/latest/worker files are not trial records
        row = row_from_record(rec)
        row["source_file"] = p
        gid = row["gid"]
        if gid in seen:
            dups.append((gid, seen[gid]["source_file"], p))
            if duplicate_policy == "first":
                continue
            if duplicate_policy == "last":
                rows[seen[gid]["_i"]] = row; row["_i"] = seen[gid]["_i"]; seen[gid] = row
                continue
        row["_i"] = len(rows)
        seen[gid] = row
        rows.append(row)
    if dups and duplicate_policy == "error":
        raise SystemExit("Duplicate global trial IDs found (%d). Decide which attempt is authoritative and "
                         "re-run with --duplicates first|last. Example: %s" % (len(dups), dups[:3]))
    if not rows:
        return pd.DataFrame(), dups
    df = pd.DataFrame(rows).drop(columns=["_i"], errors="ignore").sort_values("gid").reset_index(drop=True)
    return df, dups

# ----------------------------------------------------------------------------- Stage-1 convex baseline
def stage1_baseline(order, rho, grid_points=4001):
    """Convex Stage-1 baseline: min ||x-t||/||t|| s.t. 0 <= F(w;x) <= 1, x0 in [0,1], xk in [-1,1].
    Returns (lower, upper, max_violation_before_shift). 'lower' is the optimum of a finite-grid
    relaxation (a valid lower bound); 'upper' is that solution shifted toward the interior
    point x=[0.5,0..0] until it is continuous-domain feasible (a valid upper bound)."""
    from scipy.optimize import minimize
    from numpy.polynomial import chebyshev as Ch
    N = int(order)
    k = np.arange(1, N + 1)
    t = np.concatenate([[rho], 2 * rho * np.sinc(rho * k)])
    nt2 = float(np.sum(t ** 2))
    w = np.linspace(0.0, np.pi, int(grid_points))
    C = np.cos(np.outer(w, np.arange(N + 1)))
    f = lambda x: np.sum((x - t) ** 2) / nt2
    g = lambda x: 2 * (x - t) / nt2
    cons = [{"type": "ineq", "fun": lambda x: C @ x, "jac": lambda x: C},
            {"type": "ineq", "fun": lambda x: 1.0 - C @ x, "jac": lambda x: -C}]
    bnds = [(0, 1)] + [(-1, 1)] * N
    x0 = np.concatenate([[0.5], np.zeros(N)])
    r = minimize(f, x0, jac=g, bounds=bnds, constraints=cons, method="SLSQP",
                 options={"maxiter": 1000, "ftol": 1e-16})
    x = r.x

    def extremes(x):
        d = Ch.chebder(x)
        roots = Ch.chebroots(d) if len(d) > 1 else np.array([])
        roots = np.real(roots[np.abs(np.imag(roots)) < 1e-12]) if roots.size else roots
        pts = np.concatenate([[-1.0, 1.0], roots[(roots >= -1) & (roots <= 1)]])
        vals = Ch.chebval(pts, x)
        return vals.min(), vals.max()
    # NOTE: cosine series in w == Chebyshev series in c=cos(w) with the same coefficients.
    lo, hi = extremes(x)
    viol = max(hi - 1.0, -lo, 0.0)
    xc = np.concatenate([[0.5], np.zeros(N)])
    if viol > 0:
        s = viol / (0.5 + viol) + 1e-15
        xu = (1 - s) * x + s * xc
    else:
        xu = x
    lo2, hi2 = extremes(xu)
    ok = (lo2 >= -1e-12) and (hi2 <= 1 + 1e-12)
    return float(np.sqrt(f(x))), float(np.sqrt(f(xu))), float(viol), bool(ok), bool(r.success)

# ----------------------------------------------------------------------------- metrics
def legacy_index(sub):
    n = len(sub)
    s = sub[sub.legacy_success]
    k = len(s)
    if k == 0:
        return dict(n=n, legacy_k=0, legacy_P=0.0, legacy_E=np.nan, legacy_C=np.nan, legacy_F=0.0)
    E = s.E_saved.mean() if s.E_saved.notna().all() else s.E.mean()
    C = (s.ref_evals + s.mzi_evals).mean()
    P = k / n
    F = np.nan if (C <= 1 or not np.isfinite(E) or E <= 0) else P / E / np.log(C)
    return dict(n=n, legacy_k=k, legacy_P=P, legacy_E=E, legacy_C=C, legacy_F=F)

def total_cost(df, col_ref, col_mzi):
    return df[col_ref].fillna(0) + df[col_mzi].fillna(0)

def add_derived(df, plan):
    df = df.copy()
    infra = set(plan["infrastructure_failure_identifiers"])
    df["infra_failure"] = df.failureIdentifier.isin(infra)
    numeric = set(plan["numeric_exception_identifiers"])
    df["numeric_exception"] = df.failureIdentifier.isin(numeric)
    df["both_valid"] = df.ref_valid & df.mzi_valid & df.mzi_present
    df["excess"] = df.E - df.E_bound
    df["delta"] = np.sqrt(np.maximum(df.E ** 2 - df.E_bound ** 2, 0.0))
    df["delta_dB"] = 20.0 * np.log10(df.delta.where(df.delta > 0))
    df["total_evals"] = total_cost(df, "ref_evals", "mzi_evals")
    df["total_seconds"] = total_cost(df, "ref_seconds", "mzi_seconds")
    # A trial that ended before Stage 2 returned has no Stage-2 seconds; use the record's wall time.
    # Its Stage-2 evaluations are not saved anywhere, so flag the cost as incomplete.
    df["cost_incomplete"] = ~df.mzi_present
    df["total_seconds"] = df.total_seconds.where(df.mzi_present, df.record_elapsed_seconds.fillna(df.total_seconds))
    cell = ["order", "ratio", "seed"]
    ok = df.E.notna() & df.both_valid
    best = df[ok].groupby(cell).E.min().rename("cell_best_E")
    df = df.join(best, on=cell)
    df["gap_to_cell_best"] = df.E - df.cell_best_E
    # Stage-2 gap to the best Stage-2 solver for the SAME reference (same stage-1 solve)
    grp = ["refSolver", "order", "ratio", "seed", "trial"]
    m2 = df[df.mzi_present & df.mzi_objective.notna()].groupby(grp).mzi_objective.agg(["min", "count"])
    df = df.join(m2.rename(columns={"min": "group_best_mzi_objective", "count": "group_stage2_count"}), on=grp)
    df["stage2_gap_to_group_best"] = df.mzi_objective - df.group_best_mzi_objective
    return df

def pair_tables(df, plan):
    grids = (("delta", "delta", [(f"{d:g}dB", 10.0 ** (d / 20.0)) for d in plan["tolerances_delta_dB"]]),
             ("excess", "excess", [(f"{t:g}", t) for t in plan["tolerances_excess_over_bound"]]),
             ("cellbest", "gap_to_cell_best", [(f"{t:g}", t) for t in plan["tolerances_gap_to_cell_best"]]))
    out = []
    for (r, m), sub in df.groupby(["refSolver", "mziSolver"]):
        row = dict(refSolver=SOLVERS[int(r)], mziSolver=SOLVERS[int(m)])
        row.update(legacy_index(sub))
        ret = sub[sub.E.notna()]
        row.update(n_returned=len(ret), n_failed=int((sub.status == "failed").sum()),
                   n_infra_failures=int(sub.infra_failure.sum()),
                   n_cost_incomplete=int(sub.cost_incomplete.sum()),
                   n_numeric_exceptions=int(((sub.status == "failed") & ~sub.infra_failure).sum()),
                   flagfree_E_mean=ret.E.mean(), flagfree_E_median=ret.E.median(),
                   flagfree_excess_mean=ret.excess.mean(),
                   mean_total_evals=sub.total_evals.mean(), mean_total_seconds=sub.total_seconds.mean())
        excl = sub[~sub.infra_failure]
        excl_all = sub[~sub.infra_failure & ~sub.numeric_exception]
        for crit, col, grid in grids:
            for label, tau in grid:
                succ = sub.both_valid & (sub[col] <= tau)
                k = int(succ.sum())
                name = f"{crit}{label}"
                row[f"{name}_k"] = k
                row[f"{name}_P"] = k / len(sub)
                row[f"{name}_ERT_evals"] = sub.total_evals.sum() / k if k else np.nan
                row[f"{name}_ERT_seconds"] = sub.total_seconds.sum() / k if k else np.nan
                for tag, part in (("exclinfra", excl), ("exclexc", excl_all)):
                    kx = int((part.both_valid & (part[col] <= tau)).sum())
                    row[f"{name}_P_{tag}"] = kx / len(part) if len(part) else np.nan
        out.append(row)
    return pd.DataFrame(out)

def bootstrap_ci(df, plan):
    """Clustered bootstrap of P(tau) and expected cost per success for the pre-specified tolerances.
    Blocks = plan['bootstrap_block'] (default: seed x repeat, resampled across all orders and ratios, because
    those trials share random-stream indices). One shared set of block weights is used for every pair, so
    differences between pairs inherit the pairing. Percentile intervals, 95%."""
    blk = plan["bootstrap_block"]
    keys = df[blk].astype(str).agg("|".join, axis=1)
    ids, inv = np.unique(keys.values, return_inverse=True)
    nb = len(ids)
    rng = np.random.default_rng(plan["bootstrap_seed"])
    B = int(plan["bootstrap_replicates"])
    W = rng.multinomial(nb, np.full(nb, 1.0 / nb), size=B).astype(float)      # B x nb block counts
    rows = []
    for (r, m), sub in df.groupby(["refSolver", "mziSolver"]):
        sb = pd.Series(inv, index=df.index).loc[sub.index].values
        n_b = np.bincount(sb, minlength=nb).astype(float)
        ev_b = np.bincount(sb, weights=sub.total_evals.values, minlength=nb)
        sc_b = np.bincount(sb, weights=sub.total_seconds.values, minlength=nb)
        for dB in plan["tolerances_delta_dB"]:
            tau = 10.0 ** (dB / 20.0)
            ok = (sub.both_valid & (sub.delta <= tau)).values.astype(float)
            k_b = np.bincount(sb, weights=ok, minlength=nb)
            N, K = W @ n_b, W @ k_b
            with np.errstate(divide="ignore", invalid="ignore"):
                P = K / N
                ert_e = np.where(K > 0, (W @ ev_b) / K, np.nan)
                ert_s = np.where(K > 0, (W @ sc_b) / K, np.nan)
            q = lambda v: (np.nanpercentile(v, 2.5), np.nanpercentile(v, 97.5)) if np.isfinite(v).any() else (np.nan, np.nan)
            Plo, Phi = q(P); Elo, Ehi = q(ert_e); Slo, Shi = q(ert_s)
            rows.append(dict(refSolver=SOLVERS[int(r)], mziSolver=SOLVERS[int(m)], delta_dB=dB, delta=tau, blocks=nb,
                             P=float(ok.sum() / n_b.sum()), P_lo=Plo, P_hi=Phi,
                             ERT_evals_lo=Elo, ERT_evals_hi=Ehi, ERT_seconds_lo=Slo, ERT_seconds_hi=Shi,
                             frac_replicates_with_no_success=float(np.mean(K == 0))))
    return pd.DataFrame(rows)

def stage_tables(df, plan):
    rows = []
    for stage, solver_col, exit_col, ev_col, sec_col, present in (
            ("stage1", "refSolver", "ref_exit", "ref_evals", "ref_seconds", "ref_present"),
            ("stage2", "mziSolver", "mzi_exit", "mzi_evals", "mzi_seconds", "mzi_present")):
        for s, sub in df[df[present]].groupby(solver_col):
            row = dict(stage=stage, solver=SOLVERS[int(s)], n=len(sub), mean_evals=sub[ev_col].mean(),
                       median_evals=sub[ev_col].median(), mean_seconds=sub[sec_col].mean(),
                       median_seconds=sub[sec_col].median())
            for flag in (-1, 0, 1):
                row[f"exit_{flag}"] = int((sub[exit_col] == flag).sum())
            if stage == "stage1" and "s1_gap_to_baseline" in sub:
                row["mean_gap_to_convex_baseline"] = sub.s1_gap_to_baseline.mean()
                row["median_gap_to_convex_baseline"] = sub.s1_gap_to_baseline.median()
            if stage == "stage2":
                g = sub[sub.group_stage2_count == 6]
                for t2 in plan["stage2_gap_tolerances"]:
                    row[f"stage2_within_{t2:g}_of_group_best"] = float((g.stage2_gap_to_group_best <= t2).mean()) if len(g) else np.nan
            rows.append(row)
    return pd.DataFrame(rows)

def profiles(df, plan):
    pg = plan["profile_grid_delta"]
    grid = np.geomspace(pg["min"], pg["max"], pg["points"])
    rows = []
    for (r, m), sub in df.groupby(["refSolver", "mziSolver"]):
        ex = np.where(sub.both_valid, sub.delta, np.inf)
        tc, ts = sub.total_evals.sum(), sub.total_seconds.sum()
        for tau in grid:
            k = int(np.sum(ex <= tau))
            rows.append(dict(refSolver=SOLVERS[int(r)], mziSolver=SOLVERS[int(m)], delta=tau,
                             delta_dB=20.0 * np.log10(tau), P=k / len(sub),
                             ERT_evals=tc / k if k else np.nan, ERT_seconds=ts / k if k else np.nan))
    return pd.DataFrame(rows)

def attainability(df):
    ok = df[df.E.notna() & df.both_valid]
    g = ok.groupby(["order", "ratio", "seed"]).agg(n=("E", "size"), bound=("E_bound", "first"), best_E=("E", "min"),
                                                  median_E=("E", "median"))
    g["best_excess"] = g.best_E - g.bound
    g["median_excess"] = g.median_E - g.bound
    g["best_delta"] = np.sqrt(np.maximum(g.best_E ** 2 - g.bound ** 2, 0.0))
    g["best_delta_dB"] = 20.0 * np.log10(g.best_delta.where(g.best_delta > 0))
    g["median_delta"] = np.sqrt(np.maximum(g.median_E ** 2 - g.bound ** 2, 0.0))
    return g.reset_index()

# ----------------------------------------------------------------------------- validation
def validate(df, expect_trials, plan, checkpoint_dir=None, allow_partial=False):
    lines, bad = [], 0
    def chk(name, ok, detail=""):
        nonlocal bad
        lines.append(("PASS  " if ok else "FAIL  ") + name + (("  -- " + detail) if detail else ""))
        bad += 0 if ok else 1
    chk("global IDs unique", df.gid.is_unique)
    if expect_trials:
        full = len(df) == expect_trials
        if allow_partial and len(df) < expect_trials:
            lines.append(f"WARN  coverage: {len(df)} of {expect_trials} planned trials present -- partial run: every number is a diagnostic, not a result")
        else:
            chk(f"coverage: {len(df)} of {expect_trials} planned trials present", full,
                "partial run: every number is a diagnostic, not a result" if len(df) < expect_trials else "")
    rt = df[df.E.notna() & df.E_saved.notna()]
    d = (rt.E - rt.E_saved).abs().max() if len(rt) else np.nan
    chk("recomputed end-to-end error equals the program's own value (all returned designs)", d < 1e-12,
        f"max |diff| = {d:.2e} over {len(rt)} trials")
    below = (df.E - df.E_bound).min()
    chk("no error below its half-band bound", below >= -1e-12, f"smallest margin = {below:.2e}")
    chk("half-band identity: DC = 1/2 on every returned matrix", df.hb_dc_dev.max() < 1e-12, f"max dev = {df.hb_dc_dev.max():.2e}")
    chk("half-band identity: even-lag coefficients vanish", df.hb_even_dev.max() < 1e-12, f"max = {df.hb_even_dev.max():.2e}")
    dd = df.delta[df.E.notna()]
    chk("delta = sqrt(E^2 - bound^2) is finite on every returned design", bool(np.isfinite(dd).all()))
    s = df[df.legacy_success]
    if len(s):
        chk("legacy success implies a recorded error", s.E_saved.notna().all())
    n_noret = int((~df.mzi_present).sum())
    lines.append(f"INFO  trials without a Stage-2 result: {n_noret}; of which infrastructure failures: {int((df.infra_failure & ~df.mzi_present).sum())}")
    ids = df[~df.mzi_present].groupby("failureIdentifier").size()
    for k_, v_ in ids.items():
        lines.append(f"INFO    failure identifier '{k_ or '(none)'}': {v_}")
    if checkpoint_dir:
        try:
            import scipy.io as sio
            files = sorted(glob.glob(os.path.join(checkpoint_dir, "trial_*.mat")))
            md = 0.0; me = 0.0; n = 0
            idx = df.set_index("gid")
            for f in files:
                cp = sio.loadmat(f, struct_as_record=False, squeeze_me=True)["checkpoint"]
                gid = int(cp.globalId)
                if gid in idx.index and bool(cp.success):
                    md = max(md, abs(float(cp.error) - idx.at[gid, "E"]))
                    me = max(me, abs(float(cp.evaluations) - idx.at[gid, "total_evals"]))
                    n += 1
            chk("cross-source: MAT checkpoints agree with recomputed E and evaluations on successes",
                md < 1e-12 and me == 0, f"{n} successes compared; max E diff {md:.2e}; max evals diff {me:.0f}")
        except Exception as exc:                                  # pragma: no cover
            lines.append(f"WARN  checkpoint cross-check skipped: {exc}")
    return lines, bad

# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="+", help="directories holding live trial records (JSON per trial, or JSONL/JSONL.GZ)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--plan", help="analysis plan JSON (defaults are written to OUT/analysis_plan_used.json)")
    ap.add_argument("--checkpoints", help="optional MAT checkpoint directory for cross-validation")
    ap.add_argument("--expect-trials", type=int, default=0)
    ap.add_argument("--duplicates", choices=["error", "first", "last"], default=None)
    ap.add_argument("--allow-partial", action="store_true", help="a short coverage count is reported as WARN, not FAIL (use for interim looks)")
    ap.add_argument("--skip-baseline", action="store_true", help="skip the convex Stage-1 baseline")
    a = ap.parse_args()
    plan = dict(DEFAULT_PLAN)
    if a.plan:
        plan.update(json.load(open(a.plan, "r", encoding="utf-8")))
    if a.duplicates:
        plan["duplicate_policy"] = a.duplicates
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    df, dups = load_trials(a.sources, plan["duplicate_policy"])
    if df.empty:
        raise SystemExit("No trial records found under: %s" % a.sources)
    df = add_derived(df, plan)
    if not a.skip_baseline:
        base = {}
        for (o, r) in df[["order", "ratio"]].drop_duplicates().itertuples(index=False):
            base[(o, r)] = stage1_baseline(o, r, plan["baseline_grid_points"])
        bdf = pd.DataFrame([dict(order=o, ratio=r, baseline_lower=v[0], baseline_upper=v[1], baseline_violation=v[2],
                                 baseline_feasible=v[3], baseline_solver_ok=v[4]) for (o, r), v in base.items()])
        bdf.to_csv(os.path.join(a.out, "stage1_convex_baseline.csv"), index=False)
        df = df.merge(bdf[["order", "ratio", "baseline_lower", "baseline_upper"]], on=["order", "ratio"], how="left")
        df["s1_gap_to_baseline"] = df.ref_objective - df.baseline_lower
    lines, bad = validate(df, a.expect_trials, plan, a.checkpoints, a.allow_partial)
    if not a.skip_baseline:
        neg = (df.s1_gap_to_baseline < -1e-6).sum()
        lines.append(("PASS  " if neg == 0 else "FAIL  ") + "no Stage-1 solver beats the convex lower bound (tolerance 1e-6)" +
                     f"  -- violations: {int(neg)}")
        bad += 0 if neg == 0 else 1
        lines.append(f"INFO  convex baseline: max grid-relaxation violation {bdf.baseline_violation.max():.2e}; "
                     f"all shifted solutions feasible: {bool(bdf.baseline_feasible.all())}; "
                     f"max upper-lower gap {(bdf.baseline_upper - bdf.baseline_lower).max():.2e}")
    df.to_csv(os.path.join(a.out, "trial_table.csv"), index=False)
    pair_tables(df, plan).to_csv(os.path.join(a.out, "pair_summary.csv"), index=False)
    bootstrap_ci(df, plan).to_csv(os.path.join(a.out, "pair_bootstrap_ci.csv"), index=False)
    stage_tables(df, plan).to_csv(os.path.join(a.out, "stage_summary.csv"), index=False)
    profiles(df, plan).to_csv(os.path.join(a.out, "tolerance_profiles.csv"), index=False)
    attainability(df).to_csv(os.path.join(a.out, "cell_attainability.csv"), index=False)
    df[~df.mzi_present | df.failureIdentifier.ne("")][["gid", "order", "ratio", "seed", "trial", "refSolver", "mziSolver",
        "status", "failureStage", "failureIdentifier", "failureMessage", "infra_failure",
        "numeric_exception", "cost_incomplete"]].to_csv(
        os.path.join(a.out, "exceptions.csv"), index=False)
    if dups:
        pd.DataFrame(dups, columns=["gid", "kept_or_first_file", "other_file"]).to_csv(os.path.join(a.out, "duplicates.csv"), index=False)
    json.dump(plan, open(os.path.join(a.out, "analysis_plan_used.json"), "w"), indent=2)
    me = hashlib.sha256(open(__file__, "rb").read()).hexdigest()
    plan_hash = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    header = [f"fpf_analysis report  ({time.strftime('%Y-%m-%d %H:%M:%S')}, {time.time() - t0:.1f}s)",
              f"trials loaded: {len(df)}   script sha256: {me[:16]}   plan sha256: {plan_hash[:16]}", ""]
    open(os.path.join(a.out, "validation_report.txt"), "w", encoding="utf-8").write("\n".join(header + lines) + "\n")
    print("\n".join(header + lines))
    print(f"\nwrote tables to {a.out}")
    sys.exit(1 if bad else 0)

if __name__ == "__main__":
    main()
