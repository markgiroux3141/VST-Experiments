"""Reading SOFA (AES69) HRIR files, SimpleFreeFieldHRIR, through h5py (the `binaural` extra)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class SofaHrir:
    fs: float
    ir: np.ndarray  # (M, 2, N): receivers 0 = left, 1 = right
    az_deg: np.ndarray  # (M,)
    el_deg: np.ndarray  # (M,)
    distance_m: np.ndarray  # (M,)
    attrs: dict

    def tf(self, n_fft: int | None = None) -> tuple[np.ndarray, np.ndarray]:
        n = n_fft or self.ir.shape[-1]
        return np.fft.rfftfreq(n, 1 / self.fs), np.fft.rfft(self.ir, n, axis=-1)


def read(path: Path) -> SofaHrir:
    import h5py

    with h5py.File(path, "r") as f:
        conv = f.attrs.get("SOFAConventions", b"")
        conv = conv.decode() if isinstance(conv, bytes) else str(conv)
        if conv != "SimpleFreeFieldHRIR":
            raise ValueError(f"{path}: {conv}, not SimpleFreeFieldHRIR")
        units = f["SourcePosition"].attrs.get("Type", b"spherical")
        units = units.decode() if isinstance(units, bytes) else str(units)
        sp = f["SourcePosition"][:]
        if units != "spherical":
            r = np.linalg.norm(sp, axis=1)
            az = np.degrees(np.arctan2(sp[:, 1], sp[:, 0])) % 360
            el = np.degrees(np.arcsin(sp[:, 2] / r))
            sp = np.stack([az, el, r], axis=1)
        attrs = {k: (v.decode() if isinstance(v, bytes) else v) for k, v in f.attrs.items()}
        return SofaHrir(
            float(f["Data.SamplingRate"][0]),
            f["Data.IR"][:].astype(float),
            sp[:, 0] % 360,
            sp[:, 1],
            sp[:, 2],
            attrs,
        )
