"""Noise sources against theory (device builder B5's done-when): small test circuits whose
noise spectra have closed forms, run in either engine, read per octave band.

- `johnson`: a resistor across a capacitor, every resistor noisy: S_v = 4kTR / (1 + (f/fc)^2).
- `triode`, `pentode`: a tube with its electrodes on stiff sources, the plate through a
  load R_L, tube noise only: plate current noise into r_p || R_L, S_v = R^2 (S_shot +
  gm^2 K_f / f), S_shot = shot_k gm (a triode) or (Ib / Ik) shot_k (gm + 8 Ic2) (a pentode,
  partition noise), with gm, r_p and the currents from the Python model at the run's
  operating point.

Every density is times the grid's linear interpolation, sinc^4(f / fs)
(varimu.devices.noise.interp_gain).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import numpy as np
from scipy.signal import welch

from varimu.circuit import ir as I
from varimu.circuit import spice
from varimu.devices import noise as nz
from varimu.devices.library import load_device
from varimu.devices.pentode import Pentode
from varimu.devices.triode import Triode

RATE = 96000.0
T_K = 300.0
SEED = 11


@dataclass(frozen=True)
class Case:
    ir: I.CircuitIR
    probe: str
    theory: object  # (f, operating point {node: volts}) -> one-sided V^2/Hz


def johnson(r_ohm: float = 1e5, c_f: float = 1e-9) -> Case:
    els = (
        I.Resistor("RIN", "in", "0", 1e3),
        I.Resistor("R1", "out", "0", r_ohm),
        I.NoiseCurrent("IN_R1", "out", "0", nz.johnson_a2(r_ohm, T_K)),
        I.Capacitor("C1", "out", "0", c_f),
    )
    fc = 1 / (2 * np.pi * r_ohm * c_f)

    def theory(f, op):
        return 4 * nz.K_B * T_K * r_ohm / (1 + (f / fc) ** 2) * nz.interp_gain(f, RATE)

    return Case(_ir("johnson", els, ()), "v(out)", theory)


def _ir(title, els, models) -> I.CircuitIR:
    return I.CircuitIR(
        title=title,
        input_node="in",
        probes=(I.VoltageProbe("out"),),
        models=tuple(models),
        sections=(I.Section("t", tuple(els)),),
        noise=I.NoiseSpec(SEED, RATE),
    )


def tube(device: str, *, vb: float, rl: float, vg: float, vs: float | None = None) -> Case:
    """A tube's plate through `rl` to `vb`, its grid at `vg` (and a pentode's screen at
    `vs`), the cathode grounded; tube noise only (no resistor noise)."""
    m = load_device(device)
    m = _renamed(m, "TUBE")
    pentode = isinstance(m, Pentode)
    els = [
        I.Resistor("RIN", "in", "0", 1e3),
        I.VoltageSource("VB", "b", "0", vb),
        I.Resistor("RL", "b", "out", rl),
        I.VoltageSource("VG", "g", "0", vg),
    ]
    if pentode:
        els.append(I.VoltageSource("VS", "s", "0", vs))
        els.append(I.Device("XV", "TUBE", ("out", "s", "g", "0")))
    else:
        els.append(I.Device("XV", "TUBE", ("out", "g", "0")))
    els.append(
        I.TubeNoise("BN_XV", "XV", nz.shot_k(), nz.PARTITION if pentode else 0.0, nz.FLICKER_V2)
    )

    def theory(f, op):
        vp = op["v(out)"]
        d = 1e-4
        if pentode:
            ip = lambda g, p: float(m.ip(g, vs, p))  # noqa: E731
            ic2 = float(m.ig2(vg, vs))
        else:
            ip = lambda g, p: float(m.ip(g, p))  # noqa: E731
            ic2 = 0.0
        gm = (ip(vg + d, vp) - ip(vg - d, vp)) / (2 * d)
        rp = 2 * d / (ip(vg, vp + d) - ip(vg, vp - d))
        ib = ip(vg, vp)
        r = rp * rl / (rp + rl)
        shot = nz.shot_a2(gm, ib, ic2, nz.PARTITION) if pentode else nz.shot_a2(gm)
        return r**2 * (shot + gm**2 * nz.FLICKER_V2 / f) * nz.interp_gain(f, RATE)

    return Case(_ir(device, els, (m,)), "v(out)", theory)


def _renamed(m: Triode | Pentode, name: str):
    import dataclasses

    return dataclasses.replace(m, name=name)


def run(
    case: Case, seconds: float, engine: str, reference: bool = False, settle_s: float | None = None
) -> np.ndarray:
    """The probe's samples over `seconds` of silence (after the settle). `reference`: ngspice
    as an agreement reference (a timepoint on every sample, steps an eighth of one; see
    varimu.sim.io.run_transient). `settle_s` overrides sim_settings' settle (these circuits
    sit on stiff sources: nothing slow to settle)."""
    from varimu.sim import fast, io

    x = np.zeros(int(seconds * RATE))
    s = io.TransientSettings.from_sim_settings(engine=engine)
    if settle_s is not None:
        s = dataclasses.replace(s, settle_s=settle_s)
    if engine == "circuitsim":
        return fast.run_transient(case.ir, x, settings=s).vectors[case.probe]
    text, files = spice.emit(case.ir, triode_formulation="exact")
    return io.run_transient(
        text,
        x,
        input_node=case.ir.input_node,
        save=(case.probe,),
        settings=s,
        files=files,
        noise=spice.noise_streams(case.ir),
        max_step_div=8 if reference else 1,
        grid_breakpoints=reference,
    ).vectors[case.probe]


def octaves(case: Case, v: np.ndarray, f_lo: float, f_hi: float, nperseg: int = 2**15):
    """Per octave band from f_lo: (band centre, measured / theory in dB, bins)."""
    op = {case.probe: float(np.mean(v))}
    f, s = welch(v - np.mean(v), fs=RATE, nperseg=nperseg)
    out = []
    lo = f_lo
    while lo * 2 <= f_hi:
        sel = (f >= lo) & (f < 2 * lo)
        meas = np.mean(s[sel])
        th = np.mean(case.theory(f[sel], op))
        out.append((lo * np.sqrt(2), 10 * np.log10(meas / th), int(sel.sum())))
        lo *= 2
    return out
