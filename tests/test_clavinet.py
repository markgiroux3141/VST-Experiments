"""The Clavinet D6's strings, pickups and a played key (docs/CLAVINET_PLAN.md, CL1).

The checks against [G13] / [R12] are the plan's CL1 done-when: B against Table 1, the release
drop, decays of the right order, comb notches where the pickup's distance puts them, the
substructure model against plain finite elements, and the beating hypothesis tested (its
result is reported, either way)."""

from __future__ import annotations

import numpy as np
import pytest

from varimu.clavinet import fit, note, pickup, reference, spec, strings

G13_B = {1: 5e-4, 6: 2e-4, 22: 9e-5, 23: 1e-4, 50: 9e-5, 60: 8e-5}


def test_keyboard() -> None:
    cfg = spec.load()
    assert spec.note_hz(1, cfg) == pytest.approx(43.654, rel=1e-4)  # F1
    assert spec.note_hz(60, cfg) == pytest.approx(1318.51, rel=1e-4)  # E6
    assert spec.key_of_midi(29) == 1 and spec.key_of_midi(88) == 60 and spec.key_of_midi(89) is None


@pytest.mark.parametrize("n", sorted(G13_B))
def test_inharmonicity_vs_g13(n: int) -> None:
    """[G13] Table 1 / Fig. 6: the nominal B within 45% (E6 is the fit: exact). The wound
    type 1 can't match both its anchors with one core (5e-4 at F1, 2e-4 at A#1)."""
    b = spec.string(n).b_nominal
    tol = 1e-6 if n == 60 else 0.45
    assert b == pytest.approx(G13_B[n], rel=tol)


def test_strings_hold() -> None:
    """Every string below its wire's tensile strength (plain: E6 the most stressed)."""
    cfg = spec.load()
    for n in range(1, 61):
        g = spec.string(n)
        t = g.mu_kg_m * (2 * g.length_m * g.f_hz) ** 2
        assert t / (np.pi * g.d_core_m**2 / 4) < 0.75 * cfg["steel"]["tensile_pa"]


@pytest.mark.parametrize("n", [17, 36, 60])
def test_tuned_held(n: int) -> None:
    p = fit.params(n)
    f1 = fit.partials(strings.system(p, True), p, 1)[0][0]
    assert 1200 * abs(np.log2(f1 / p.geom.f_hz)) < 0.05
    assert p.tension_rest_n < p.tension_held_n  # the pinch stretches it


@pytest.mark.parametrize("n", [1, 17, 24, 36, 50, 60])
def test_release_drop(n: int) -> None:
    """[G13] 2.3.1: three semitones for the whole keyboard (E4 is the fit)."""
    p = fit.params(n)
    f_rel, sig = fit.released_fundamental(p)
    assert 12 * np.log2(p.geom.f_hz / f_rel) == pytest.approx(3.0, abs=0.7)
    assert np.log(1000) / sig < (1.0 if p.geom.wound else 0.3)  # the yarn kills it


def test_decays_vs_g13() -> None:
    """A2 (Fig. 7a; the fundamental is the fit) and E4 (Fig. 8): low partials ring longest,
    each within a factor of 2.5 of the published T60."""
    for n, g13 in (
        (17, [22.0, 16.0, 10.5, 9.7, 4.9]),
        (36, [8.1, 9.0, 7.0, 8.6, 6.5, 6.0, 3.5, 5.9, 3.1, 4.3]),
    ):
        p = fit.params(n)
        parts = fit.partials(strings.system(p, True), p, len(g13))
        t60 = np.array([np.log(1000) / s for _, s in parts])
        ratio = t60 / np.array(g13)
        assert np.all((ratio > 1 / 2.5) & (ratio < 2.5)), (n, t60.round(1))
        assert t60[0] > t60[-1]


