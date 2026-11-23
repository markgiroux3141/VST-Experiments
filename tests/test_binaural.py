"""The virtual head (docs/BINAURAL_PLAN.md): mesh voxelization, the SH far-field transform,
the rigid-sphere reference, the body solver against the exact sphere (GPU, small grid), the
room engine's direction-aware entries."""

from __future__ import annotations

import numpy as np
import pytest

from varimu.binaural.analytic import sphere_hrtf
from varimu.binaural.mesh import sphere_mesh, voxelize
from varimu.binaural.sphere import gauss_grid, nm_list, transform, ylm


def test_voxelized_sphere_has_the_meshs_volume():
    m = sphere_mesh(0.05, 5)
    assert m.open_edges() == 0
    dx = 0.002
    n = 60
    s = voxelize(m, np.full(3, -(n - 1) / 2 * dx), dx, (n, n, n))
    assert abs(s.sum() * dx**3 / m.volume_m3() - 1) < 0.01


def test_sh_transform_recovers_a_band_limited_field():
    g = gauss_grid(20)
    n, _ = nm_list(20)
    rng = np.random.default_rng(1)
    c = (rng.standard_normal(len(n)) + 1j * rng.standard_normal(len(n))) * (n <= 12)
    p = (ylm(20, g.theta, g.phi) @ c)[None, :]
    sh = transform(g, p, np.array([1e5]), 0.1, 343.0)
    assert np.abs(sh.coeffs[0] - c).max() < 1e-12


def test_sphere_reference_matches_the_capsule_series_on_the_surface():
    from varimu.mics.free_field import sphere_entry_factors

    f = np.array([300.0, 3000.0, 8000.0])
    for g in (0.0, 1.0, 2.5):
        ours = sphere_hrtf(f, [np.cos(g)], 0.0875, 0.0875, 343.0)[0]
        ref, _ = sphere_entry_factors(f, g, 0.0875, 1e-5)
        assert np.max(np.abs(20 * np.log10(np.abs(ours / ref)))) < 0.01


def _gpu():
    roomsim = pytest.importorskip("roomsim")
    if not hasattr(roomsim, "body_run"):
        pytest.skip("roomsim without the body solver: uv sync --extra fast")
    try:
        roomsim.gpu_info()
    except RuntimeError:
        pytest.skip("no GPU")


def test_the_body_solver_hears_a_rigid_sphere_as_the_series_does():
    """A 2 mm grid, receivers gated before the faces answer: the far field of a source at
    the sphere's side against the exact series to 4 kHz (B1's check at a test's size)."""
    _gpu()
    from varimu.binaural.solve import C_M_S, RunSpec, ear_point, run, spectra
    from varimu.binaural.sphere import unit_vectors

    a, R = 0.0875, 0.13
    spec = RunSpec(dx_m=0.002, radius_m=R, order=20, half_m=0.36, sponge_m=0.03, g_max=0.05,
                   duration_s=0.0018)  # fmt: skip
    mesh = sphere_mesh(a, 5)
    src = ear_point(mesh, "left", spec.dx_m)
    g = gauss_grid(spec.order)

    def field(m, s):
        f, P = spectra(run(m, spec, s, log=None), 512)
        return f, transform(g, P, f, R, C_M_S)

    f, ref = field(None, np.zeros(3))
    f, head = field(mesh, src)
    az = np.radians(np.arange(0, 360, 30.0))
    th = np.full_like(az, np.pi / 2)
    H = head.at(th, az) / ref.at(th, az)
    A = sphere_hrtf(f, unit_vectors(th, az) @ np.array([0, 1.0, 0]), a, np.linalg.norm(src), C_M_S)
    sel = (f >= 200) & (f <= 4000)
    err = np.abs(20 * np.log10(np.abs(H[:, sel] / A[:, sel])))
    assert err.max() < 1.5, err.max()


def test_capsule_entries_unchanged_and_a_head_ear_sees_direction():
    """shoebox._entries gives a capsule's table the angle to its aim, as before; a head's
    ear (here the analytic sphere) leads for a source on its side."""
    from varimu.binaural.render import SphereHead
    from varimu.binaural.room import head_mics
    from varimu.rooms.shoebox import Mic, _entries

    class Probe:
        f_grid = np.array([0.0, 1.0])

        def at(self, th, r):
            return th[:, None] * np.ones(2), r[:, None] * np.ones(2)

    aim = np.array([1.0, 0, 0])
    m = Mic(np.zeros(3), aim, Probe())
    v = np.array([[1.0, 1.0, 0.0], [0.0, -2.0, 0.0]])
    r = np.linalg.norm(v, axis=1)
    th, _ = _entries(m, v, r)
    assert np.allclose(th[:, 0], np.arccos(np.clip((v @ aim) / r, -1, 1)))
    left, right = head_mics(SphereHead(), np.zeros(3), facing_deg=0.0, eq=False)
    # from 60 deg left (straight opposite an ear is the sphere's bright spot)
    u = np.array([[np.cos(np.radians(60)), np.sin(np.radians(60)), 0.0]])
    fl, _ = _entries(left, u, np.array([np.inf]), unit=True)
    fr, _ = _entries(right, u, np.array([np.inf]), unit=True)
    f = left.table.f_grid
    k = np.argmin(np.abs(f - 4000))
    assert abs(fl[0, k]) > 2 * abs(fr[0, k])  # head shadow


def test_cached_head_does_not_take_a_variant_for_its_base(tmp_path, monkeypatch):
    from varimu.binaural import hrtf

    monkeypatch.setattr(hrtf, "CACHE", tmp_path)
    (tmp_path / "heads").mkdir()
    loaded = []
    monkeypatch.setattr(hrtf.HeadHrtf, "load", classmethod(lambda cls, p: loaded.append(p.name)))
    (tmp_path / "heads" / "hutubs_pp4-pinna130_0123456789abcdef0123.npz").touch()
    assert hrtf.cached_head("hutubs_pp4") is None
    (tmp_path / "heads" / "hutubs_pp4_fedcba9876543210fedc.npz").touch()
    hrtf.cached_head("hutubs_pp4")
    assert loaded == ["hutubs_pp4_fedcba9876543210fedc.npz"]


def _head_scene(chain: str, **mic):
    from varimu.rooms.scene import load_scene

    return load_scene(
        {
            "name": "h",
            "room": {"dims_m": [5, 4, 3], "materials": {"walls": "anechoic",
                     "floor": "anechoic", "ceiling": "anechoic"}},
            "sources": [{"name": "A", "clip": "x.wav", "spl_db": 80, "position_m": [3, 3, 1.2]}],
            "mics": [{"name": "Head", "head": "sphere", "chain": chain,
                      "position_m": [2, 2, 1.2], "aim": {"azimuth_deg": 30}, **mic}],
        }
    )  # fmt: skip


def test_a_head_mic_is_two_ears_panned_hard():
    s = _head_scene("omni_clean", noise=True)
    assert [(m.name, m.pan, m.ear, m.head_of) for m in s.mics] == [
        ("Head.L", -1.0, "left", "Head"),
        ("Head.R", 1.0, "right", "Head"),
    ]
    assert all(m.head == "sphere" and m.noise and m.azimuth_deg == 30 for m in s.mics)


def test_a_head_needs_a_pressure_chain():
    with pytest.raises(ValueError, match="pressure"):
        _head_scene("u47_v76")
