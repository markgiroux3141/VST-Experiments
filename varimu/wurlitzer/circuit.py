"""The reeds into the 200A's electronics (config/circuits/wurlitzer_200a.yaml, WZ2;
docs/WURLITZER_PLAN.md, WZ3).

**The input.** The circuit's plate node `pk` has the reeds' standing capacitance `CREEDS`
(c_reeds_f) from the input `in`. The reeds' changing capacitance C(t) at the plate's
voltage V pushes the current -d(C V)/dt into the plate; to first order (dC ~ 1e-3 of the
plate's capacitance, the signal ~ 1e-3 of V0), -V0 dC/dt, which `in` = -V0 dC / c_reeds_f
gives through CREEDS (the rest, -C_reeds dv/dt, CREEDS gives itself). V0 is the plate's
idle voltage (`plate_v0`: the drawing's +150 V, the circuit's idle 150.0 V).

**The transfer** (`transfer`): the small-signal response from `in` to a probe, measured on
the circuit with a multisine (240 tones, 20 Hz-20 kHz, 20 mV each: the AUX path is linear
there, its harmonics within 0.1 dB of the circuit's own down to -78 dB re a note, WZ3),
cached in cache/wurlitzer/ by the circuit file, the settings and this module. The fit
(scripts/wurlitzer_register_fit.py) filters the reeds' input with it instead of running the
circuit per evaluation; the circuit itself checks the result.
"""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

import numpy as np

from varimu.circuit import builder
from varimu.circuit import spec as cspec
from varimu.circuit.ir import VoltageProbe
from varimu.sim import fast, io
from varimu.wurlitzer import pickup as pk

CIRCUIT = "wurlitzer_200a"
TRANSFER_FS = 96000
TRANSFER_TONES = 240


def _circuit(name: str = CIRCUIT) -> cspec.CircuitSpec:
    return cspec.load_circuit(cspec.circuit_path(name))


def c_reeds_f(name: str = CIRCUIT) -> float:
    return float(cspec.resolve(_circuit(name), {})["c_reeds_f"])


def plate_v0(name: str = CIRCUIT) -> float:
    """The plate's polarizing voltage: the drawing's +150 V at `hv150`, where the circuit
    idles (150.0 V; tests/test_wurlitzer_200a.py holds it within 2%)."""
    return 150.0


def plate_input_v(dc_f: np.ndarray, name: str = CIRCUIT) -> np.ndarray:
    """The circuit's input `in` (volts) for the reeds' capacitance change dc_f."""
    return -plate_v0(name) * np.asarray(dc_f) / c_reeds_f(name)


def settings(quality: str = "production") -> io.TransientSettings:
    st = io.TransientSettings.from_sim_settings(
        engine="circuitsim", quality=None if quality == "production" else quality
    )
    return dataclasses.replace(st, full_scale_volts_peak=1.0)  # the input in volts


def render(
    x_v: np.ndarray,
    sets: dict | None = None,
    quality: str = "production",
    probes: tuple[str, ...] = ("out", "spk"),
    name: str = CIRCUIT,
) -> dict[str, np.ndarray]:
    """The circuit driven at `in` by x_v (volts, at the project's rate): the probes' volts."""
    c = _circuit(name)
    ir = builder.build_ir(c, cspec.resolve(c, sets or {}))
    ir = dataclasses.replace(ir, probes=tuple(VoltageProbe(p) for p in probes))
    v = fast.run_transient(ir, np.asarray(x_v, dtype=float), settings=settings(quality)).vectors
    return {p: np.asarray(v[f"v({p})"]) for p in probes}


@dataclasses.dataclass(frozen=True)
class Transfer:
    f_hz: np.ndarray
    h: dict  # probe -> complex response at f_hz

    def apply(self, x: np.ndarray, fs_hz: float, probe: str = "out") -> np.ndarray:
        """x filtered by the response (magnitude and phase interpolated in log f, held at
        the ends; circular, so pad x)."""
        fr = np.fft.rfftfreq(x.size, 1 / fs_hz)
        lf = np.log(np.clip(fr, self.f_hz[0], self.f_hz[-1]))
        h = self.h[probe]
        mag = np.interp(lf, np.log(self.f_hz), np.log(np.abs(h)))
        ph = np.interp(lf, np.log(self.f_hz), np.unwrap(np.angle(h)))
        return np.fft.irfft(np.fft.rfft(x) * np.exp(mag + 1j * ph), x.size)


def _transfer_key(sets: dict, quality: str, name: str) -> str:
    hsh = hashlib.sha256()
    hsh.update(cspec.circuit_path(name).read_bytes())
    hsh.update(Path(__file__).read_bytes())
    hsh.update(repr(sorted(sets.items())).encode())
    hsh.update(quality.encode())
    return hsh.hexdigest()[:16]


def transfer(
    sets: dict | None = None,
    quality: str = "production",
    probes: tuple[str, ...] = ("out", "spk"),
    name: str = CIRCUIT,
) -> Transfer:
    sets = dict(sets or {})
    path = pk.CACHE_DIR / f"transfer_{_transfer_key(sets, quality, name)}.npz"
    if path.exists():
        z = np.load(path)
        if all(p in z for p in probes):
            return Transfer(z["f_hz"], {p: z[p] for p in probes})
    fs = TRANSFER_FS
    t = np.arange(2 * fs) / fs
    f = np.unique(np.round(np.geomspace(20, 20000, TRANSFER_TONES)))  # whole Hz: 1 s periodic
    ph = np.random.default_rng(1).uniform(0, 2 * np.pi, f.size)
    x = 0.02 * np.sum(np.sin(2 * np.pi * f[:, None] * t + ph[:, None]), axis=0) / np.sqrt(f.size)
    v = render(x, sets, quality, probes, name)
    seg = slice(fs, 2 * fs)
    k = f.astype(int)
    xs = np.fft.rfft(x[seg])[k]
    h = {p: np.fft.rfft(v[p][seg])[k] / xs for p in probes}
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, f_hz=f, **h)
    return Transfer(f, h)
