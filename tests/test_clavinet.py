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


@pytest.mark.parametrize("n", [24, 36])
@pytest.mark.parametrize("held", [False, True])
def test_substructures_vs_finite_elements(n: int, held: bool) -> None:
    """strings.py's reduced model against plain FE of the whole string (no hinge, no
    reduction), lossless (measured 2026-11-06, CL1):
    - the ringing modes (sigma < 20/s: the speaking partials) within 4 cents (the hinge at
      the anvil puts the substructures ~2.5 cents low; the tuning takes it out);
    - the yarn's heavily damped modes within 25 cents;
    - decay rates within 5% where the loss is real; where only the end and pinch dashpots
      damp a mode (sigma < 0.3/s, lossless: a tiny end motion) within a factor of 3 (the
      two models move the ends' few microns differently; the A2 fit absorbs it);
    - the heavily damped ones within 15%."""
    p = fit.params(n)
    rows = [r for r in reference.compare(p, held, 3000.0) if r[0] > 20.0]
    assert len(rows) > 10
    for f_ref, f_cb, s_ref, s_cb in rows:
        cents = 1200 * abs(np.log2(f_cb / f_ref))
        assert cents < (4.0 if s_ref < 20 else 25.0)
        if s_ref > 1e-3:
            if s_ref < 0.3:
                assert 1 / 3 < s_cb / s_ref < 3
            else:
                assert s_cb == pytest.approx(s_ref, rel=0.05 if s_ref < 20 else 0.15)


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
    """[R12] Fig. 5 / [G13] Fig. 10: the linkage falls as the string rises, a string near
    a bar's edge more steeply than one near its middle; vertical motion dominates."""
    pk = pickup.pickups()["centre"]
    g = spec.string(36)
    mu_r = spec.load()["steel"]["mu_r"]
    h = np.array([0.5, 1.0, 2.0, 4.0, 8.0]) * 1e-3
    for n in (35, 31):  # mid-bar, bar edge
        lm = pickup.linkage_map(pk, n, g.d_magnetic_m, mu_r)
        lam = lm(np.zeros_like(h), h)
        assert np.all(np.diff(np.abs(lam)) < 0)
    mid = pickup.linkage_map(pk, 35, g.d_magnetic_m, mu_r)
    edge = pickup.linkage_map(pk, 31, g.d_magnetic_m, mu_r)
    assert abs(edge(0.0, 3e-3, dh=1)) > 2 * abs(mid(0.0, 3e-3, dh=1))
    assert abs(mid(0.0, 3e-3, ddx=1)) < 0.5 * abs(mid(0.0, 3e-3, dh=1))
    assert 0.01 < pickup.mean_b_t(pk) < 0.1  # [R12]: ~0.075 T


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
