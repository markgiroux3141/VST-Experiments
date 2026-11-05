"""The room loop (docs/ROOM_LOOP_PLAN.md R1-R3): entry tables, the shoebox with directions,
scenes."""

from __future__ import annotations

import numpy as np
import pytest

from varimu.rooms import entries
from varimu.rooms.shoebox import Mic, Shoebox, aim_vector, responses
from varimu.separation.room import Room, air_absorption_db_per_m, impulse_response

FS = 96000


def test_body_table_matches_the_bem(tmp_path, monkeypatch):
    """The table, interpolated between its angles and distances, is the BEM's answer."""
    from varimu.mics.free_field import body_entry_factors

    monkeypatch.setattr(entries, "N_FREQ", 8)
    monkeypatch.setattr(entries, "CACHE", tmp_path)
    body = {"form": "cylinder", "radius_m": 6.35e-3, "length_m": 0.03}
    geom = {"diaphragm": {"radius_m": 4.45e-3}, "body": body}
    tab = entries.entry_table(geom, FS)
    assert tab.rear.shape == tab.front.shape and np.all(tab.rear == 0)  # no rear diaphragm
    fg = tab.f_grid[1:]
    for th_deg, d in [(30.0, 1.0), (31.25, 0.25), (151.25, np.inf)]:
        got, _ = tab.at(np.radians([th_deg]), np.array([d]))
        want, _ = body_entry_factors(fg, [np.radians(th_deg)], body, 4.45e-3, d)
        err = np.abs(got[0, 1:] - want[:, 0]) / np.abs(want[:, 0])
        sel = fg < 20e3
        assert np.all(err[sel] < 0.02), (th_deg, d, err)
    assert np.all(tab.at(np.array([0.3]), np.array([0.5]))[0][:, 0] == 1)  # DC


def test_path_table_is_the_spherical_wave():
    tab = entries.entry_table({"path_m": 0.02}, FS)
    i = np.searchsorted(tab.f_grid, 1000.0)
    k = 2 * np.pi * tab.f_grid[i] / entries.C_AIR
    f, r = tab.at(np.array([0.0]), np.array([1.0]))
    assert f[0, i] == pytest.approx(1 / 0.99 * np.exp(1j * k * 0.01), rel=1e-9)
    assert r[0, i] == pytest.approx(1 / 1.01 * np.exp(-1j * k * 0.01), rel=1e-9)


def _omni():
    return entries.entry_table({}, FS)


def test_anechoic_room_is_the_free_field():
    """An anechoic shoebox: the direct sound alone, 1 / r late by r / c through the air."""
    room = Shoebox((8.0, 8.0, 8.0), ("anechoic",) * 6)
    src, pos = np.array([4.0, 4.0, 4.0]), np.array([4.0, 5.5, 4.0])
    h = responses(room, [src], [Mic(pos, aim_vector(-90), _omni())], FS, length_s=0.1, tail=False)
    x = h[0, 0, 0]
    f = np.fft.rfftfreq(len(x), 1 / FS)
    got = np.fft.rfft(x)
    r = 1.5
    air = 10 ** (-air_absorption_db_per_m(np.maximum(f, 1.0)) * r / 20)
    want = air / r * np.exp(-2j * np.pi * f * r / 343.2)
    sel = (f > 20) & (f < 20e3)
    err = np.abs(got[sel] - want[sel]) / np.abs(want[sel])
    assert np.max(err) < 0.01


def test_omni_early_part_matches_the_mono_room():
    """With an omni the early part is the separation study's room (its 1 / 4 pi r scale)."""
    old = Room("t", (5.0, 4.0, 2.6), "furnished_wall", "wood_floor", "gypsum_on_studs", "t")
    room = Shoebox((5.0, 4.0, 2.6), ("furnished_wall",) * 4 + ("wood_floor", "gypsum_on_studs"))
    src, mic = np.array([1.2, 1.5, 1.3]), np.array([3.4, 2.1, 1.1])
    ref = impulse_response(old, tuple(src), tuple(mic), FS) * 4 * np.pi
    h = responses(room, [src], [Mic(mic, aim_vector(0), _omni())], FS, tail=False)[0, 0, 0]
    n = int(0.055 * FS)  # before the fade toward the tail
    # below 6 kHz: the old room's air is per octave up to 8 kHz, the new one per frequency
    m = 1 << 16
    f = np.fft.rfftfreq(m, 1 / FS)

    def low(x):
        return np.fft.irfft(np.fft.rfft(x[:n], m) * (f < 6000), m)

    err = np.sqrt(np.sum((low(h) - low(ref)) ** 2) / np.sum(low(ref) ** 2))
    assert 20 * np.log10(err) < -30


