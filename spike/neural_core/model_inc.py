"""The incremental net: the state is the physical pair (B, H), the net learns the step's slope.

A rate-independent hysteresis of the differential kind (Jiles-Atherton, Duhem, Bouc-Wen)
is a law dH/dB = f(B, H, direction): its state is (B, H), and one sample's step from the
last accepted point is a function of (B_{n-1}, H_{n-1}, dB). So the recurrent part is
exact bookkeeping and the net is a static map, fitted by plain regression:

    dB   = B_n - B_{n-1}
    u    = [asinh(B_{n-1} / B0), asinh(H_{n-1} / H0), asinh(dB / DB0)] / XS
    H_n  = H_{n-1} + S_LIN exp(g(u)) dB                      (A/m)

g is an MLP (smooth activations); g = 0 is the core's linear limit. exp keeps the slope
positive: H is monotonic in B within a step, so Newton's residual stays monotonic. The
target is g* = log(((H_n - H_{n-1}) / dB) / S_LIN): no zero crossings, ~12 units of range
(relative permeability 1..250,000).

Why: the plain GRU (model.py) learned the residual H - S_LIN B slowly (-8..-10 dB open loop
after 150 epochs, the same on loud items only), the residual crossing zero twice a cycle.
"""

from __future__ import annotations

import numpy as np
import torch
from torch import nn

B0_T = 1e-5
H0_A_PER_M = 1e-5
DB0_T = 1e-10  # below a sample's dB at 20 Hz, -40 dBu (~6e-8 T): the direction stays sharp
X_SCALE = 4.0


def inputs(b_prev, h_prev, db):
    lib = torch if isinstance(b_prev, torch.Tensor) else np
    return (
        lib.asinh(b_prev / B0_T) / X_SCALE,
        lib.asinh(h_prev / H0_A_PER_M) / X_SCALE,
        lib.asinh(db / DB0_T) / X_SCALE,
    )


class IncNet(nn.Module):
    def __init__(self, width: int = 64, depth: int = 3):
        super().__init__()
        layers: list[nn.Module] = []
        n_in = 3
        for _ in range(depth):
            layers += [nn.Linear(n_in, width), nn.Tanh()]
            n_in = width
        layers.append(nn.Linear(n_in, 1))
        self.mlp = nn.Sequential(*layers)

    def forward(self, u: torch.Tensor) -> torch.Tensor:
        """u: (..., 3) inputs -> g (...)."""
        return self.mlp(u).squeeze(-1)

    def to_numpy(self, s_lin: float) -> NumpyInc:
        lin = [m for m in self.mlp if isinstance(m, nn.Linear)]
        ws = [m.weight.detach().cpu().double().numpy() for m in lin]
        bs = [m.bias.detach().cpu().double().numpy() for m in lin]
        return NumpyInc(ws, bs, s_lin)


class NumpyInc:
    """The incremental net in float64, as a bench core (`bench.Core`)."""

    def __init__(self, ws, bs, s_lin: float, n: int = 1):
        self.ws, self.bs, self.s_lin = ws, bs, s_lin
        self.reset(n)

    def reset(self, n: int) -> None:
        self.b_prev = np.zeros(n)
        self.h_prev = np.zeros(n)
        self._pending = None

    def eval(self, b):
        db = b - self.b_prev
        u0, u1, u2 = inputs(self.b_prev, self.h_prev, db)
        du2 = 1 / (X_SCALE * np.sqrt(db * db + DB0_T * DB0_T))  # only u2 depends on b
        w0 = self.ws[0]
        a = np.outer(u0, w0[:, 0]) + np.outer(u1, w0[:, 1]) + np.outer(u2, w0[:, 2]) + self.bs[0]
        da = np.outer(du2, w0[:, 2])
        for w, bias in zip(self.ws[1:], self.bs[1:], strict=True):
            t = np.tanh(a)
            dt = (1 - t * t) * da
            a = t @ w.T + bias
            da = dt @ w.T
        g, dg = a[:, 0], da[:, 0]
        slope = self.s_lin * np.exp(g)
        h = self.h_prev + slope * db
        self._pending = (b.copy(), h)
        return h, slope * (1 + db * dg)

    def accept(self, b):
        last_b, h = self._pending
        assert np.array_equal(last_b, b), "accept follows an eval at the same b"
        self.b_prev = b.copy()
        self.h_prev = h
