"""The two-core saturable reactor (tube synth S1, docs/TUBE_SYNTH_PLAN.md) in circuitsim.

config/circuits/saturable_reactor.yaml: the signal source Vs -- RS -- the signal windings
of cores A and B in series -- ground; the control supply Vc -- RC -- the control windings
in anti-series (A's from c1 to c2, B's reversed from c2 to ground). With the winding
resistances folded into R = RS + 2 r_sig and Rc = RC + 2 r_ctl, the eddy-current
capacitance on each core node as Ke B' of magnetomotive force and no gap or leakage (the
file has none), the circuit is

    R i_s + Ns A (B_A' + B_B') = Vs        Ns i_s + Nc i_c = l H_A + Ke B_A'
    Rc i_c + Nc A (B_A' - B_B') = Vc       Ns i_s - Nc i_c = l H_B + Ke B_B'

a constant linear map from (H_A, H_B, Vs, Vc) to (i_s, i_c, B_A', B_B'), with each H the
JA path of its core (H' = dH/dB B'). It is solved here exactly, like the single-core
circuits of tests/test_circuitsim_core.py: DOP853 at rtol 1e-11, each core's reversals
located as events. The run starts at the DC operating point, where each core sits on its
initial curve at H = +-Nc Vc / (Rc l) (checked first).

Also, against the core alone (varimu.synth.reactor): the inductance the signal sees is the
cores' incremental permeability at the bias, and the control circuit carries only even
harmonics of the signal (by symmetry: B_A - B_B is even in the signal).
"""

import dataclasses
from pathlib import Path

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR
from varimu.devices.core import DEMAGNETIZED, MU0, TESLA_PER_V, core_model
from varimu.sim import fast, io
from varimu.synth.reactor import current_driven_permeability

pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")

from engine_compare import FS  # noqa: E402

CIRCUIT = CONFIG_DIR / "circuits" / "saturable_reactor.yaml"
DUR_S = 0.1


@dataclasses.dataclass(frozen=True)
class Reactor:
    """The circuit's numbers for the reference, from the circuit file."""

    ns: float
    nc: float
    area_m2: float
    path_m: float
    r_ohm: float  # signal loop
    rc_ohm: float  # control loop
    rs_ohm: float  # the signal source's resistance (RS), part of r_ohm
    rc_feed_ohm: float  # the control feed (RC), part of rc_ohm
    ke: float  # eddy magnetomotive force per T/s
    material: str

    def core(self):
        return core_model("JA", self.material, self.path_m)

    def bias_a_per_m(self, control_v):
        return self.nc * control_v / (self.rc_ohm * self.path_m)

    def control_v_for(self, h_a_per_m):
        return h_a_per_m * self.rc_ohm * self.path_m / self.nc


def load(control_v=0.0, **overrides):
    """(circuit IR, Reactor) at the control voltage (and other parameter overrides)."""
    s = spec.load_circuit(Path(CIRCUIT))
    p = spec.resolve(s, {"control_v": control_v, **overrides})
    ir = builder.build_ir(s, p)
    els = {e.name: e for e in ir.elements()}
    assert {"XTA_CORE", "XTB_CORE"} <= set(els) and "RTA_gap" not in els
    assert not any(n.endswith("_lk") for n in els), "the reference has no leakage"
    r = Reactor(
        ns=els["LTA_sig"].turns,
        nc=els["LTA_ctl"].turns,
        area_m2=els["LTA_sig"].area_m2,
        path_m=p["core_path_m"],
        r_ohm=els["RS"].r_ohm + els["RTA_sig"].r_ohm + els["RTB_sig"].r_ohm,
        rc_ohm=els["RC"].r_ohm + els["RTA_ctl"].r_ohm + els["RTB_ctl"].r_ohm,
        rs_ohm=els["RS"].r_ohm,
        rc_feed_ohm=els["RC"].r_ohm,
        ke=els["CTA_eddy"].c_f / TESLA_PER_V,
        material="mumetall",
    )
    assert els["CTB_eddy"].c_f == els["CTA_eddy"].c_f
    return ir, r


def settings(converged=False):
    s = io.TransientSettings.from_sim_settings(engine="circuitsim")
    s = dataclasses.replace(s, full_scale_volts_peak=1.0)
    if converged:
        s = dataclasses.replace(
            s, oversample=8, error_abstol=s.error_abstol / 10, error_reltol=s.error_reltol / 10
        )
    return s