def test_tail_continues_the_images_and_spaced_mics_cohere_like_a_diffuse_field():
    room = Shoebox((7.0, 5.5, 3.2), ("furnished_wall",) * 4 + ("wood_floor", "gypsum_on_studs"))
    om = _omni()
    mics = [Mic(np.array([3.0, 3.0, 1.5]), aim_vector(0), om),
            Mic(np.array([3.3, 3.0, 1.5]), aim_vector(0), om)]  # fmt: skip
    h = responses(room, [np.array([1.5, 1.2, 1.2])], mics, FS)[0]
    a, b = h[0, 0], h[1, 0]
    # energy continuity across the hand-over at 80 ms (60-80 ms vs 80-100 ms), within 3 dB
    e1 = np.sum(a[int(0.06 * FS) : int(0.08 * FS)] ** 2)
    e2 = np.sum(a[int(0.08 * FS) : int(0.10 * FS)] ** 2)
    assert abs(10 * np.log10(e2 / e1)) < 3
    # tail coherence at 0.3 m: high at 150 Hz (sinc(kd) ~ 0.65), low at 2 kHz
    from scipy.signal import coherence

    t0, t1 = int(0.1 * FS), int(0.5 * FS)
    flat = np.exp(3 * np.log(10) * np.arange(t1 - t0) / FS / room.rt60_s()[3])  # stationary
    a, b = a[t0:t1] * flat, b[t0:t1] * flat
    f, coh = coherence(a, b, FS, nperseg=4096)
    lo = coh[(f > 100) & (f < 200)].mean()
    f, coh = coherence(a, b, FS, nperseg=512)
    hi = coh[(f > 1500) & (f < 6000)].mean()
    assert lo > 0.3 and hi < 0.15, (lo, hi)


def test_scene_loads_and_its_pressures_are_the_room(tmp_path):
    from varimu.rooms.scene import load_scene, mic_pressures

    clip = tmp_path / "x.wav"
    import soundfile as sf

    rng = np.random.default_rng(0)
    sf.write(clip, rng.standard_normal(4800).astype("<f4"), FS, subtype="FLOAT")
    scene = load_scene(
        {
            "name": "t",
            "room": {"dims_m": [6, 6, 6], "materials": {"walls": "anechoic", "floor": "anechoic",
                                                         "ceiling": "anechoic"}},
            "sources": [{"name": "s", "clip": str(clip), "spl_db": 94, "position_m": [3, 3, 3]}],
            "mics": [{"name": "m", "chain": "capsule_bk4134", "position_m": [3, 4, 3],
                      "aim": {"azimuth_deg": -90}}],
        }
    )  # fmt: skip
    p, kinds, n = mic_pressures(scene, FS, [np.ones(2000)])
    assert kinds == ["pressure"]
    lag = int(round(1 / 343.2 * FS))
    edge = np.argmax(np.diff(p[0, 0, 0]))
    assert abs(edge - lag) <= 2
    assert p[0, 0, 0, lag + 1000] == pytest.approx(1.0, rel=1e-3)  # 1 Pa at 1 m, 1 m away


def test_bmld_and_better_ear_on_the_textbook_cases():
    """N0S0: no binaural advantage; N0Spi: ~15 dB at low frequencies (the EC model's k at
    250 Hz); a target hard left against a masker hard right: the better ear is far ahead."""
    from varimu.rooms.binaural import band_measures

    rng = np.random.default_rng(1)
    n = FS
    s, m = rng.standard_normal(n), rng.standard_normal(n)
    diotic = band_measures(np.stack([s, s]), np.stack([m, m]), FS)
    assert np.allclose(diotic["bmld_db"], 0.0, atol=1e-9)
    assert abs(np.mean(diotic["be_tmr_db"])) < 0.3 and np.max(np.abs(diotic["be_tmr_db"])) < 2
    spi = band_measures(np.stack([s, -s]), np.stack([m, m]), FS)
    low = spi["bmld_db"][(spi["fc_hz"] > 200) & (spi["fc_hz"] < 300)]
    assert np.all((low > 13) & (low < 16)), low
    panned = band_measures(np.stack([s, 0 * s]), np.stack([0 * m, m]), FS)
    assert np.all(panned["be_tmr_db"] > 40)


