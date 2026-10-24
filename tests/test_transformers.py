"""Main plan Phase 2, "done when": each transformer, tested standalone, shows
plausible frequency response, low-frequency saturation with rising level, and a
visible hysteresis loop.

Each of T101-T104 is the slice's own transformer (Jiles-Atherton core) between
the slice's source and load impedances, the tubes as resistances
(varimu.measure.transformers; scripts/transformer_report.py plots the same
figures to reports/transformers/). Measured 2026-10-24, after mumetall's
Rayleigh refit (re 1 kHz, 40 Hz / 15 kHz; 30 Hz THD at 0.5 of mu0 Ms / at
the top drive, 0.87-1.0 of it):

    T101 input (mumetall)          -0.02 / +0.56 dB   0.08% / 12.0%
    T102 output (GO steel)         -0.33 / -0.32 dB   0.33% / 11.5%
    T103 sidechain in (mumetall)   -0.04 / +0.06 dB   0.09% / 11.9%
    T104 sidechain out (GO steel)  -6.64 / -0.04 dB   2.07% / 17.0%

Before the refit (2026-10-21 / -23): T101 -0.29 / +0.60 dB, 0.09% / 15.9%;
T103 -0.20 / +0.08 dB, 0.10% / 13.6% (the old fit's low permeability at
small drive cost bass).

"Plausible" here is the 670's published response, 40 Hz - 15 kHz +-1 dB
(reissue / dealer specs, see config/circuits/fairchild_670.yaml), for the
signal transformers; T103 is allowed +-1.5 dB. T104 is driven from the 6973
plates, which the slice feeds back only at HF (C105/C106, 20 pF), so at low
frequencies they are high-impedance pentodes: it is checked from 300 Hz, its
LF end being the plates' and the 12BH7 feedback winding's business.
"""

import numpy as np
import pytest

pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")

from varimu.measure import transformers as tx  # noqa: E402

# key -> (band of the response check in Hz, tolerance in dB)
RESPONSE = {
    "t101": ((40, 15000), 1.0),
    "t102": ((40, 15000), 1.0),
    "t103": ((40, 15000), 1.5),
    "t104": ((300, 15000), 1.0),
}


@pytest.fixture(scope="module", params=tx.KEYS)
def measured(request):
    return request.param, tx.summary(request.param)


def test_frequency_response_is_plausible(measured):
    key, s = measured
    (lo, hi), tol = RESPONSE[key]
    f, g = np.array(s["freqs_hz"]), np.array(s["gain_db"])
    band = (f >= lo) & (f <= hi)
    assert np.max(np.abs(g[band])) <= tol, dict(zip(f[band], g[band], strict=True))
    # A transformer: it rolls off at the low end (magnetizing inductance). Since
    # mumetall's Rayleigh refit, T101 and T103 are nearly flat to 10 Hz (-0.23 dB
    # there): check at the bottom of the sweep.
    assert g[0] < g[f == 100][0] - 0.3, (f[0], g[0])


def test_low_frequency_saturation_rises_with_level(measured):
    key, s = measured
    lf = s["thd_30hz"]
    bsat = s["bsat_t"]
    b = np.array([r["b_peak_t"] for r in lf])
    thd = np.array([r["thd_pct"] for r in lf])
    upper = b >= 0.45 * bsat
    assert np.all(np.diff(thd[upper]) > 0), list(zip(b, thd, strict=True))
    assert thd[np.argmin(abs(b - 0.5 * bsat))] <= 2.5, (key, thd)
    assert b[-1] >= 0.85 * bsat and thd[-1] >= 5.0, (key, b[-1], thd[-1])
    # The same drives at 1 kHz need ~33x less flux: no saturation there.
    assert max(r["thd_pct"] for r in s["thd_1khz"]) < 0.2


def test_the_hysteresis_loop_is_visible(measured):
    _, s = measured
    lp = s["loop"]
    b, h = np.array(lp["b"]), np.array(lp["h"])
    area = abs(np.trapezoid(h, b))  # J/m^3 per cycle
    assert area > 0
    # coercivity on both branches: where B crosses zero, H is on opposite sides
    up = [h[i] for i in range(1, len(b)) if b[i - 1] < 0 <= b[i]]
    down = [h[i] for i in range(1, len(b)) if b[i - 1] > 0 >= b[i]]
    assert up and down and min(up) > 0 > max(down), (up, down)
    assert np.max(np.abs(b)) > 0.8 * s["bsat_t"]
