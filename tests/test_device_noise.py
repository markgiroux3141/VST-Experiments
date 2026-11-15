"""Transistor and op-amp noise in the builder (CHAINS_PLAN.md NH2): what a noisy build adds, and
that a build without noise adds nothing. The spectra and the engines' agreement are
tests/test_noise_spectra.py's (cases flicker, bjt, jfet)."""

from __future__ import annotations

from pathlib import Path

import pytest

from varimu.circuit import builder, parts, spice
from varimu.circuit import ir as I
from varimu.circuit.spec import load_circuit
from varimu.devices import noise as nz

CIRCUITS = Path(__file__).resolve().parents[1] / "config" / "circuits"


def _build(name: str, noise, path: Path | None = None) -> I.CircuitIR:
    return builder.build(load_circuit(path or CIRCUITS / f"{name}.yaml"), noise=noise).ir


def _of(ir: I.CircuitIR, kind) -> list:
    return [e for e in ir.elements() if isinstance(e, kind)]


@pytest.mark.parametrize("name", ["api_312", "cloudlifter", "clean_pre", "ssl_4000e"])
def test_a_build_without_noise_has_none_of_it(name):
    ir = _build(name, False)
    assert not _of(ir, I.TransistorNoise | I.FlickerCurrent | I.NoiseCurrent)


def test_a_bjt_part_gets_its_junction_noise_and_its_resistors_johnson_noise():
    ir = _build("api_312", 3)
    bjts = [e for e in _of(ir, I.Device) if e.name.startswith("Q")]
    tn = {t.device: t for t in _of(ir, I.TransistorNoise)}
    assert set(tn) == {q.name for q in bjts}
    t = tn[bjts[0].name]
    assert (t.name, t.family, t.temperature_k) == (f"BN_{bjts[0].name}", "bjt", nz.RESISTOR_T_K)
    # The parasitic resistors (RB, RC, RE where nonzero) are noisy resistors.
    rq = [r for r in _of(ir, I.Resistor) if r.name.startswith(f"R{bjts[0].name.upper()}_")]
    names = {n.name for n in _of(ir, I.NoiseCurrent)}
    assert rq and all(f"IN_{r.name}" in names for r in rq)


def test_a_jfet_part_gets_its_channel_noise():
    ir = _build("cloudlifter", 3)
    families = {t.family for t in _of(ir, I.TransistorNoise)}
    assert families == {"jfet"}


def test_flicker_comes_from_the_device_noise_table(tmp_path, monkeypatch):
    table = tmp_path / "device_noise.yaml"
    table.write_text(
        "flicker:\n  BC550C: {kf: 2.0e-15, af: 1.1, source: 'test'}\n", encoding="utf-8"
    )
    monkeypatch.setattr(builder, "DEVICE_NOISE_FILE", table)
    ir = _build("api_312", 3)
    by_component = {t.kf for t in _of(ir, I.TransistorNoise)}
    assert 2.0e-15 in by_component  # the BC550C instances
    assert 0.0 in by_component  # other parts, not listed: no flicker
    assert {t.af for t in _of(ir, I.TransistorNoise) if t.kf > 0} == {1.1}


def test_an_opamps_noise_is_its_datasheets_en_and_in(tmp_path):
    # The clean pre's U1 has in and its corner; en added here (its file models en as RN).
    text = (CIRCUITS / "clean_pre.yaml").read_text(encoding="utf-8")
    assert text.count("in_a_rthz: u_in_a_rthz") == 1
    text = text.replace(
        "in_a_rthz: u_in_a_rthz",
        "en_v_rthz: {value: 3.5e-9, source: 'test'}, en_corner_hz: {value: 50.0, source: 'test'}, "
        "in_a_rthz: u_in_a_rthz",
    )
    path = CIRCUITS / "_nh2_test_clean_pre.yaml"  # beside the original: relative paths resolve
    path.write_text(text, encoding="utf-8")
    try:
        ir = _build("x", 3, path)
    finally:
        path.unlink()
    nc = {n.name: n for n in _of(ir, I.NoiseCurrent)}
    fc = {f.name: f for f in _of(ir, I.FlickerCurrent)}
    gm_en = parts.OPAMP_GM_S * 3.5e-9
    en = nc["IN_U1_en"]
    assert (en.a, en.b, en.psd_a2_hz) == ("0", "u1_1", gm_en * gm_en)
    assert fc["IF_U1_en"].kf_a2 == gm_en * gm_en * 50.0
    ip, im = nc["IN_U1_ip"], nc["IN_U1_im"]
    assert (ip.a, im.a) == ("ip", "fb") and ip.psd_a2_hz == 0.4e-12 * 0.4e-12
    assert fc["IF_U1_ip"].kf_a2 == ip.psd_a2_hz * 392.0


def test_an_opamp_without_noise_values_is_noiseless():
    ir = _build("omni_4134", 3)
    assert not [n for n in _of(ir, I.NoiseCurrent) if n.name.startswith("IN_U1_")]


def test_transistor_noise_emits_to_spice():
    ir = _build("cloudlifter", 3)
    text, _ = spice.emit(ir)
    t = _of(ir, I.TransistorNoise)[0]
    b = t.name.lower()
    assert f"B{b}_p " in text and f"B{b}_g " in text
    # A JFET's gm by difference: its second copy with the gate up.
    assert f"V{b}_d " in text and f"J{b}_c1 " in text
    streams = {s.node for s in spice.noise_streams(ir)}
    assert {f"nz_{b}_s", f"nz_{b}_g", f"nz_{b}_f"} <= streams


def test_the_ir_refuses_transistor_noise_on_the_wrong_device():
    ir = _build("cloudlifter", 3)
    t = _of(ir, I.TransistorNoise)[0]
    import dataclasses

    bad = dataclasses.replace(t, family="bjt")
    sections = tuple(
        dataclasses.replace(s, elements=tuple(bad if e is t else e for e in s.elements))
        for s in ir.sections
    )
    with pytest.raises(I.IRError, match="not a BJT instance"):
        dataclasses.replace(ir, sections=sections).validate()