# --- rooms of any floor plan (docs/ROOM_LOOP_PLAN.md R6) ---

RECT = [[0, 0], [7, 0], [7, 5.5], [0, 5.5]]
FURNISHED = ("furnished_wall", "wood_floor", "gypsum_on_studs")


def _rect_room():
    from varimu.rooms.polyroom import PolyRoom

    return PolyRoom(RECT, "flat", 3.2, None, 0.0, 8, *FURNISHED)


def test_polyroom_finds_the_shoebox_images():
    from varimu.rooms.polyroom import image_sources, valid_paths
    from varimu.rooms.shoebox import images

    src, mic = np.array([2.0, 2.55, 1.3]), np.array([4.5, 2.25, 1.6])
    pr = _rect_room()
    pos, seq = image_sources(pr, src, 3)
    got = pos[valid_paths(pr, pos, seq, mic)]
    sb = Shoebox((7.0, 5.5, 3.2), ("furnished_wall",) * 4 + ("wood_floor", "gypsum_on_studs"))
    spos, hits = images(sb, src, 200.0)
    want = spos[hits.sum(1) <= 3]
    assert {tuple(np.round(p, 6)) for p in got} == {tuple(np.round(p, 6)) for p in want}


def test_ray_traced_decay_meets_eyring_and_the_image_energy():
    """In a shoebox: RT within 15% of Eyring's; the tail's level 4 pi c e(t) / V within
    0.5 dB of the exact image sources' energy (specular rays)."""
    import varimu.rooms.polyroom as P
    from varimu.rooms.shoebox import images
    from varimu.separation.room import BANDS_HZ

    pr = _rect_room()
    src, mic = np.array([2.0, 2.55, 1.3]), np.array([4.5, 2.25, 1.6])
    t, e = P.ray_decay(pr, src, 1.5, n_rays=8000)
    sb = Shoebox((7.0, 5.5, 3.2), ("furnished_wall",) * 4 + ("wood_floor", "gypsum_on_studs"))
    rt = P.rt60_from_decay(t, e)
    assert np.all(np.abs(rt / sb.rt60_s() - 1) < 0.15), (rt, sb.rt60_s())
    saved = dict(P.SCATTERING)
    try:
        P.SCATTERING.update({k: 0.0 for k in P.SCATTERING})
        t, e = P.ray_decay(pr, src, 0.3, n_rays=8000)
    finally:
        P.SCATTERING.update(saved)
    c = 343.2
    pos, hits = images(sb, src, c * 0.3)
    lb = hits @ np.log(np.sqrt(1 - sb.alphas()))
    r = np.linalg.norm(pos - mic, axis=1)
    air = air_absorption_db_per_m(BANDS_HZ)
    a2 = np.exp(2 * lb) / r[:, None] ** 2 * 10 ** (-air[None, :] * r[:, None] / 10)
    sel = (r / c >= 0.1) & (r / c < 0.2)
    ts = (t >= 0.1) & (t < 0.2)
    form = 4 * np.pi * c / pr.volume_m3() * np.trapezoid(e[:, ts], t[ts], axis=1)
    assert np.all(np.abs(10 * np.log10(a2[sel].sum(0) / form)) < 0.5)


def test_l_shaped_room_hides_the_direct_sound_and_ceilings_shape_the_room():
    from varimu.rooms.polyroom import PolyRoom, image_sources, valid_paths

    room = PolyRoom([[0, 0], [8, 0], [8, 3], [3, 3], [3, 8], [0, 8]], "gable", 2.8, 4.5)
    src, mic = np.array([6.5, 1.5, 1.5]), np.array([1.5, 6.5, 1.5])
    pos, seq = image_sources(room, src, 3)
    ok = valid_paths(room, pos, seq, mic)
    assert not ok[0] and ok.sum() > 0  # no direct sound round the corner, reflections do
    assert room.inside(np.array([4.0, 1.5, 4.3])) and not room.inside(np.array([0.3, 1.5, 3.5]))
    vault = PolyRoom(RECT, "vault", 3.0, 5.0, 0.0, 8)
    assert vault.height_at(np.array([3.5, 2.0])) == pytest.approx(5.0)
    assert vault.height_at(np.array([0.0, 2.0])) == pytest.approx(3.0)


