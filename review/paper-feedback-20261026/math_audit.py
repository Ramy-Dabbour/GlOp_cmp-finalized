"""Independent numerical checks of formulas in the existing MATLAB model.

This does not load MATLAB, optimize a benchmark trial, or modify source/results.
"""
import json
from pathlib import Path

import numpy as np
from numpy.polynomial.chebyshev import Chebyshev


def transfer(theta, phi):
    m = len(theta)
    degree = 2 * m - 1
    a = np.zeros((2, 2, degree + 1), complex)
    a[:, :, 0] = np.eye(2)
    phase_pattern = ((m - np.arange(1, m + 1)) % 2) * (phi % 1)
    for index in range(m):
        d = 2 if index < m - 1 else 1
        t = np.cos(2 * np.pi * theta[index])
        k = np.sin(2 * np.pi * theta[index])
        phase = np.exp(-2j * np.pi * phase_pattern[index])
        b = np.zeros_like(a)
        b[0, 0, d] = phase * t
        b[0, 1, 0] = 1j * k
        b[1, 0, d] = phase * 1j * k
        b[1, 1, 0] = t
        product = np.zeros_like(a)
        for row in range(2):
            for column in range(2):
                for inner in range(2):
                    product[row, column] += np.convolve(
                        a[row, inner], b[inner, column]
                    )[:degree + 1]
        a = product
    q = np.sqrt(0.5) * np.array([[1, 1j], [1j, 1]])
    return np.einsum("ikn,kj->ijn", a, q)


def lag_rows(a):
    rows = []
    for v in a.reshape(4, -1):
        centered = np.convolve(v, v[::-1].conj())
        rows.append(np.r_[centered[len(v) - 1:], centered[:len(v) - 1]])
    return np.array(rows)


def target_rows(t, degree):
    g = np.zeros(2 * degree + 1)
    g[0] = t[0]
    g[1:len(t)] = t[1:] / 2
    g[-(len(t) - 1):] = t[1:][::-1] / 2
    h = -g
    h[0] += 1
    return np.array([g, h, h, g])


def main():
    rng = np.random.default_rng(20261026)
    checks = {name: 0.0 for name in [
        "maximum_dc_deviation_from_one_half",
        "maximum_even_lag_magnitude",
        "maximum_power_complementarity_residual",
        "maximum_halfband_frequency_residual",
        "maximum_parseval_relative_discrepancy",
        "maximum_floor_decomposition_discrepancy",
    ]}
    minimum_bound_margin = np.inf
    table = []
    for rho in [0.2, 0.3, 0.4, 0.5]:
        for n in range(4, 13):
            t = np.r_[rho, 2 * rho * np.sinc(rho * np.arange(1, n + 1))]
            c = Chebyshev(t)
            roots = c.deriv().roots()
            roots = roots[np.isreal(roots) & (roots.real >= -1) & (roots.real <= 1)].real
            values = c(np.r_[-1, 1, roots])
            denominator_squared = 2 * (rho**2 + (1 - rho)**2 + np.dot(t[1:], t[1:]))
            forced_squared = 4 * (0.5 - rho)**2 + 2 * np.dot(t[2::2], t[2::2])
            bound = np.sqrt(forced_squared / denominator_squared)
            # Constructive admissible degree-N response, not a claim of optimality.
            low, high = min(values), max(values)
            affine = t / (high - low)
            affine[0] = (rho - low) / (high - low)
            difference = affine - t
            affine_e = np.sqrt((4 * difference[0]**2 + 2 * np.dot(difference[1:], difference[1:])) / denominator_squared)
            affine_j1 = np.linalg.norm(difference) / np.linalg.norm(t)
            table.append(dict(N=n, rho=rho, raw_min=float(min(values)),
                              raw_max=float(max(values)), topology_E_lower_bound=float(bound),
                              admissible_affine_response_E=float(affine_e),
                              admissible_affine_response_J1=float(affine_j1)))
            for _ in range(3):
                a = transfer(rng.random(n + 1), rng.random())
                rows = lag_rows(a)
                degree = 2 * n + 1
                target = target_rows(t, degree)
                g = rows[0]
                delta = np.zeros(len(g))
                delta[0] = 1
                err = np.linalg.norm(rows - target) / np.linalg.norm(target)
                remaining_odd = 8 * np.sum(np.abs(g[1:degree + 1:2] - target[0, 1:degree + 1:2])**2)
                decomposed = (forced_squared + remaining_odd) / denominator_squared
                w = 2 * np.pi * np.arange(256) / 256
                fields = np.einsum("ijn,nw->ijw", a, np.exp(1j * np.outer(np.arange(degree + 1), w)))
                power = np.abs(fields.reshape(4, -1))**2
                target_power = np.einsum("rn,nw->rw", target, np.exp(1j * np.outer(
                    np.r_[0:degree + 1, -degree:0], w))).real
                spectral_error = np.sqrt(np.sum((power - target_power)**2) / np.sum(target_power**2))
                checks["maximum_dc_deviation_from_one_half"] = max(checks["maximum_dc_deviation_from_one_half"], float(np.max(np.abs(rows[:, 0] - 0.5))))
                checks["maximum_even_lag_magnitude"] = max(checks["maximum_even_lag_magnitude"], float(np.max(np.abs(rows[:, 2:degree + 1:2]))))
                checks["maximum_power_complementarity_residual"] = max(checks["maximum_power_complementarity_residual"], float(np.max(np.abs(rows - np.array([g, delta - g, delta - g, g])))))
                checks["maximum_halfband_frequency_residual"] = max(checks["maximum_halfband_frequency_residual"], float(np.max(np.abs(power[:, :128] + power[:, 128:] - 1))))
                checks["maximum_parseval_relative_discrepancy"] = max(checks["maximum_parseval_relative_discrepancy"], float(abs(spectral_error - err)))
                checks["maximum_floor_decomposition_discrepancy"] = max(checks["maximum_floor_decomposition_discrepancy"], float(abs(err**2 - decomposed)))
                minimum_bound_margin = min(minimum_bound_margin, err - bound)
    result = dict(description="Independent NumPy transcription of the existing MATLAB transfer matrix; numerical checks support the algebraic proof, not formal certification.",
                  random_lattice_designs_checked=108, checks=checks,
                  minimum_observed_E_minus_topology_bound=float(minimum_bound_margin),
                  target_and_bound_table=table)
    output = Path(__file__).with_name("math_audit_results.json")
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "target_and_bound_table"}, indent=2))
    print("N,rho,topology_E_lower_bound")
    for row in table:
        if row["N"] in [4, 10, 12]:
            print(f'{row["N"]},{row["rho"]},{row["topology_E_lower_bound"]:.10f}')


if __name__ == "__main__":
    main()
