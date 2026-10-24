"""The 670 slice on the fast engine at production settings (circuit-sim plan, M4).

Production is sim_settings.yaml's `circuitsim` block: esdirk4 at 2x with
5th-order input interpolation and local error control, chosen by the M4
method study (CIRCUIT_SIM_PLAN.md, M4).

- Every excerpt is checked against the engine's converged solution (esdirk4
  at 4x with a 10x tighter error tolerance), with bounds a few dB outside the
  measured values so a regression shows, and inside the plan's tolerance
  (-55 dB rms re signal, CV within 0.2 V).
- Excerpts whose content stays well below 20 kHz are also checked against
  the plan's ngspice reference (gear, reltol 1e-4, 4x) at the plan's
  tolerance. ngspice can't referee HF-rich excerpts: its input is linear
  between samples, which alone is -41 dB off at 20 kHz at 4x, and gear damps
  there. Its tabulated triodes also leave it ~-62 dB rms from the engine's
  converged solution; the exact formulation agrees to -92 dB on the burst
  (measured once; it runs ~7000x slower than real time).

The excerpts are 0.1 s of the test library: the 0 dBFS burst onset at TC1
(the fastest attack), a 0 dBFS sweep section (~600 Hz), a -10 dBFS 19 + 20 kHz
twin tone and a -10 dBFS multitone. The last two exercise frequency warping
near the slice's transformer resonances (35.5 kHz since Phase 2; ~17 kHz
before) and the sidechain rectifying
HF, which the error control is there for. (At 0 dBFS the twin tone drives
that resonance so hard that every setting halves thousands of steps: the
provisional transformer model's limit, not a test.)
"""

import dataclasses

import numpy as np
import pytest

from varimu.circuit import netlist as nl
from varimu.config import load_sim_settings
from varimu.measure import signals
from varimu.sim import fast, io, ngspice

pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")

FS = 96000
BASE = {"input_atten_db": 0.0, "ac_threshold": 0.8}