def test_scene_with_a_floor_plan_renders_its_pressures(tmp_path):
    from varimu.rooms.polyroom import PolyRoom
    from varimu.rooms.scene import load_scene, mic_pressures

    scene = load_scene(
        {
            "name": "t",
            "room": {"floor_m": [[0, 0], [5, 0.3], [5.4, 4], [0.2, 4.4]],
                     "ceiling": {"type": "shed", "height_m": 2.6, "peak_m": 3.4, "axis_deg": 90},
                     "materials": {"walls": "furnished_wall", "floor": "wood_floor",
                                   "ceiling": "acoustic_tile"}},
            "sources": [{"name": "s", "clip": "x.wav", "spl_db": 94, "position_m": [2, 2, 1.2]}],
            "mics": [{"name": "m", "chain": "capsule_bk4134", "position_m": [3, 2.2, 1.4],
                      "aim": {"azimuth_deg": 180}}],
            "settings": {"tail_s": 0.6},
        }
    )  # fmt: skip
    assert isinstance(scene.room, PolyRoom)
    p, kinds, _ = mic_pressures(scene, FS, [np.r_[1.0, np.zeros(99)]])
    h = p[0, 0, 0]
    assert abs(np.argmax(np.abs(h)) - int(round(np.linalg.norm([1, 0.2, 0.2]) / 343.2 * FS))) <= 2
    assert np.sum(h[int(0.1 * FS) :] ** 2) > 0  # a tail


# --- a material per face (docs/ROOM_LOOP_PLAN.md R7) ---


def test_one_absorbent_wall_decays_as_eyring_and_the_rays_say():
    """Drapes on one long wall: the ray-traced RT falls as Eyring's area-weighted absorption
    says (each within 15% of the other, and the drop from the bare room within 10%)."""
    from varimu.rooms.polyroom import PolyRoom, ray_decay, rt60_from_decay

    src = np.array([2.0, 2.55, 1.3])
    bare = _rect_room()
    draped = PolyRoom(RECT, "flat", 3.2, None, 0.0, 8, *FURNISHED,
                      face_materials={"wall 1": "heavy_drapes"})  # fmt: skip
    assert draped.material(draped.faces[2]) == "heavy_drapes"  # the floor is face 0
    rt_bare = rt60_from_decay(*ray_decay(bare, src, 2.0, n_rays=8000))
    rt = rt60_from_decay(*ray_decay(draped, src, 2.0, n_rays=8000))
    ey_bare, ey = bare.rt60_eyring_s(), draped.rt60_eyring_s()
    assert np.all(np.abs(rt / ey - 1) < 0.15), (rt, ey)
    assert np.all(np.abs((rt / rt_bare) / (ey / ey_bare) - 1) < 0.10)
    assert np.all(rt[2:] < 0.9 * rt_bare[2:])  # mids and highs clearly shorter (8-23%)


def test_face_materials_follow_the_plan_as_given_and_default_to_the_rooms():
    from varimu.rooms.polyroom import PolyRoom, ray_decay

    cw = PolyRoom(RECT[::-1], "flat", 3.2, None, 0.0, 8, *FURNISHED,
                  face_materials={"wall 0": "plaster"})  # fmt: skip
    # the plan as given runs clockwise: its wall 0 (y = 5.5) is the stored edge 2
    walls = {f.index: cw.material(f) for f in cw.faces if f.kind == "wall"}
    assert walls == {0: "furnished_wall", 1: "furnished_wall", 2: "plaster", 3: "furnished_wall"}
    with pytest.raises(ValueError):
        PolyRoom(RECT, face_materials={"wall 9": "plaster"})
    with pytest.raises(ValueError):
        PolyRoom(RECT, face_materials={"wall 1": "velvet"})
    # naming a face with its default material changes nothing, bit for bit
    same = PolyRoom(RECT, "flat", 3.2, None, 0.0, 8, *FURNISHED,
                    face_materials={"wall 0": "furnished_wall", "floor": "wood_floor"})  # fmt: skip
    a = ray_decay(_rect_room(), np.array([2.0, 2.5, 1.3]), 0.5, n_rays=500)
    b = ray_decay(same, np.array([2.0, 2.5, 1.3]), 0.5, n_rays=500)
    assert np.array_equal(a[1], b[1])


# --- the GPU (docs/ROOM_LOOP_PLAN.md R9) ---


def _gpu_or_skip():
    from varimu.rooms import gpu

    if gpu.module() is None:
        pytest.skip("roomsim isn't installed (uv sync --extra fast)")
    return gpu