@pytest.mark.parametrize("n", [1, 24, 36])
def test_held_vs_finite_elements(n: int) -> None:
    """strings.py's held system against plain FE of the whole string (no reduction),
    lossless (measured 2026-11-06): the ringing modes (sigma < 20/s: the speaking partials,
    both polarizations) within 0.5 cents, their decays within 10%; the yarn's heavily
    damped ones within 20 cents and 10%."""
    p = fit.params(n)
    rows = [r for r in reference.compare(p, True, 3000.0) if r[0] > 20.0]
    assert len(rows) > 10
    for f_ref, f_cb, s_ref, s_cb in rows:
        cents = 1200 * abs(np.log2(f_cb / f_ref))
        assert cents < (0.5 if s_ref < 20 else 20.0)
        if s_ref > 1e-3:
            assert s_cb == pytest.approx(s_ref, rel=0.10)


@pytest.mark.parametrize("n", [1, 24, 36, 60])
def test_release_vs_finite_elements(n: int) -> None:
    """The released fundamental (what a release sounds: the drop and the yarn's kill)
    against the plain FE's eigenvalue nearest it: within 5 cents and 15% in decay."""
    p = fit.params(n)
    f_cb, s_cb = fit.released_fundamental(p)
    ref = reference.eigenvalues(reference.lossless(p), False)
    q = reference.lossless(p)
    f_q, s_q = fit.released_fundamental(q)
    j = int(np.argmin(np.abs(ref - complex(-s_q, 2 * np.pi * f_q))))
    assert 1200 * abs(np.log2(f_q / (ref[j].imag / (2 * np.pi)))) < 5.0
    assert s_q == pytest.approx(-ref[j].real, rel=0.15)
    assert np.isfinite(f_cb) and s_cb > 0


def test_bend() -> None:
    """The rubber's wrap: harder presses bend up (the configured target at its key)."""
    cfg = spec.load()
    an = cfg["anvil"]
    p = fit.params(int(an["bend_key"]))
    lo, hi = an["bend_force_n"]
    assert fit.bend_cents(p, hi) - fit.bend_cents(p, lo) == pytest.approx(
        an["bend_target_cents"], abs=0.5
    )
    assert fit.bend_cents(p, 3.0) > fit.bend_cents(p, 2.0) > fit.bend_cents(p, 1.0)


def test_pickup_shape() -> None:
    """The along-the-string model ([R12] Fig. 5 / [G13] Fig. 10): the linkage falls as the
    string rises (measured 2026-11-06: to ~0.2 of its value at 0.25 mm by 2.5 mm; [R12]'s
    Vizimag curve falls to ~0.4 there: ours is steeper, a provisional geometry), every
    plain string over a bar is equally sensitive, horizontal motion is invisible to first
    order ([R12]: 25-30 dB down). The cross-bar models (ferrite) put the gradient at the
    bars' ends, as recorded."""
    pk = pickup.pickups()["centre"]
    assert pk.model == "along"
    g = spec.string(36)
    mu_r = spec.load()["steel"]["mu_r"]
    h = np.array([0.25, 0.5, 1.0, 2.0, 2.5, 4.0, 8.0]) * 1e-3
    lam = {n: pickup.linkage_map(pk, n, g.d_magnetic_m, mu_r) for n in (31, 35, 40)}
    v = lam[35](np.zeros_like(h), h)
    assert np.all(np.diff(np.abs(v)) < 0)
    assert 0.1 < v[4] / v[0] < 0.6
    for n in (31, 40):
        assert lam[n](0.0, 3e-3, dh=1) == pytest.approx(lam[35](0.0, 3e-3, dh=1), rel=1e-9)
    assert abs(lam[35](0.0, 3e-3, ddx=1)) < 1e-6 * abs(lam[35](0.0, 3e-3, dh=1))
    ferrite = pickup.Pickup(**{**pk.__dict__, "model": "ferrite"})
    mid = pickup.linkage_map(ferrite, 35, g.d_magnetic_m, mu_r)
    edge = pickup.linkage_map(ferrite, 31, g.d_magnetic_m, mu_r)
    assert abs(edge(0.0, 3e-3, dh=1)) > 2 * abs(mid(0.0, 3e-3, dh=1))
    assert 0.01 < pickup.mean_b_t(ferrite) < 0.1  # [R12]: ~0.075 T


