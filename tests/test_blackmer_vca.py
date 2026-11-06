"""The Blackmer gain cell from our BJTs (scripts/blackmer_cell.py; DEVICE_BUILDER_PLAN.md
B11) in THAT's application circuit, config/circuits/blackmer_vca_test.yaml (GENERATED):
its idle current, its gain law and distortion against the THAT 2180 datasheet
(data/datasheets/that_vca/), and both engines' DC point.

Measured 2026-11-06 at production settings (1 kHz, the datasheet's conditions): 0.0047 %
THD at 0 dBV and unity gain (2180A typ 0.005 %), 0.015 % at -15 dB (sheet at +10 dBV: A
0.02, C max 0.07), 6.20 mV/dB (sheet 6.0-6.2 at T_CHIP 35 C)."""

import subprocess
import sys

import numpy as np
import pytest

from varimu.circuit import builder
from varimu.circuit.spec import load_circuit, resolve
from varimu.config import CONFIG_DIR, REPO_ROOT
from varimu.devices.library import load_device

CIRCUIT = CONFIG_DIR / "circuits" / "blackmer_vca_test.yaml"
FS = 96000.0
TIGHT = "reltol=1e-9 abstol=1e-15 vntol=1e-9"


def _spec():
    return load_circuit(CIRCUIT)


def _build(ec_minus_v: float = 0.0, cores: str = "linear"):
    spec = _spec()
    q = dict(resolve(spec))
    q["ec_minus_v"] = ec_minus_v
    return builder.build(spec, q, cores=cores)


def _fast():
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.sim import fast

    return fast


def test_generated_file_is_current():
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "blackmer_cell.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_passes_the_preflight_checks():
    from varimu import preflight

    assert preflight.check_circuit(_spec()) == []


def _idle_currents(volts: dict[str, float]) -> dict[str, float]:
    """Core collector currents from the internal nodes (c, b, e) of each transistor."""
    import dataclasses

    out = {}
    for k, ref in ((1, "BC550C@1"), (2, "BC550C@1"), (3, "BC560C@1"), (4, "BC560C@1")):
        q = dataclasses.replace(load_device(ref), temp_k=35.0 + 273.15)
        c, b, e = (volts[f"qca{k}_{t}"] for t in "cbe")
        ic, _ = q.currents(c - e, b - e)
        out[f"Q{k}"] = abs(float(ic))
    return out


def _probes(r, names):
    return {n: float(np.asarray(r.vectors[f"v({n})"])[0]) for n in names}


NODES = [f"qca{k}_{t}" for k in (1, 2, 3, 4) for t in "cbe"]


def _with_probes(c):
    import dataclasses

    from varimu.circuit.ir import VoltageProbe

    ir = dataclasses.replace(c.ir, probes=c.ir.probes + tuple(VoltageProbe(n) for n in NODES))
    return ir


def test_idles_at_the_datasheets_current():
    """Each core transistor carries the 2180's 20 uA at idle (the derived bias), within 5%:
    the derivation neglects the collectors' few hundred mV of Early effect."""
    fast = _fast()
    c = _build()
    r = fast.run_transient(_with_probes(c), np.zeros(16))
    ic = _idle_currents(_probes(r, NODES))
    for k, i in ic.items():
        assert i == pytest.approx(20e-6, rel=0.05), (k, i)


def test_dc_point_agrees_with_ngspice():
    """The idle point in both engines (ngspice's native Q at the instances' temp)."""
    fast = _fast()
    from test_bjt import _ngspice

    ngspice = _ngspice()
    c = _build()
    r = ngspice.run(c.text + "vin in 0 dc 0\n", "op", [f"v({n})" for n in NODES], options=TIGHT)
    rs = fast.run_transient(_with_probes(c), np.zeros(16))
    for n in NODES:
        assert float(rs.vectors[f"v({n})"][0]) == pytest.approx(float(r[f"v({n})"][0]), abs=2e-6), n


def _tone(ec_minus_v: float, amp_v: float):
    fast = _fast()
    n = int(FS * 0.1)
    t = np.arange(n) / FS
    x = amp_v * np.sin(2 * np.pi * 1000 * t)
    y = np.asarray(fast.run_transient(_build(ec_minus_v).ir, x).vectors["v(out)"])
    tt, seg = t[n // 2 :], y[n // 2 :]

    def amp(f):
        return 2 * abs(np.mean(seg * np.exp(-2j * np.pi * f * tt)))

    a1 = amp(1000.0)
    thd = np.sqrt(sum(amp(1000.0 * h) ** 2 for h in range(2, 8))) / a1
    return 20 * np.log10(a1 / amp_v), 100 * thd


def test_gain_law_and_distortion():
    """Unity at Ec = 0 within the sheet's +-0.1 dB; the control constant 6.0-6.25 mV/dB
    both ways (sheet 6.0-6.2, gain-control linearity 0.5 % typ, 2 % max); THD at 0 dBV and
    unity under the 2180A's maximum 0.01 %, at -15 dB under the 2180C's 0.07 %."""
    g0, thd0 = _tone(0.0, 1.414)
    assert abs(g0) < 0.1 and thd0 < 0.01, (g0, thd0)
    g_up, _ = _tone(-0.0915, 0.1)
    g_dn, thd_dn = _tone(0.0915, 1.414)
    for g in (g_up, -g_dn):
        assert 91.5 / 6.25 < g < 91.5 / 6.0, (g_up, g_dn)
    assert thd_dn < 0.07, thd_dn