def test_triangles_cover_every_face():
    from varimu.rooms.polyroom import PolyRoom

    for room in (
        _rect_room(),
        PolyRoom([[0, 0], [8, 0], [8, 3], [3, 3], [3, 8], [0, 8]], "gable", 2.8, 4.5),
        PolyRoom(RECT, "vault", 3.0, 5.0, 30.0, 6),
    ):
        tris, owner = room.triangles()
        area = np.linalg.norm(np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]), axis=1)
        per = np.bincount(owner, area / 2, minlength=len(room.faces))
        assert np.all(np.abs(per / np.array(room.areas_m2()) - 1) < 0.05)  # areas_m2 sampled
        for fi, f in enumerate(room.faces):  # every triangle lies on its face's plane
            v = tris[owner == fi].reshape(-1, 3)
            assert np.allclose(v @ f.normal, f.d, atol=1e-9)


@pytest.mark.parametrize("backend", ["cpu", "gpu"])
def test_roomsim_rays_agree_with_numpy(backend):
    """roomsim's ray tracer (its own random numbers) against polyroom's numpy loop: RTs
    within 2%, the energy at a mic over 50-300 ms within 0.5 dB."""
    gpu = _gpu_or_skip()
    if backend == "gpu" and gpu.gpu_info() is None:
        pytest.skip("no GPU")
    from varimu.rooms.polyroom import PolyRoom, ray_decay, rt60_from_decay

    room = PolyRoom([[0, 0], [8, 0], [8, 3], [3, 3], [3, 8], [0, 8]], "gable", 2.8, 4.5)
    src, mic = np.array([6.5, 1.5, 1.5]), np.array([1.5, 6.5, 1.5])
    ref = ray_decay(room, src, 2.0, n_rays=20000, receivers=[mic], backend="numpy")
    got = ray_decay(room, src, 2.0, n_rays=20000, receivers=[mic], backend=backend)
    assert np.all(np.abs(rt60_from_decay(*got[:2]) / rt60_from_decay(*ref[:2]) - 1) < 0.02)
    e_ref, e_got = ref[2][0][:, 50:300].sum(1), got[2][0][:, 50:300].sum(1)
    assert np.all(np.abs(10 * np.log10(e_got / e_ref)) < 0.5)


def test_gpu_image_spectra_are_numpys():
    gpu = _gpu_or_skip()
    if gpu.gpu_info() is None:
        pytest.skip("no GPU")
    room = Shoebox((7.0, 5.5, 3.2), ("furnished_wall",) * 4 + ("wood_floor", "gypsum_on_studs"))
    om = _omni()
    mics = [Mic(np.array([4.5, 2.25, 1.6]), aim_vector(0), om)]
    src = [np.array([2.0, 2.55, 1.3])]
    a = responses(room, src, mics, FS, tail=False, backend="numpy", length_s=0.2)
    g = responses(room, src, mics, FS, tail=False, backend="gpu", length_s=0.2)
    n = int(0.06 * FS)
    err = np.sqrt(np.sum((a[..., :n] - g[..., :n]) ** 2) / np.sum(a[..., :n] ** 2))
    assert 20 * np.log10(err) < -100


# --- the wave solver (docs/ROOM_LOOP_PLAN.md R10) ---


def test_admittance_gives_the_materials_absorption():
    from varimu.rooms import wave

    a_tab, b_tab = wave._alpha_table()
    for a in (0.02, 0.1, 0.3, 0.7):
        b = wave.beta_for_alpha(np.array([a]))[0]
        assert np.interp(b, b_tab, a_tab) == pytest.approx(a, abs=1e-4)
    assert wave.beta_for_alpha(np.array([0.0]))[0] == 0.0
    assert 0.94 < a_tab[-1] < 0.96  # the most a real locally reacting admittance absorbs


def test_first_order_entries_fit_the_tables():
    from varimu.rooms import wave

    om = _omni()
    a, b = wave.first_order_entries(om)
    assert np.allclose(a[0], 1, atol=1e-9) and np.allclose(b[0], 0, atol=1e-9)
    tab = entries.entry_table({"path_m": 0.02}, FS)  # front / rear 2 cm apart
    a, b = wave.first_order_entries(tab)
    sel = tab.f_grid < 710  # to the top of a 500 Hz crossover
    front, _ = tab.at(np.array([0.0]), np.array([np.inf]))
    assert np.allclose((a[0] + b[0])[sel], front[0, sel], rtol=1e-2)  # (kd)^2: ~1% at 1 kHz


