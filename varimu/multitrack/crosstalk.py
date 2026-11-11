"""Crosstalk between neighbouring tracks of one tape (docs/PERIOD_GEAR_BACKLOG.md, PG1, MT3).

Ampex names two mechanisms (data/schematics/ampex_300_4/README.md, "Crosstalk"; the 354
manual p. 12):

- **Playback, long wavelengths.** "Magnetic coupling occurs in reproduce between the signal
  recorded on one track and the reproduce head of the other track" ("the direct pick-up by one
  head of flux passing the other head": Ampex AI-14 p. 10). Our ring head's field
  (`varimu.devices.tape.head_hx_spectrum`) is a gap term plus an outer-contour term: the pole
  faces' potential relaxing to zero beyond their ends, in air (pole_m, relax_m). Between the
  cores of a stack the interchannel shields screen the gap; the contour's field, in air beyond
  the stack, isn't screened, so a head reads its neighbour's track through its contour term
  only, attenuated by the lateral distance. That lateral factor is the field of a strip source
  (the head's width W) in three dimensions at one wavenumber k along the tape: in the plane of
  the head face the free-space propagator 1 / (2 kappa), kappa = sqrt(k^2 + q^2), is K0(k |y|)
  / pi across the width, so the factor of a neighbour at centre distance D is

      L(k) = k / (pi W) integral over |u - D| < W of (W - |u - D|) K0(k u) du,

  normalized so that a track of infinite width reads its own contour term with L = 1 (the
  stream's 2D head). The fraction of the contour's flux the shields leave, `unshielded`, is the
  one fitted unknown (`fit_unshielded`, on Ampex's measured curve).
- **Playback, the cores.** "90-mil stacked heads, separated by only 70 mils or so, form a
  small transformer ... Interwinding shields proved satisfactory" (AI-14 p 10): a flat
  magnetic coupling between neighbouring cores, a fraction of the neighbour's own EMF. It is
  the curve's plateau (~-59 dB, ~400 Hz-4 kHz), which the contour's term (falling as
  exp(-k (D - W))) can't give. Below ~300 Hz the contour's term and this one add with their
  signs: the curve's lobes and nulls.
- **Record, high frequencies.** "The mutual inductance and capacitance between the two record
  heads causes the signal from one record head to be present in the other record head, and
  therefore to get recorded on that other track." With constant-current record drives, a
  mutual inductance M puts j w M I into the neighbour's loop, whose current is that over the
  loop's impedance (its driver's source impedance, far above the head's): a 6 dB / octave
  rise, independent of the pre-emphasis (both tracks are equalized alike); a capacitance
  between the windings, across the driven head's j w L, 12 dB / octave. Here as
  `record_coupling_db` (fitted); in the deck's circuit (MT5) they are couplings between the
  record coils, sized to give this.

`fit` sizes the five unknowns on the curve's third-octave envelope (`bands`), with
the head's contour as our model's head: Ampex's lobes belong to its 1957 three-track head's
contour, which isn't published, and the deck plays our heads."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import integrate, special

from varimu.devices.tape import HeadGeometry

MIL = 25.4e-6
REPO = Path(__file__).resolve().parents[2]
MEASURED_CSV = REPO / "data" / "datasheets" / "ampex_300_crosstalk.csv"


@dataclass(frozen=True)
class TrackFormat:
    """Tracks of one width on equal centres across the tape, numbered from the top edge."""

    name: str
    tracks: int
    width_m: float
    pitch_m: float  # centre to centre
    tape_m: float
    source: str

    def __post_init__(self) -> None:
        span = (self.tracks - 1) * self.pitch_m + self.width_m
        if self.width_m >= self.pitch_m or span > self.tape_m:
            raise ValueError(f"{self.name}: {self.tracks} tracks don't fit")

    @property
    def guard_m(self) -> float:
        return self.pitch_m - self.width_m

    def neighbours(self, track: int, reach: int = 1) -> list[tuple[int, float]]:
        """(track, centre distance) of the tracks within `reach` of `track` (0-based): an
        edge track has one neighbour, an inner track two."""
        return [
            (j, abs(j - track) * self.pitch_m)
            for j in range(self.tracks)
            if j != track and abs(j - track) <= reach
        ]


#: The four-track 1/2 in master (the build): the 354 manual p. 12's layout, NAB's 70 mil on
#: 130 mil centres.
FOUR_TRACK_HALF_INCH = TrackFormat(
    "4 track 1/2 in",
    4,
    70 * MIL,
    130 * MIL,
    500 * MIL,
    "data/schematics/ampex_300_4/README.md: 354 manual p 44 (12), '4 track master', 70 mil tracks "
    "60 mil apart (AI-14's 80 mil can't fit four with 60 mil gaps on 500 mil)",
)
#: The three-track 1/2 in master, the format of Ampex's measured crosstalk curve.
THREE_TRACK_HALF_INCH = TrackFormat(
    "3 track 1/2 in",
    3,
    100 * MIL,
    185 * MIL,
    500 * MIL,
    "354 manual p 44 (12): '3 track master', 100 mil tracks 85 mil apart; AI-14 p 13 (13)",
)


def lateral_quad(k: float, d: float, w: float) -> float:
    """`lateral` by adaptive quadrature (the reference `lateral`'s rule is tested against)."""
    if d <= w:
        raise ValueError("the strips overlap: crosstalk is for separate tracks")
    if k <= 0.0:
        raise ValueError("k > 0")

    def f(u: float) -> float:
        return (w - abs(u - d)) * special.k0(k * u)

    val, _ = integrate.quad(f, d - w, d + w, points=[d], limit=200, epsabs=0.0, epsrel=1e-12)
    return k / (math.pi * w) * val


_GL_X, _GL_W = np.polynomial.legendre.leggauss(48)


def lateral(k: np.ndarray | float, d_m: float, w_m: float) -> np.ndarray:
    """L(k): the contour field a head of width w reads from a track of width w at centre
    distance d, relative to a track of infinite width (the module's docs). Gauss-Legendre
    on each half of the triangle (K0 is smooth there: d > w)."""
    if d_m <= w_m:
        raise ValueError("the strips overlap: crosstalk is for separate tracks")
    k = np.abs(np.atleast_1d(np.asarray(k, float)))
    if np.any(k <= 0.0):
        raise ValueError("k > 0")
    acc = np.zeros_like(k)
    for lo, hi in ((d_m - w_m, d_m), (d_m, d_m + w_m)):
        u = 0.5 * (hi - lo) * _GL_X + 0.5 * (hi + lo)
        tri = w_m - np.abs(u - d_m)
        acc += 0.5 * (hi - lo) * (special.k0(np.outer(k, u)) @ (_GL_W * tri))
    return k / (math.pi * w_m) * acc


def contour_term(head: HeadGeometry, k: np.ndarray) -> np.ndarray:
    """The outer contour's part of the head's spectrum over the gap length (head_hx_spectrum's
    second term without g e^{-|k| y}): -cos(k e_c) R(k)."""
    k = np.asarray(k, float)
    g, p, r = head.gap_m, head.pole_m, head.relax_m
    ec = g / 2.0 + p + r / 2.0
    relax = np.sinc(k * r / (2.0 * math.pi)) if r > 0 else 1.0
    return -np.cos(k * ec) * relax


def gap_term(head: HeadGeometry, k: np.ndarray) -> np.ndarray:
    return np.sinc(np.asarray(k, float) * head.gap_m / (2.0 * math.pi))


def record_coupling_db(f_hz: np.ndarray, a_at_10k: float, power: int = 1) -> np.ndarray:
    """The record heads' coupling, recorded on the neighbour: a (f / 10 kHz)^power, in dB:
    power 1 a mutual inductance (j w M over the neighbour's loop impedance), 2 a capacitance
    between the windings (j w C across the driven head's j w L)."""
    return 20.0 * np.log10(a_at_10k * (np.asarray(f_hz, float) / 10e3) ** power)


def combined_db(*terms_db: np.ndarray) -> np.ndarray:
    """Terms added in power (their phases unknown to the curve)."""
    return 10.0 * np.log10(sum(10.0 ** (np.asarray(t) / 10.0) for t in terms_db))


def measured() -> tuple[np.ndarray, np.ndarray]:
    """Ampex's curve (f_hz, db), reading (a) of its axis (the provenance sidecar)."""
    d = np.loadtxt(MEASURED_CSV, delimiter=",", skiprows=1)
    return d[:, 0], d[:, 1]


def bands(
    f_hz: np.ndarray,
    db: np.ndarray,
    centres: np.ndarray | None = None,
    per_octave: int = 1,
    lo_hz: float = 20.0,
) -> tuple:
    """Power averages of a curve (dense in log f) over 1 / per_octave octave bands:
    (centres, dB). Without `centres`, the bands from lo_hz up with at least two points.
    Ampex's lobes depend on its 1957 head's contour (a lobe spans about an octave); the fit
    is on this envelope."""
    f_hz, db = np.asarray(f_hz, float), np.asarray(db, float)
    half = 2.0 ** (0.5 / per_octave)
    if centres is None:
        cs, c = [], lo_hz * half
        while c < f_hz.max():
            if np.count_nonzero((f_hz >= c / half) & (f_hz < c * half)) >= 2:
                cs.append(c)
            c *= half * half
        centres = np.array(cs)
    out = []
    for c in centres:
        m = (f_hz >= c / half) & (f_hz < c * half)
        out.append(10.0 * np.log10(np.mean(10.0 ** (db[m] / 10.0))))
    return np.asarray(centres), np.array(out)


#: The four-track stack's couplings re the three-track's: AI-14 p 13 gives crosstalk
#: rejection "at a similar figure" to S/N 55 dB for three 100 mil tracks 100 mil apart and
#: "around 50 decibels" for four 80 mil tracks 60 mil apart (data/schematics/ampex_300_4/
#: README.md): +5 dB on the couplings that don't follow from geometry (the cores' and the
#: record heads'), as the stack's gaps narrow.
FOUR_VS_THREE_DB = 5.0


@dataclass(frozen=True)
class Crosstalk:
    """The fitted crosstalk between neighbouring heads of a stack (the module's docs).

    unshielded: the contour's flux fraction the shields leave; contour_width_ratio: the
    contour's effective width over the track width (its field spreads past the track: the
    core and pole pieces are wider); core: the cores' flat magnetic coupling ("a small
    transformer", AI-14 p 10), signed re the contour term; mutual / capacitive: the record
    heads' couplings at 10 kHz (6 and 12 dB / octave). Fitted on the three-track Model 300,
    `scaled` to another format."""

    head: HeadGeometry
    unshielded: float
    contour_width_ratio: float
    core: float
    mutual: float
    capacitive: float

    def contour_width_m(self, fmt: TrackFormat) -> float:
        return self.contour_width_ratio * fmt.width_m

    def playback(self, f_hz: np.ndarray, speed_m_s: float, fmt: TrackFormat, d_m: float):
        """The neighbour's EMF over the driven track's own (both through the same playback
        EQ, as Ampex measured them; the engine's ratio, `varimu.devices.tape.CrossPickup`):
        the contour's pickup over the head's own reading, plus the cores' coupling (a
        fraction of the driven head's own reading), signed. The head's own reading isn't
        flat: its bump moves the low end by up to ~4 dB on the 351's head (until 2026-11-10
        the fit took it as flat)."""
        k = 2.0 * math.pi * np.asarray(f_hz, float) / speed_m_s
        lat = lateral(k, d_m, self.contour_width_m(fmt))
        own = gap_term(self.head, k) + contour_term(self.head, k)
        return self.unshielded * contour_term(self.head, k) * lat / own + self.core

    def curve_db(self, f_hz: np.ndarray, speed_m_s: float, fmt: TrackFormat) -> np.ndarray:
        """Crosstalk on an adjacent track as Ampex measured it (dB re the driven track's
        operating level): the playback terms, then the record heads' couplings in power."""
        pb = 20.0 * np.log10(np.abs(self.playback(f_hz, speed_m_s, fmt, fmt.pitch_m)) + 1e-30)
        return combined_db(
            pb,
            record_coupling_db(f_hz, self.mutual, 1),
            record_coupling_db(f_hz, self.capacitive, 2),
        )

    def scaled(self, by_db: float = FOUR_VS_THREE_DB) -> Crosstalk:
        """The couplings that don't follow from geometry raised by by_db (the four-track
        stack's narrower gaps)."""
        g = 10.0 ** (by_db / 20.0)
        return Crosstalk(
            self.head,
            self.unshielded,
            self.contour_width_ratio,
            self.core * g,
            self.mutual * g,
            self.capacitive * g,
        )


def fit(
    head: HeadGeometry,
    speed_m_s: float = 0.381,
    fmt: TrackFormat = THREE_TRACK_HALF_INCH,
    per_octave: int = 1,
) -> tuple[Crosstalk, float]:
    """Crosstalk's five unknowns fitted to Ampex's curve's octave envelope (`bands`; the
    head's contour given: our model's head), over both signs of the cores' coupling; returns
    it and the rms misfit (dB) over the bands."""
    from scipy import optimize

    f, db = measured()
    dense = np.geomspace(f.min(), f.max(), 2000)
    fc, want = bands(f, db, per_octave=per_octave)
    max_ratio = 0.999 * fmt.pitch_m / fmt.width_m

    def make(p, sign) -> Crosstalk:
        return Crosstalk(
            head,
            10 ** (p[0] / 20),
            p[1],
            sign * 10 ** (p[2] / 20),
            10 ** (p[3] / 20),
            10 ** (p[4] / 20),
        )

    def cost(p, sign) -> float:
        _, got = bands(dense, make(p, sign).curve_db(dense, speed_m_s, fmt), fc, per_octave)
        return float(np.sqrt(np.mean((got - want) ** 2)))

    bounds = [(-40, 20), (0.5, max_ratio), (-80, -45), (-90, -20), (-90, -20)]
    best = None
    for sign in (1.0, -1.0):
        for p0 in ([-5, 1.2, -59, -52, -60], [-5, 1.6, -59, -60, -52], [0, 1.0, -60, -55, -55]):
            r = optimize.minimize(cost, p0, args=(sign,), method="Powell", bounds=bounds)
            if best is None or r.fun < best[0]:
                best = (float(r.fun), make(r.x, sign))
    return best[1], best[0]