def drive(t, amp):
    """50 Hz ramped from 0 to `amp` over the first 60 ms, plus 1 kHz at amp / 20."""
    ramp = np.minimum(1.0, t / 0.06)
    return amp * (ramp * np.sin(2 * np.pi * 50 * t) + 0.05 * np.sin(2 * np.pi * 1000 * t))


def dc_state(core, h_a_per_m, tol_t=1e-12):
    """B, H where the initial curve reaches |H| = h (sign of h): l H = Nc i_c at DC."""
    if h_a_per_m == 0:
        return 0.0, 0.0
    lo, hi = 0.0, 1.5
    while hi - lo > tol_t:
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if core.h_of_b(mid, DEMAGNETIZED)[0] < abs(h_a_per_m) else (lo, mid)
    b = 0.5 * (lo + hi)
    h = core.h_of_b(b, DEMAGNETIZED)[0]
    return (b, h) if h_a_per_m > 0 else (-b, -h)


def reference(r: Reactor, control_v, amp, t_out):
    """The exact solution (module docstring): v(s), v(c1), B_A, B_B on t_out."""
    core = r.core()
    na, nc = r.ns * r.area_m2, r.nc * r.area_m2
    m = np.array(
        [
            [r.r_ohm, 0.0, na, na],
            [0.0, r.rc_ohm, nc, -nc],
            [r.ns, r.nc, -r.ke, 0.0],
            [r.ns, -r.nc, 0.0, -r.ke],
        ]
    )
    minv = np.linalg.inv(m)

    def unknowns(t, y):
        return minv @ np.array([drive(t, amp), control_v, r.path_m * y[1], r.path_m * y[3]])

    h_dc = r.bias_a_per_m(control_v)
    ba, ha = dc_state(core, h_dc)
    bb, hb = dc_state(core, -h_dc)
    y0 = np.array([ba, ha, bb, hb])
    x = unknowns(1e-7, y0)
    deltas = [1.0 if x[2] >= 0 else -1.0, 1.0 if x[3] >= 0 else -1.0]
    out = np.zeros((4, len(t_out)))
    t0 = 0.0
    while t0 < t_out[-1]:
        da, db = deltas

        def rhs(t, y, da=da, db=db):
            _, _, bad, bbd = unknowns(t, y)
            return [bad, core.dh_db(y[0], y[1], da) * bad, bbd, core.dh_db(y[2], y[3], db) * bbd]

        def rev_a(t, y, da=da):
            return unknowns(t, y)[2] + da * 1e-12

        def rev_b(t, y, db=db):
            return unknowns(t, y)[3] + db * 1e-12

        rev_a.terminal, rev_a.direction = True, -da
        rev_b.terminal, rev_b.direction = True, -db
        sol = solve_ivp(rhs, (t0, t_out[-1]), y0, method="DOP853", events=(rev_a, rev_b),
                        dense_output=True, rtol=1e-11, atol=[1e-13, 1e-9, 1e-13, 1e-9])  # fmt: skip
        k = (t_out >= t0) & (t_out <= sol.t[-1])
        if k.any():
            out[:, k] = sol.sol(t_out[k])
        if sol.status != 1:
            break
        if sol.t_events[0].size:
            deltas[0] = -deltas[0]
        if sol.t_events[1].size:
            deltas[1] = -deltas[1]
        t0, y0 = sol.t[-1] + 1e-13, sol.y[:, -1]
    xs = np.array([unknowns(t, y) for t, y in zip(t_out, out.T, strict=True)])
    return {
        "s": drive(t_out, amp) - xs[:, 0] * r.rs_ohm,
        "c1": control_v - xs[:, 1] * r.rc_feed_ohm,
        "b_a": out[0],
        "b_b": out[2],
    }


def err_db(a, b):
    return 20 * np.log10(np.std(a - b) / np.std(b))


def test_dc_point_is_the_initial_curve():
    """circuitsim's DC operating point puts each core on its initial curve (the core-alone
    measurement's starting point), at opposite bias."""
    for control_v in (5.0, 50.0, 100.0):
        ir, r = load(control_v)
        v = fast.run_transient(ir, np.zeros(96), settings=settings()).vectors
        b, _ = dc_state(r.core(), r.bias_a_per_m(control_v))
        ba, bb = v["v(ta_core)"][0] * TESLA_PER_V, v["v(tb_core)"][0] * TESLA_PER_V
        print(control_v, b, ba, bb)
        assert abs(ba - b) < 1e-7 and abs(bb + b) < 1e-7