def _wave_or_skip():
    gpu = _gpu_or_skip()
    return "gpu" if gpu.gpu_info() is not None else "cpu"


def test_wave_solver_rings_at_a_rigid_boxs_modes():
    """The rigid box's lowest modes within 0.1% of the closed form (on the voxelized box)."""
    from scipy.signal import find_peaks

    from varimu.rooms import wave
    from varimu.rooms.polyroom import PolyRoom

    b = _wave_or_skip()
    dx, m, lam = wave.grid_step(250.0, FS)
    lx, ly, lz = 44 * dx, 32 * dx, 25 * dx
    vox = wave.voxelize(PolyRoom([[0, 0], [lx, 0], [lx, ly], [0, ly]], "flat", lz), dx)
    base = np.floor(vox.grid_coords([0.37, 0.41, 0.33])).astype(int)
    nx, ny, _ = vox.dims
    cell = base[0] + nx * (base[1] + ny * base[2])
    mic = vox.grid_coords([lx - 0.39, ly - 0.37, lz - 0.41])
    n_steps = int(3.0 * FS / m)
    rec = wave.run_band(vox, lam, np.zeros(len(vox.wall_cells)), ([cell], [1.0]), [mic], n_steps, b)
    p = np.diff(rec[:, 0, 0])  # the zero-frequency mode out (the module docstring)
    n = 1 << 20
    spec = np.abs(np.fft.rfft(p * np.hanning(len(p)), n))
    f = np.fft.rfftfreq(n, m / FS)
    pk, _ = find_peaks(spec, distance=int(1.0 / f[1]))
    pk = pk[f[pk] < 130]
    found = np.sort(f[pk[np.argsort(spec[pk])[::-1][:20]]])
    c = 343.2
    modes = sorted(
        c / 2 * np.sqrt((i / lx) ** 2 + (j / ly) ** 2 + (k / lz) ** 2)
        for i in range(4) for j in range(4) for k in range(3) if i + j + k > 0
    )[:6]  # fmt: skip
    for mo in modes:
        assert np.min(np.abs(found / mo - 1)) < 1e-3, (mo, found)


