"""The net: a GRU cell from B to H, one step per sample.

Per sample n, with the hidden state h_{n-1} of the previous accepted sample:

    x_n  = [asinh(B_n / B0), asinh((B_n - B_{n-1}) / DB0)] / XS  (companded inputs, ~+-3)
    h_n  = GRU(x_n, h_{n-1})
    y_n  = Y_MAX tanh((W2 tanh(W1 h_n + b1) + b2) / Y_MAX)        (soft clamp)
    H_n  = S_LIN B_n + R0 sinh(y_n)                              (A/m)

S_LIN is the core's linear limit (1 / (mu0 (1 + chi0))): the net only predicts the
residual r = H - S_LIN B, which is what makes the distortion. The companding is the point
(the spike's README, "The hard part"): B spans 1e-5..0.8 T and r 1e-7..1e3 A/m, and a net
in float32 can't hold a tiny quadratic term next to O(1) activations, so both ends are
asinh-companded to O(10) and the loss is relative to the local level of r.

`TorchNet` trains (cuDNN's GRU, teacher-forced on recorded B); `NumpyNet` is the same cell
for the bench: `eval(B)` returns H and dH/dB (forward mode through the cell, B a scalar per
sequence) with the hidden state frozen, `accept` moves it on.
"""

from __future__ import annotations

import numpy as np
import torch
from torch import nn

B0_T = 1e-5
DB0_T = 1e-7
X_SCALE = 4.0  # the companded inputs reach ~+-12; /4 keeps the GRU's gates out of saturation
R0_A_PER_M = 1e-8
Y_MAX = 40.0  # |r| < R0 sinh(40) ~ 1e9 A/m; unclamped, sinh overflowed float32 in training


def features(b: np.ndarray | torch.Tensor, b_prev):
    lib = torch if isinstance(b, torch.Tensor) else np
    return lib.asinh(b / B0_T) / X_SCALE, lib.asinh((b - b_prev) / DB0_T) / X_SCALE


class TorchNet(nn.Module):
    def __init__(self, hidden: int = 32, head: int = 32):
        super().__init__()
        self.hidden = hidden
        self.gru = nn.GRU(2, hidden, batch_first=True)
        self.head = nn.Sequential(nn.Linear(hidden, head), nn.Tanh(), nn.Linear(head, 1))

    def forward(self, x: torch.Tensor, h0: torch.Tensor | None = None):
        """x: (batch, time, 2) features -> y (batch, time) and the last hidden state."""
        out, hn = self.gru(x, h0)
        return Y_MAX * torch.tanh(self.head(out).squeeze(-1) / Y_MAX), hn

    def to_numpy(self, s_lin: float) -> NumpyNet:
        g = {k: v.detach().cpu().double().numpy() for k, v in self.state_dict().items()}
        return NumpyNet(
            w_ih=g["gru.weight_ih_l0"],
            w_hh=g["gru.weight_hh_l0"],
            b_ih=g["gru.bias_ih_l0"],
            b_hh=g["gru.bias_hh_l0"],
            w1=g["head.0.weight"],
            b1=g["head.0.bias"],
            w2=g["head.2.weight"][0],
            b2=float(g["head.2.bias"][0]),
            s_lin=s_lin,
        )


def sigmoid(x):
    return 0.5 * (1 + np.tanh(0.5 * x))


class NumpyNet:
    """The trained cell in float64, as a bench core (`bench.Core`): n sequences at once."""

    def __init__(self, *, w_ih, w_hh, b_ih, b_hh, w1, b1, w2, b2, s_lin, n: int = 1):
        self.w_ih, self.w_hh, self.b_ih, self.b_hh = w_ih, w_hh, b_ih, b_hh
        self.w1, self.b1, self.w2, self.b2 = w1, b1, w2, b2
        self.s_lin = s_lin
        self.size = w_hh.shape[1]
        self.reset(n)

    def reset(self, n: int) -> None:
        self.h = np.zeros((n, self.size))
        self.b_prev = np.zeros(n)
        self._gh = None  # W_hh h + b_hh of the frozen state
        self._pending = None

    def eval(self, b):
        hs = self.size
        if self._gh is None:
            self._gh = self.h @ self.w_hh.T + self.b_hh
        gh = self._gh
        x0, x1 = features(b, self.b_prev)
        dx0 = 1 / (X_SCALE * np.sqrt(b * b + B0_T * B0_T))
        dx1 = 1 / (X_SCALE * np.sqrt((b - self.b_prev) ** 2 + DB0_T * DB0_T))
        gi = np.outer(x0, self.w_ih[:, 0]) + np.outer(x1, self.w_ih[:, 1]) + self.b_ih
        dgi = np.outer(dx0, self.w_ih[:, 0]) + np.outer(dx1, self.w_ih[:, 1])
        r = sigmoid(gi[:, :hs] + gh[:, :hs])
        z = sigmoid(gi[:, hs : 2 * hs] + gh[:, hs : 2 * hs])
        dr = r * (1 - r) * dgi[:, :hs]
        dz = z * (1 - z) * dgi[:, hs : 2 * hs]
        a = gi[:, 2 * hs :] + r * gh[:, 2 * hs :]
        da = dgi[:, 2 * hs :] + dr * gh[:, 2 * hs :]
        nn_ = np.tanh(a)
        dn = (1 - nn_ * nn_) * da
        h_new = (1 - z) * nn_ + z * self.h
        dh_new = (1 - z) * dn + dz * (self.h - nn_)
        t = np.tanh(h_new @ self.w1.T + self.b1)
        q = np.tanh((t @ self.w2 + self.b2) / Y_MAX)
        y = Y_MAX * q
        dy = (1 - q * q) * (((1 - t * t) * (dh_new @ self.w1.T)) @ self.w2)
        res = R0_A_PER_M * np.sinh(y)
        dres = R0_A_PER_M * np.cosh(y) * dy
        self._pending = (b.copy(), h_new)
        return self.s_lin * b + res, self.s_lin + dres

    def accept(self, b):
        last_b, h_new = self._pending
        assert np.array_equal(last_b, b), "accept follows an eval at the same b"
        self.h = h_new
        self.b_prev = b.copy()
        self._gh = None