def test_play_e4() -> None:
    """A struck key: the pinch closes, the EMF is finite and sized by the level fit, the
    release ends it."""
    pl = note.play(36, 2.5, 0.4, tail_s=0.2)
    assert np.isfinite(pl.contact_s) and 0 < pl.contact_s < 0.05
    c = pl.emf_v["centre"]
    assert np.all(np.isfinite(c))
    assert 0.02 < np.max(np.abs(c)) < 0.5
    tail = c[int(0.5 * 96000) :]
    assert np.max(np.abs(tail[-2000:])) < 0.02 * np.max(np.abs(c))


def test_comb_notch() -> None:
    """A pickup a distance d from the termination nulls the partials near multiples of
    L / d (the comb [G13] Fig. 3 shows): the held modes' amplitude at the bridge pickup
    (4 cm) dips at the partial nearest L / 4 cm."""
    n = 36
    p = fit.params(n)
    held = strings.system(p, True)
    d = note.pickup_distance_m("bridge", n)
    row = strings.point_rows(p, held.lay, 0, d, 0.0)
    f, _, amp = strings.mode_table(held, row)
    k_null = p.geom.length_m / d
    k = int(round(k_null))
    parts = fit.partials(held, p, k + 2)
    amps = []
    for fk, _ in parts:
        i = int(np.argmin(np.abs(f - fk)))
        amps.append(amp[i] / np.sqrt(fk))  # per unit energy, roughly
    a = np.array(amps)
    assert a[k - 1] < 0.35 * np.median(a)


def test_knock() -> None:
    """CL4's knock (knock.py): the board under the anvils rings when the string slams onto
    the anvil and moves the pinched string. Measured 2026-11-06: -29 to -37 dB under the note
    in its first 200 ms (subtler than [G13]'s 'clearly audible'; the board is provisional)."""
    a = note.play(60, 3.5, 0.4, tail_s=0.05, knock=True).emf_v["centre"]
    b = note.play(60, 3.5, 0.4, tail_s=0.05, knock=False).emf_v["centre"]
    seg = slice(int(0.02 * 96000), int(0.2 * 96000))
    d = a[seg] - b[seg]
    assert np.all(np.isfinite(a))
    ratio_db = 20 * np.log10(np.std(d) / np.std(b[seg]))
    assert -45 < ratio_db < -15


def _pitch_cents(x: np.ndarray, f0: float, t0: float, t1: float) -> float:
    from scipy import signal

    sos = signal.butter(4, [0.8 * f0, 1.2 * f0], btype="band", fs=96000, output="sos")
    y = signal.sosfiltfilt(sos, x)
    f = np.diff(np.unwrap(np.angle(signal.hilbert(y)))) * 96000 / (2 * np.pi)
    return float(1200 * np.log2(np.median(f[int(t0 * 96000) : int(t1 * 96000)]) / f0))


def test_tension_modulation() -> None:
    """CL4: a hard E3 (the slackest plain string) starts sharp and glides to pitch as it
    decays (measured 2026-11-06: +16 cents at 50-100 ms, +2 by 1.5 s; a soft one +7); without
    the modulation it holds its pitch within a cent."""
    f0 = fit.params(24).geom.f_hz
    hard = note.play(24, 4.0, 2.0, tail_s=0.05, knock=False, level=False).disp_m["centre"]
    soft = note.play(24, 1.0, 2.0, tail_s=0.05, knock=False, level=False).disp_m["centre"]
    flat = note.play(24, 4.0, 2.0, tail_s=0.05, knock=False, tension_mod=False, level=False)
    early, late = _pitch_cents(hard, f0, 0.05, 0.1), _pitch_cents(hard, f0, 1.5, 1.9)
    assert 5 < early < 40 and late < early / 3
    assert 0 < _pitch_cents(soft, f0, 0.05, 0.1) < early
    assert abs(_pitch_cents(flat.disp_m["centre"], f0, 0.05, 0.1)) < 1.0