def test_wave_solver_agrees_with_image_sources_in_a_rigid_shoebox():
    """Below the crossover (100-340 Hz, the first 60 ms) the wave solver's response is the
    exact image sources' within -30 dB, its walls on whole cells (else they sit up to half a
    cell off: -20 dB)."""
    from varimu.rooms import wave

    b = _wave_or_skip()
    dx = 343.2 / (wave.PPW * 500)
    sb = Shoebox((117 * dx, 90 * dx, 73 * dx), ("rigid",) * 6)
    mics = [Mic(np.array([2.9, 2.1, 1.4]), aim_vector(200), _omni())]
    src = [np.array([1.1, 1.3, 1.2])]
    n_fft = 1 << 16
    geo = responses(sb, src, mics, FS, length_s=0.12, tail=False, ism_s=0.11, backend=b)
    low, xw = wave.responses(
        sb, src, mics, FS, n_fft, crossover_hz=500, rt_s=np.full(7, 10.0), length_s=0.12,
        backend=b,
    )  # fmt: skip
    f = np.fft.rfftfreq(n_fft, 1 / FS)[: len(xw)]
    with np.errstate(invalid="ignore", divide="ignore"):
        bp = np.where((f > 100) & (f < 340), np.sin(np.pi * np.log(f / 100) / np.log(3.4)) ** 2, 0)
    pad = np.zeros(n_fft // 2 + 1 - len(f))
    g = np.fft.irfft(np.r_[np.fft.rfft(geo[0, 0, 0], n_fft)[: len(f)] * bp, pad], n_fft)
    w = np.fft.irfft(np.r_[low[0, 0, 0] * bp, pad], n_fft)
    nd = int(0.06 * FS)
    err = np.sqrt(np.sum((g[:nd] - w[:nd]) ** 2) / np.sum(g[:nd] ** 2))
    assert 20 * np.log10(err) < -30


def test_wave_solver_decays_as_the_rays_say():
    """The admittance from the materials' random-incidence absorption: the wave solver's
    250 and 500 Hz octaves decay at the ray-traced RT within 10%."""
    from scipy.signal import butter, sosfiltfilt

    from varimu.rooms import wave
    from varimu.rooms.polyroom import ray_decay, rt60_from_decay

    b = _wave_or_skip()
    room = _rect_room()
    src = np.array([2.0, 2.55, 1.3])
    rt_ray = rt60_from_decay(*ray_decay(room, src, 3.0, n_rays=20000, backend=b))
    dx, m, lam = wave.grid_step(250.0, FS)
    vox = wave.voxelize(room, dx)
    rng = np.random.default_rng(3)
    mics = [vox.grid_coords([rng.uniform(1, 6), rng.uniform(1, 4.5), rng.uniform(1, 2.2)])
            for _ in range(6)]  # fmt: skip
    base = np.floor(vox.grid_coords(src)).astype(int)
    nx, ny, _ = vox.dims
    cell = base[0] + nx * (base[1] + ny * base[2])
    fs_sim = FS / m
    for bi in (1, 2):
        rec = wave.run_band(vox, lam, vox.beta_links[:, bi], ([cell], [1.0]), mics,
                            int(1.6 * fs_sim), b)  # fmt: skip
        fc = (125.0, 250.0, 500.0)[bi]
        sos = butter(4, [fc / np.sqrt(2), fc * np.sqrt(2)], "band", fs=fs_sim, output="sos")
        y = sosfiltfilt(sos, np.diff(rec[:, :, 0], axis=0), axis=0)
        edc = np.cumsum((y**2)[::-1], axis=0)[::-1].mean(1)
        db = 10 * np.log10(edc / edc[0])
        t = np.arange(len(db)) / fs_sim
        sel = (db <= -5) & (db >= -25)
        rt = -60 / np.polyfit(t[sel], db[sel], 1)[0]
        assert abs(rt / rt_ray[bi] - 1) < 0.1, (fc, rt, rt_ray[bi])


# --- objects and edge diffraction (docs/ROOM_LOOP_PLAN.md R11) ---

GOBO = {"name": "gobo", "center_m": [3.5, 2.75, 0.9], "size_m": [1.2, 0.08, 1.8], "yaw_deg": 90,
        "material": "heavy_drapes"}  # fmt: skip


def test_objects_occlude_reflect_and_leave_old_rooms_alone():
    from varimu.rooms.polyroom import PolyRoom, image_sources, valid_paths

    room = PolyRoom(RECT, "flat", 3.2, objects=[GOBO])
    assert len(room.faces) == 12 and room.n_room_faces == 6
    assert not room.inside(np.array([3.5, 2.75, 0.9])) and room.inside(np.array([3.5, 3.6, 0.9]))
    assert room.volume_m3() == pytest.approx(7 * 5.5 * 3.2 - 1.2 * 0.08 * 1.8, rel=1e-3)
    src = np.array([2.0, 2.75, 1.2])
    pos, seq = image_sources(room, src, 4)
    assert valid_paths(room, pos[:1], seq[:1], np.array([5.0, 2.75, 1.2]))[0] == False  # noqa: E712
    assert valid_paths(room, pos[:1], seq[:1], np.array([5.0, 4.6, 1.2]))[0]
    # a reflection off the gobo's near face reaches a mic beside the source
    ok = valid_paths(room, pos, seq, np.array([2.0, 3.6, 1.2]))
    assert np.any(ok & (seq[:, 0] >= 6) & (seq[:, 1] == -1))
    # no objects: the faces are the room's as before
    bare = _rect_room()
    assert [(f.kind, f.index) for f in bare.faces] == [(f.kind, f.index) for f in room.faces[:6]]


def test_btm_is_continuous_across_the_shadow_boundary():
    """The diffracted wave jumps by the direct sound's 1 / d where the direct sound vanishes
    (a long thin plate: the half-plane), so the total field is continuous."""
    from varimu.rooms.diffraction import Edge, btm

    ed = Edge(np.array([0, 0, -10.0]), np.array([0, 0, 1.0]), 20.0, np.array([1.0, 0, 0]),
              np.array([0, 1.0, 0]), 2 * np.pi, ())  # fmt: skip
    s = np.array([-1.0, 0.5, 0.0])
    tb = np.arctan2(0.5, -1.0) % (2 * np.pi) + np.pi  # the shadow boundary behind the edge
    sums = []
    for th in (tb - np.radians(0.1), tb + np.radians(0.1)):
        r = np.array([1.3 * np.cos(th), 1.3 * np.sin(th), 0.2])
        _, h = btm(ed, s, r, FS)
        sums.append(h[:8].sum())
    d = np.linalg.norm(np.array([1.3 * np.cos(tb), 1.3 * np.sin(tb), 0.2]) - s)
    assert sums[0] < 0 < sums[1]  # lit: it subtracts; shadow: it is the sound
    assert sums[1] - sums[0] == pytest.approx(1 / d, rel=0.01)


def test_a_long_screen_attenuates_as_maekawa_says():
    """Behind a long thin screen in free field (its top and bottom edges equally far: 6 dB
    above one edge), the insertion loss follows Maekawa's 10 log10(3 + 20 N) within 1.5 dB
    from 400 Hz to 8 kHz."""
    from varimu.rooms.polyroom import PolyRoom

    gpu = _gpu_or_skip()
    b = "gpu" if gpu.gpu_info() else "cpu"
    wall = {"center_m": [20, 20, 1.5], "size_m": [30.0, 0.05, 3.0], "yaw_deg": 90,
            "material": "heavy_drapes"}  # fmt: skip
    args = ([[0, 0], [40, 0], [40, 40], [0, 40]], "flat", 30.0, None, 0.0, 8) + ("anechoic",) * 3
    src, mic = np.array([18.0, 20, 1.5]), np.array([22.0, 20, 1.5])
    mics = [Mic(mic, aim_vector(180), _omni())]

    def run(room):
        h = responses(room, [src], mics, FS, length_s=0.06, tail=False, backend=b)[0, 0, 0]
        spec = np.abs(np.fft.rfft(h, 1 << 18)) ** 2
        f = np.fft.rfftfreq(1 << 18, 1 / FS)
        fc = 1000 * 2 ** (np.arange(-7, 10) / 3)
        lv = [
            10 * np.log10(spec[(f >= q / 2 ** (1 / 6)) & (f < q * 2 ** (1 / 6))].sum()) for q in fc
        ]
        return fc, np.array(lv)

    fc, free = run(PolyRoom(*args))
    _, screened = run(PolyRoom(*args, objects=[wall]))
    n_fresnel = 2 * (2 * np.hypot(2, 1.5) - 4) * fc / 343.2
    maekawa = 10 * np.log10(3 + 20 * n_fresnel) - 20 * np.log10(2)
    assert np.all(np.abs((free - screened) - maekawa) < 1.5)


def test_an_l_rooms_hidden_source_arrives_round_the_corner():
    from varimu.rooms.polyroom import PolyRoom

    b = _wave_or_skip()
    room = PolyRoom([[0, 0], [8, 0], [8, 3], [3, 3], [3, 8], [0, 8]], "flat", 3.0)
    src, mic = np.array([6.5, 1.5, 1.5]), np.array([1.5, 6.5, 1.5])
    h = responses(room, [src], [Mic(mic, aim_vector(0), _omni())], FS, length_s=0.2,
                  tail=False, backend=b)[0, 0, 0]  # fmt: skip
    corner = np.array([3.0, 3.0, 1.5])
    t_corner = (np.linalg.norm(src - corner) + np.linalg.norm(mic - corner)) / 343.2
    first = np.argmax(np.abs(h) > 0.05 * np.abs(h).max()) / FS
    assert first == pytest.approx(t_corner, abs=2 / FS)


def test_diffraction_on_the_gpu_is_numpys():
    from varimu.rooms.polyroom import PolyRoom

    gpu = _gpu_or_skip()
    if gpu.gpu_info() is None:
        pytest.skip("no GPU")
    gobo = {**GOBO, "center_m": [5.0, 5.0, 1.5], "size_m": [1.5, 0.06, 2.0]}
    room = PolyRoom([[0, 0], [10, 0], [10, 10], [0, 10]], "flat", 6.0, None, 0.0, 8,
                    "anechoic", "anechoic", "anechoic", objects=[gobo])  # fmt: skip
    mics = [Mic(np.array([6.5, 5.6, 1.4]), aim_vector(180), _omni())]
    src = [np.array([3.8, 5.0, 1.4])]
    a = responses(room, src, mics, FS, length_s=0.05, tail=False, backend="numpy")
    g = responses(room, src, mics, FS, length_s=0.05, tail=False, backend="gpu")
    err = np.sqrt(np.sum((a - g) ** 2) / np.sum(a**2))
    assert 20 * np.log10(err) < -100
