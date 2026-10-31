"""The tape medium (docs/TAPE_PLAN.md, TM2): varimu.devices.tape's head fields, playback by
reciprocity, demagnetization and recording."""

from __future__ import annotations

import math

import numpy as np
import pytest

from varimu.devices.preisach import OE_A_PER_M, Preisach, PreisachParams
from varimu.devices.tape import (
    MU0,
    HeadGeometry,
    Slab,
    demag_field,
    demag_kernel,
    head_hx,
    head_hx_spectrum,
    playback_emf,
    record,
)

OE = OE_A_PER_M
HEAD = HeadGeometry(gap_m=6.35e-6, pole_m=2e-3, relax_m=0.5e-3)


def test_the_head_field_has_its_closed_form_spectrum():
    """head_hx sampled finely, Fourier transformed, against head_hx_spectrum."""
    dx = 0.05e-6
    x = (np.arange(1 << 18) - (1 << 17)) * dx
    for y in (0.5e-6, 3e-6):
        f = head_hx(HEAD, x, np.full_like(x, y))
        spec = np.fft.fftshift(np.fft.fft(np.fft.ifftshift(f))).real * dx
        k = 2 * math.pi * np.fft.fftshift(np.fft.fftfreq(len(x), dx))
        sel = (np.abs(k) > 2e4) & (np.abs(k) < 2e6)
        want = head_hx_spectrum(HEAD, k[sel], y)
        assert np.abs(spec[sel] - want).max() < 1e-3 * np.abs(want).max()


def test_the_theory_losses_are_in_the_geometry():
    """Gap loss sinc(pi g / lambda), Wallace's 54.6 d / lambda dB, and no response at
    infinite wavelength (the poles' finite length: the head bump's other side)."""
    k = 2 * math.pi / np.array([20e-6, 50e-6, 200e-6])
    # An abrupt pole edge e = g/2 + p away: sinc(k g / 2) - cos(k e) at the head's surface.
    abrupt = HeadGeometry(HEAD.gap_m, 1e-3, 0.0)
    s = head_hx_spectrum(abrupt, k, 1e-12) / HEAD.gap_m
    e = HEAD.gap_m / 2 + 1e-3
    np.testing.assert_allclose(
        s, np.sinc(k * HEAD.gap_m / (2 * math.pi)) - np.cos(k * e), rtol=1e-6, atol=1e-9
    )
    d = 2e-6
    lam = 2 * math.pi / k
    wallace = 20 * np.log10(head_hx_spectrum(HEAD, k, 1e-6) / head_hx_spectrum(HEAD, k, 1e-6 + d))
    np.testing.assert_allclose(wallace, 54.575 * d / lam, rtol=1e-3)
    assert head_hx_spectrum(HEAD, np.array([1e-3]), 1e-6)[0] == pytest.approx(0.0, abs=1e-12)


