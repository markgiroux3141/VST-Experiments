"""A transformer's datasheet figures measured on its test circuit (docs/CHAINS_PLAN.md WP4).

The circuit is a manufacturer's test circuit as a circuit file: a source resistance
`r_source_ohm` from `in` to the primary's terminal `p`, the secondary's terminal `out`
(both probed), e.g. config/circuits/jt115k_test.yaml (Jensen's test circuit 1). Levels are
set at the primary's terminals, as Jensen's sheets have them ("all levels are input");
`emf_db` is the response from the source's EMF (a bandwidth figure includes the source's
loading), `gain_db` from the primary's terminals. Tones are fitted by least squares on
whole periods after a faded-in settle (the core starts demagnetized).
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from varimu.circuit import builder, spec
from varimu.sim import fast
from varimu.sim.io import TransientSettings

DBU_V = 0.7746


def _tone(circuit, overrides, f: float, emf_rms: float, periods: int) -> tuple:
    st = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = st.sample_rate
    n_settle = int(max(0.3, 3 / f) * fs)
    t = np.arange(n_settle + int(round(periods * fs / f))) / fs
    fade = np.clip(t / (0.5 * n_settle / fs), 0, 1)
    x = emf_rms * np.sqrt(2) * np.sin(2 * np.pi * f * t) * fade
    ir = builder.build_ir(circuit, spec.resolve(circuit, dict(overrides)))
    r = fast.run_transient(ir, x, settings=st)
    sl = slice(n_settle, None)
    return t[sl], x[sl], r.vectors["v(p)"][sl], r.vectors["v(out)"][sl]


def _phasors(t, y, f: float, harmonics: int) -> np.ndarray:
    cols = []
    for k in range(1, harmonics + 1):
        cols += [np.sin(2 * np.pi * k * f * t), np.cos(2 * np.pi * k * f * t)]
    a = np.linalg.lstsq(np.array(cols).T, y, rcond=None)[0]
    return a[0::2] + 1j * a[1::2]


def measure(
    circuit, overrides: Mapping[str, float], f: float, level_dbu: float = -20.0, periods: int = 6
) -> dict:
    """At `level_dbu` on the primary's terminals and `f`: `gain_db` (out / primary),
    `emf_db` (out / EMF), `zin_ohm` (the primary's input impedance) and `thd` (the
    output's, fraction; harmonics to the 9th below 5 kHz, none above)."""
    r_src = spec.resolve(circuit, dict(overrides))["r_source_ohm"]
    h = 9 if f < 5000 else 1
    want = DBU_V * 10 ** (level_dbu / 20)
    emf = want * 1.1
    for _ in range(2):
        t, x, p, o = _tone(circuit, overrides, f, emf, periods)
        emf *= want / (abs(_phasors(t, p, f, 1)[0]) / np.sqrt(2))
    t, x, p, o = _tone(circuit, overrides, f, emf, periods)
    cx, cp, co = (_phasors(t, y, f, h) for y in (x, p, o))
    return {
        "gain_db": float(20 * np.log10(abs(co[0]) / abs(cp[0]))),
        "emf_db": float(20 * np.log10(abs(co[0]) / abs(cx[0]))),
        "zin_ohm": float(abs(cp[0] / ((cx[0] - cp[0]) / r_src))),
        "thd": float(np.sqrt(np.sum(np.abs(co[1:]) ** 2)) / abs(co[0])),
    }


def response_db(circuit, overrides: Mapping[str, float], f: float, ref_hz: float = 1000.0) -> float:
    """The response from the source's EMF at `f`, re `ref_hz`, at -20 dBu (dB)."""
    return measure(circuit, overrides, f)["emf_db"] - measure(circuit, overrides, ref_hz)["emf_db"]