# (control V, drive amplitude V): the Rayleigh region unbiased; biased with one core
# pulled back through zero; both cores driven into saturation in turn
CASES = {
    "unbiased_small": (0.0, 2.0),
    "biased": (50.0, 150.0),
    "saturating": (100.0, 400.0),
}
# Bounds, rms dB re signal (production, converged), and B (converged, T): a few dB
# outside the values measured 2026-10-29 (v(s) / v(c1), production / converged):
# unbiased -90.3 / -89.0 (c1 roundoff); biased -69.0 / -73.2, c1 -78.3 / -83.3, B within
# 1.1e-4 T; saturating -55.5 / -71.4, c1 -64.9 / -77.3, B within 3.3e-4 T.
# Unlike the single-core circuits (-88..-95 dB), the reactor is current-driven (10 kOhm
# into 2 x 500 turns), so through the steep middle of mumetall's loop (mu up to 250,000) a
# small error in H is a large one in B. The converged runs plateau there whatever the
# step (oversample 8..32, error tolerances / 10..100: -71.4..-70.5 dB): what is left is
# the core device's path integration (its RK4 substeps), not the time step. Production
# adds step error where a core leaves saturation (-55.5 dB driven hard into it).
BOUNDS = {
    "unbiased_small": (-85.0, -85.0, 1e-4),
    "biased": (-65.0, -70.0, 3e-4),
    "saturating": (-52.0, -68.0, 1e-3),
}


@pytest.fixture(scope="module")
def runs():
    t = np.arange(int(DUR_S * FS)) / FS
    out = {}
    for name, (control_v, amp) in CASES.items():
        ir, r = load(control_v)
        x = drive(t, amp)
        out[name] = (
            fast.run_transient(ir, x, settings=settings()).vectors,
            fast.run_transient(ir, x, settings=settings(converged=True)).vectors,
            reference(r, control_v, amp, t),
        )
    return out


@pytest.mark.parametrize("name", list(CASES))
def test_circuitsim_agrees_with_the_exact_solution(runs, name):
    prod, conv, ref = runs[name]
    rows = []
    for p in ("s", "c1"):
        if CASES[name][0] == 0 and p == "c1":
            # Unbiased, the cores are identical and the control circuit carries nothing:
            # both solutions are roundoff there, so check circuitsim's is.
            for v in (prod, conv):
                assert np.std(v["v(c1)"]) < 1e-6 * np.std(ref["s"])
            continue
        rows.append((p, err_db(prod[f"v({p})"], ref[p]), err_db(conv[f"v({p})"], ref[p])))
    b_err = max(
        np.max(np.abs(conv["v(ta_core)"] * TESLA_PER_V - ref["b_a"])),
        np.max(np.abs(conv["v(tb_core)"] * TESLA_PER_V - ref["b_b"])),
    )
    print(name, rows, f"B (converged) within {b_err:.2e} T",
          f"B_A {ref['b_a'].min():.3f}..{ref['b_a'].max():.3f} T")  # fmt: skip
    prod_db, conv_db, b_max = BOUNDS[name]
    for p, e_prod, e_conv in rows:
        assert e_conv < conv_db, (p, e_conv)
        assert e_prod < prod_db, (p, e_prod)
    assert b_err < b_max


def sine_fit(x, f_hz, t):
    """Complex amplitude of x's component at f_hz (least squares with an offset)."""
    a = np.column_stack(
        [np.cos(2 * np.pi * f_hz * t), np.sin(2 * np.pi * f_hz * t), np.ones_like(t)]
    )
    c, s, _ = np.linalg.lstsq(a, x, rcond=None)[0]
    return c - 1j * s


F_HZ = 100.0
CYCLE = int(FS / F_HZ)


def tone_run(control_v, amp_v, cycles=10, **overrides):
    ir, r = load(control_v, **overrides)
    t = np.arange(cycles * CYCLE) / FS
    x = amp_v * np.sin(2 * np.pi * F_HZ * t)
    v = fast.run_transient(ir, x, settings=settings()).vectors
    return r, t, x, v


RS_CURRENT_OHM = 1.0e6  # a signal source that makes the drive a current (>> omega L)


def current_amp_v(r, ripple_t):
    """The drive amplitude for ~ripple_t pp at the unbiased permeability, from 1 MOhm."""
    h_pp = ripple_t / (MU0 * 29_000)
    return 0.5 * h_pp * r.path_m / r.ns * RS_CURRENT_OHM