def test_playback_is_reciprocity_and_rises_6_db_per_octave():
    """A sinusoidal pattern through the repro head: the EMF's amplitude is v k mu0 W Ms
    (H/I) dy sum over layers of the field's spectrum: the gap, spacing and thickness
    losses, and doubling the frequency at constant flux doubles the EMF."""
    slab = Slab(12.7e-6, 8, 0.25e-6, 0.5e-6)
    head = HeadGeometry(6.35e-6, 100e-6, 50e-6)  # the pattern runs far past its poles
    v, w, ms, hpa = 0.381, 6.3e-3, 1e5, 2e5
    amps = {}
    for lam in (100e-6, 50e-6, 25e-6):
        k = 2 * math.pi / lam
        n = int(round(40 * lam / slab.ds_m))
        s = np.arange(n) * slab.ds_m
        m = np.tile(0.3 * np.sin(k * s), (slab.layers, 1))
        s_rep = s[n // 4 : 3 * n // 4 : 3]
        emf = playback_emf(m, 0.0, slab, head, hpa, w, ms, s_rep, np.full(len(s_rep), v))
        spec = sum(
            head_hx_spectrum(head, np.array([k]), slab.spacing_m + y)[0] for y in slab.depths_m
        )
        dy = slab.thickness_m / slab.layers
        want = -v * MU0 * w * ms * hpa * dy * 0.3 * k * spec * np.cos(k * s_rep)
        np.testing.assert_allclose(emf, want, atol=2e-4 * np.abs(want).max())
        amps[lam] = np.abs(want).max()
    # Same flux, twice the frequency: twice the EMF, times the losses' ratio.
    for lam in (100e-6, 50e-6):
        k1, k2 = 2 * math.pi / lam, 4 * math.pi / lam
        loss = lambda k: sum(  # noqa: E731
            head_hx_spectrum(head, np.array([k]), slab.spacing_m + y)[0] for y in slab.depths_m
        )
        assert amps[lam / 2] / amps[lam] == pytest.approx(2.0 * loss(k2) / loss(k1), rel=1e-9)


def test_the_demag_kernel_is_the_slabs_factor():
    slab = Slab(12.7e-6, 12, 0.5e-6, 0.5e-6)
    k = np.array([1e3, 1.65e4, 2.47e5, 1e6])
    kd = k * slab.thickness_m
    np.testing.assert_allclose(
        demag_kernel(k, slab).sum(axis=2).mean(axis=1), 1 - (1 - np.exp(-kd)) / kd, rtol=1e-9
    )


def test_a_long_pattern_demagnetizes_by_the_slab_factor():
    slab = Slab(12.7e-6, 6, 0.5e-6, 0.5e-6)
    lam = 50e-6
    s = np.arange(4000) * slab.ds_m
    m = np.tile(np.sin(2 * math.pi * s / lam), (slab.layers, 1))
    h = demag_field(m, slab, 1.0)[:, 1500:2500].mean(axis=0)
    kd = 2 * math.pi / lam * slab.thickness_m
    n = 1 - (1 - math.exp(-kd)) / kd
    np.testing.assert_allclose(h, -n * m[0, 1500:2500], atol=0.01 * n)


@pytest.fixture(scope="module")
def ensemble() -> Preisach:
    return Preisach(PreisachParams(293 * OE, 0.33, 46 * OE, 2000 * OE))


def _harmonics(m: np.ndarray, s: np.ndarray, lam_m: float, n: int = 3) -> np.ndarray:
    """Complex amplitudes of the pattern's first n harmonics of wavelength lam_m (per
    layer, summed over layers), by projection over the whole wavelengths it covers."""
    span = int(np.floor((s[-1] - s[0]) / lam_m)) * lam_m
    sel = s < s[0] + span
    k = 2 * math.pi / lam_m
    total = m.sum(axis=0)[sel]
    return np.array(
        [2 * np.mean(total * np.exp(-1j * h * k * (s[sel] - s[0]))) for h in range(1, n + 1)]
    )


def _record(pre, sign: float, f_hz: float = 4000.0, sub: int = 1, phases: int = 4):
    """A tone recorded into 4 layers: its first three harmonics (complex, summed), averaged
    over `phases` phases of the bias oscillator (it runs free of the signal)."""
    v, slab = 0.381, Slab(12.7e-6, 4, 0.5e-6, 0.5e-6)
    head = HeadGeometry(25e-6, 2e-3, 1e-3)
    lam = v / f_hz
    s = 150e-6 + np.arange(int(round(4 * lam / slab.ds_m))) * slab.ds_m
    out = []
    for ph in np.arange(phases) * 2 * math.pi / phases:
        m = record(
            pre,
            head,
            slab,
            lambda t: sign * 60 * OE * np.sin(2 * math.pi * f_hz * t),
            500 * OE,
            70e3,
            lambda t: v * t,
            0.0,
            (s[-1] + 200e-6) / v,
            s,
            sub=sub,
            hg_signal_max=60 * OE,
            bias_phase_rad=ph,
        )
        out.append(_harmonics(m, s, lam))
    return np.mean(out, axis=0)


def test_recording_is_odd_in_the_audio_band(ensemble):
    """No even harmonics from the medium itself, over the bias oscillator's phases: the
    negated tone records exactly the negated pattern, and the 2nd harmonic (the recording's
    start, a few wavelengths in) is far below the 3rd. At one locked bias phase the 2nd
    reaches about -46 dB: about one bias cycle crosses the recording zone, so a cell's
    freeze depends on the bias's phase there (a real effect that a free-running
    oscillator averages away)."""
    a, b = _record(ensemble, 1.0), _record(ensemble, -1.0)
    np.testing.assert_allclose(b, -a, atol=1e-7 * abs(a[0]))
    assert abs(a[1]) < 10 ** (-50 / 20) * abs(a[0]) and abs(a[1]) < 0.2 * abs(a[2])


def test_bias_peaks_suffice(ensemble):
    """Sampling each bias half cycle at its peak only, against 9 samples per half cycle
    (the model only needs the field's extrema): the true extremum differs from the
    carrier's peak by second-order terms."""
    a, b = _record(ensemble, 1.0, sub=1), _record(ensemble, 1.0, sub=9)
    assert abs(a[0] - b[0]) < 0.02 * abs(b[0])
    assert abs(abs(a[2]) - abs(b[2])) < 0.1 * abs(b[2])


def test_both_field_components_and_the_perpendicular_spectrum():
    """head_field's Hx is head_hx; its Hy's Fourier transform is i sgn(k) times Hx's."""
    from varimu.devices.tape import head_field, head_hy_spectrum

    dx = 0.05e-6
    x = (np.arange(1 << 18) - (1 << 17)) * dx
    for head in (HEAD, HeadGeometry(6.35e-6, 2e-3, 0.0)):
        for y in (0.5e-6, 3e-6):
            hx, hy = head_field(head, x, np.full_like(x, y))
            np.testing.assert_allclose(hx, head_hx(head, x, np.full_like(x, y)), atol=1e-9)
            if head.relax_m > 0:
                spec = np.fft.fftshift(np.fft.fft(np.fft.ifftshift(hy))) * dx
                k = 2 * math.pi * np.fft.fftshift(np.fft.fftfreq(len(x), dx))
                sel = (np.abs(k) > 2e5) & (np.abs(k) < 2e6)
                want = head_hy_spectrum(head, k[sel], y)
                assert np.abs(spec[sel] - want).max() < 2e-3 * np.abs(want).max()
    # Over the gap's centre the field points along the tape; either side of it, Hy has
    # opposite signs.
    hx, hy = head_field(HEAD, np.array([0.0, 10e-6, -10e-6]), np.full(3, 1e-6))
    assert hx[0] == pytest.approx(2 / math.pi * math.atan(3.175)) and abs(hy[0]) < 1e-9
    assert hy[1] * hy[2] < 0


def test_the_vector_demag_field_is_the_slabs():
    """Uniform M_x and M_y through the coating (a long wavelength): the x and y
    demagnetizing factors (1 - (1 - e^{-kd}) / (kd)) and (1 - e^{-kd}) / (kd), summing to 1;
    M_x's x field as the scalar kernel gives it."""
    from varimu.devices.tape import demag_field_vector

    slab = Slab(12.7e-6, 6, 0.5e-6, 0.5e-6)
    lam = 50e-6
    s = np.arange(4000) * slab.ds_m
    wave = np.sin(2 * math.pi * s / lam)
    m = np.tile(wave, (slab.layers, 1))
    z = np.zeros_like(m)
    kd = 2 * math.pi / lam * slab.thickness_m
    nx = 1 - (1 - math.exp(-kd)) / kd
    mid = slice(1500, 2500)
    hx, hy = demag_field_vector(m, z, slab, 1.0)
    np.testing.assert_allclose(hx, demag_field(m, slab, 1.0), atol=2e-3)
    np.testing.assert_allclose(hx[:, mid].mean(axis=0), -nx * wave[mid], atol=0.01)
    hx, hy = demag_field_vector(z, m, slab, 1.0)
    np.testing.assert_allclose(hy[:, mid].mean(axis=0), -(1 - nx) * wave[mid], atol=0.01)


def test_the_vector_demag_operator_is_symmetric():
    """The demagnetizing field derives from an energy: <M_x, H_x[M_y]> = <M_y, H_y[M_x]>
    for any patterns (this checks the cross terms)."""
    from varimu.devices.tape import demag_field_vector

    slab = Slab(12.7e-6, 5, 0.5e-6, 0.5e-6)
    rng = np.random.default_rng(5)
    mx, my = rng.normal(size=(2, slab.layers, 600))
    z = np.zeros_like(mx)
    hx_from_y, _ = demag_field_vector(z, my, slab, 1.0, q=64)
    _, hy_from_x = demag_field_vector(mx, z, slab, 1.0, q=64)
    a, b = float((mx * hx_from_y).sum()), float((my * hy_from_x).sum())
    assert a == pytest.approx(b, rel=2e-3), (a, b)


def _rust_or_skip():
    circuitsim = pytest.importorskip("circuitsim")
    if not hasattr(circuitsim, "tape_record"):
        pytest.skip("circuitsim without the tape kernel (rebuild: uv sync --extra fast)")
    return circuitsim


def test_the_rust_particles_agree(ensemble):
    """circuitsim's Preisach tables and corner formula against the reference."""
    circuitsim = _rust_or_skip()
    rng = np.random.default_rng(6)
    h = rng.normal(0.0, 400 * OE, (200, 40)) * np.linspace(1.5, 0.1, 40)
    p = ensemble.p
    got = circuitsim.tape_state_after(
        (p.hc_median_a_m, p.sigma_ln_hc, p.sigma_hi_a_m, p.h_max_a_m, p.n_table), h.ravel(), 40
    )
    np.testing.assert_allclose(got, ensemble.state_after(h), atol=1e-12)


@pytest.mark.parametrize("vector", [False, True])
def test_the_rust_recording_agrees(ensemble, vector):
    """circuitsim's recording kernel against the reference: scalar and vector, with a
    steady field on the cells."""
    from varimu.devices.tape import Orientation

    _rust_or_skip()
    v, slab = 0.381, Slab(12.7e-6, 3, 0.5e-6, 0.5e-6)
    head = HeadGeometry(25e-6, 2e-3, 3e-3)
    s = 300e-6 + np.arange(300) * slab.ds_m
    rng = np.random.default_rng(7)
    hs = rng.normal(0.0, 5 * OE, (slab.layers, len(s)))
    hs = (hs, 0.5 * hs) if vector else hs
    kw = dict(
        hg_signal_max=40 * OE, h_static=hs, orientation=Orientation(3.0, 4) if vector else None
    )
    args = (
        ensemble,
        head,
        slab,
        lambda t: 40 * OE * np.sin(2 * math.pi * 3000.0 * t),
        500 * OE,
        70e3,
        lambda t: v * t,
        0.0,
        (s[-1] + 400e-6) / v,
        s,
    )
    a = record(*args, **kw)
    b = record(*args, engine="rust", **kw)
    for x, y in zip(a if vector else [a], b if vector else [b], strict=True):
        np.testing.assert_allclose(y, x, atol=1e-9)


def test_the_head_image_cancels_long_wavelength_demag():
    """Against the head (spacing -> 0), a long wavelength's x demagnetization nearly
    vanishes (the image of opposite sign), a short one's is untouched."""
    from varimu.devices.tape import demag_field_vector

    slab = Slab(12.7e-6, 6, 0.5e-6, 0.5e-6)
    s = np.arange(8000) * slab.ds_m
    mid = slice(3000, 5000)
    for lam, lo, hi in ((400e-6, 0.0, 0.2), (5e-6, 0.95, 1.05)):
        m = np.tile(np.sin(2 * math.pi * s / lam), (slab.layers, 1))
        z = np.zeros_like(m)
        free, _ = demag_field_vector(m, z, slab, 1.0)
        imaged, _ = demag_field_vector(m, z, slab, 1.0, image_spacing_m=1e-9)
        ratio = np.abs(imaged[:, mid]).mean() / np.abs(free[:, mid]).mean()
        assert lo < ratio < hi, (lam, ratio)


def test_the_tabulated_head_field_is_close(ensemble):
    """The Rust kernel's field table (1/40 of each layer's height, cubic) against the exact
    field: the recorded pattern within 1e-4 of Ms."""
    from varimu.devices.tape import Orientation

    _rust_or_skip()
    v, slab = 0.381, Slab(12.7e-6, 3, 0.5e-6, 0.5e-6)
    head = HeadGeometry(12.7e-6, 2e-3, 3e-3)
    s = 300e-6 + np.arange(400) * slab.ds_m
    args = (
        ensemble,
        head,
        slab,
        lambda t: 40 * OE * np.sin(2 * math.pi * 3000.0 * t),
        450 * OE,
        100e3,
        lambda t: v * t,
        0.0,
        (s[-1] + 400e-6) / v,
        s,
    )
    kw = dict(hg_signal_max=40 * OE, orientation=Orientation(1.5, 4), engine="rust")
    a = record(*args, **kw)
    b = record(*args, table_step=1 / 40, **kw)
    for x, y in zip(a, b, strict=True):
        np.testing.assert_allclose(y, x, atol=1e-4)