def _excerpt(name: str) -> tuple[np.ndarray, dict]:
    st = load_sim_settings()
    spec = next(s for s in signals.default_library() if s.name == name)
    sig = signals.render(spec, sample_rate=FS, seed=st.seed)
    if name.startswith("burst"):
        a = sig.meta["burst_start"]
        return sig.samples[a - FS // 50 : a + FS // 12], dict(BASE, time_constant=1)
    mid = len(sig.samples) // 2
    # Faded in over 10 ms: a run starts at the DC operating point with its first
    # input sample, and a 0 dBFS sample there is 13.8 V of DC on T101's primary,
    # which saturates its mumetall core (a start no real input has).
    x = sig.samples[mid : mid + FS // 10].copy()
    n = FS // 100
    x[:n] *= 0.5 - 0.5 * np.cos(np.pi * np.arange(n) / n)
    return x, dict(BASE, time_constant=2)


# name -> (bound vs converged: rms dB, CV V; checked against ngspice too).
# Measured 2026-10-21 with the Phase 2 transformers, production vs converged
# (Jiles-Atherton cores) / vs ngspice (both engines on linear cores) (rms dB, CV V):
#   burst_1000hz_0dbfs  -79.3 / 0.007    -60.1 / 0.026
#   ess_0dbfs           -89.0 / 0.002    -55.7 / 0.098  (ngspice's gear at 0 dBFS)
#   ccif_-10dbfs        -70.8 / 0.058
#   multitone_-10dbfs   -72.6 / 0.015
# (2026-10-15, the slice's linear placeholders: -79.7 / 0.010, -79.6 / 0.009,
# -63.7 / 0.044, -70.5 / 0.010; vs ngspice -61.2 / 0.024, -57.4 / 0.167.)
# Phase 3 (the power supply and idle channel 2 in the circuit, 1 s settling first,
# grid current in the 6973s; 2026-10-21), vs converged: -83.0 / 0.003, -87.5 / 0.001,
# -73.4 / 0.090, -67.4 / 0.033. CCIF's CV difference is at its attack onset (the CV
# drops ~75 V in ~2 ms); the rails agree to mV.
# 2026-10-23 (T103 at 8.5, the tapped AC THRESHOLD pots, the factory-adjusted DC
# threshold): vs converged -81.2 / 0.005, -85.8 / 0.002, -72.2 / 0.012, -74.3 / 0.013;
# vs ngspice -64.0 / 0.007, -60.4 / 0.014.
# 2026-10-24 (mumetall's Rayleigh refit: T101 / T103 cores, and their linear limits
# in the ngspice rows): vs converged -81.6 / 0.005, -86.3 / 0.002, -73.1 / 0.013,
# -74.5 / 0.008; vs ngspice -64.3 / 0.013, -60.4 / 0.013.
EXCERPTS = {
    "burst_1000hz_0dbfs": (-78.0, 0.01, True),
    "ess_0dbfs": (-82.0, 0.005, True),
    "ccif_-10dbfs": (-69.0, 0.03, False),
    "multitone_-10dbfs": (-71.0, 0.03, False),
}


def _err(a: dict, b: dict) -> tuple[float, float]:
    """(output rms error in dB re the signal, worst CV difference in V)."""
    d = np.std(a["v(out)"] - b["v(out)"]) / np.std(b["v(out)"])
    return 20 * np.log10(d), float(np.max(np.abs(a["v(cv)"] - b["v(cv)"])))


@pytest.fixture(scope="module")
def runs():
    """Production and converged circuitsim runs of every excerpt (shared by the tests)."""
    prod = io.TransientSettings.from_sim_settings(engine="circuitsim")
    conv = dataclasses.replace(
        prod,
        oversample=4,
        error_abstol=prod.error_abstol / 10,
        error_reltol=prod.error_reltol / 10,
    )
    out = {}
    for name in EXCERPTS:
        x, ov = _excerpt(name)
        c = nl.build(ov)
        v = x * prod.full_scale_volts_peak
        out[name] = (
            x,
            ov,
            fast.run_transient(c.ir, v, settings=prod).vectors,
            fast.run_transient(c.ir, v, settings=conv).vectors,
        )
    return out


@pytest.mark.parametrize("name", list(EXCERPTS))
def test_production_settings_are_close_to_the_converged_solution(runs, name):
    _, _, prod, conv = runs[name]
    rms_db, cv_v = _err(prod, conv)
    print(f"{name}: {rms_db:.1f} dB, CV {cv_v:.3f} V")
    bound_db, bound_cv, _ = EXCERPTS[name]
    assert rms_db < bound_db and cv_v < bound_cv, f"{rms_db:.1f} dB, CV {cv_v:.3f} V"


@pytest.mark.parametrize("name", [n for n, (_, _, ng) in EXCERPTS.items() if ng])
def test_production_settings_agree_with_the_ngspice_reference(runs, name):
    try:
        ngspice.find_ngspice()
    except ngspice.SimulatorNotFound:
        pytest.skip("ngspice not available")
    # Both engines on the same circuit: the cores in their linear limit (ngspice has
    # no Jiles-Atherton core; decided 2026-10-21).
    x, ov, _, _ = runs[name]
    s = dataclasses.replace(
        io.TransientSettings.from_sim_settings(), method="gear", reltol=1e-4, oversample=4
    )
    c = nl.build(ov, cores="linear")
    cs = io.TransientSettings.from_sim_settings(engine="circuitsim")
    prod = fast.run_transient(c.ir, x * cs.full_scale_volts_peak, settings=cs).vectors
    ref = io.run_transient(
        c.text,
        x * s.full_scale_volts_peak,
        input_node=c.input_node,
        save=list(c.save),
        settings=s,
        files=c.files,
    ).vectors
    rms_db, cv_v = _err(prod, ref)
    print(f"{name}: {rms_db:.1f} dB, CV {cv_v:.3f} V")
    assert rms_db < -55 and cv_v < 0.2, f"{rms_db:.1f} dB, CV {cv_v:.3f} V"