def test_unbiased_inductance_is_the_cores_permeability():
    """Unbiased and driven by current (100 Hz, ~0.5 mT pp), the signal windings' inductance
    is 2 mu0 mu Ns^2 A / l with mu the core alone's under the same H swing."""
    _, r = load()
    cycles = 12
    r, t, x, v = tone_run(0.0, current_amp_v(r, 0.5e-3), cycles, r_signal_ohm=RS_CURRENT_OHM)
    last = slice((cycles - 1) * CYCLE, None)
    vs = sine_fit(v["v(s)"][last], F_HZ, t[last])
    i = sine_fit((x - v["v(s)"])[last] / r.rs_ohm, F_HZ, t[last])
    l_meas = (vs / i).imag / (2 * np.pi * F_HZ)
    h_swing = 2 * r.ns * abs(i) / r.path_m
    _, mu = current_driven_permeability(r.core(), 0.0, h_swing, cycles=cycles)
    l_ref = 2 * MU0 * mu * r.ns**2 * r.area_m2 / r.path_m
    print(f"L {l_meas:.4g} H vs {l_ref:.4g} H ({l_meas / l_ref - 1:+.2%})")
    # measured 2026-10-29: 18.45 H vs 18.48 H (-0.16%)
    assert abs(l_meas / l_ref - 1) < 0.01


def test_settled_inductance_falls_with_bias():
    """Biased and driven by current (100 Hz, ~2 mT pp), each core's loop climbs toward the
    anhysteretic curve for tens of cycles (the JA core's minor loops ratchet: below the
    anhysteretic, rising is irreversible and falling reversible), then settles. The settled
    inductance falls with bias, over a span of a few hundred: the cutoff sweep of S2's
    filter. Measured 2026-10-29 (permeability after 100 / 300 cycles): 29,900 / 29,800 at
    0, 5,030 / 5,060 at 3, 1,600 / 1,620 at 10, 363 / 367 at 30, 49 / 49 at 100 A/m; at
    0.5 mT pp the same climb takes over 300 cycles (docs/TUBE_SYNTH_PLAN.md, S1)."""
    _, r = load()
    cycles = 100
    mus = []
    for h_dc in (0.0, 3.0, 10.0, 30.0, 100.0):
        amp_v = current_amp_v(r, 2e-3)
        control_v = r.control_v_for(h_dc)
        rr, t, x, v = tone_run(control_v, amp_v, cycles, r_signal_ohm=RS_CURRENT_OHM)
        b = v["v(ta_core)"] * TESLA_PER_V
        i = (x - v["v(s)"]) / RS_CURRENT_OHM

        def mu_of(sl, b=b, i=i, rr=rr):
            dh = rr.ns * (i[sl].max() - i[sl].min()) / rr.path_m
            return (b[sl].max() - b[sl].min()) / (MU0 * dh)

        mu = mu_of(slice(-CYCLE, None))
        mu_before = mu_of(slice(-11 * CYCLE, -10 * CYCLE))
        print(f"H {h_dc:5.1f}: mu {mu:7.0f} ({mu / mu_before - 1:+.2%} in the last 10 cycles)")
        assert abs(mu / mu_before - 1) < 0.03, "not settled"
        mus.append(mu)
    assert all(a > b for a, b in zip(mus, mus[1:], strict=False))
    assert 200 < mus[0] / mus[-1] < 2000


def test_control_circuit_carries_only_even_harmonics():
    """Biased at 30 A/m with a 100 Hz signal of ~20 mT pp, the control circuit carries the
    signal's even harmonics; the odd ones cancel."""
    _, r = load()
    r, t, x, v = tone_run(r.control_v_for(30.0), 20.0)
    c1 = v["v(c1)"][5 * CYCLE :]
    spec_ = np.abs(np.fft.rfft(c1 - c1.mean())) / len(c1) * 2
    harm = {k: spec_[5 * k] for k in range(1, 7)}  # 5 cycles: bin 5 k is harmonic k
    s1 = np.abs(np.fft.rfft(v["v(s)"][5 * CYCLE :]))[5] / len(c1) * 2
    b = v["v(ta_core)"][-CYCLE:] * TESLA_PER_V
    print(
        f"ripple {(b.max() - b.min()) * 1e3:.1f} mT; signal fundamental {s1:.3g} V; "
        + ", ".join(f"h{k} {a:.3g} V" for k, a in harm.items())
    )
    odd = max(harm[1], harm[3], harm[5])
    assert harm[2] > 1e-3 * s1  # the reactor's even-harmonic feedthrough is there
    assert odd < 1e-6 * harm[2]
