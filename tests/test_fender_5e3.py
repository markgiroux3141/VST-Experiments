"""The Fender 5E3 Deluxe (device builder B9 step 3): config/circuits/fender_5e3.yaml.

It builds from the generic format, passes the pre-flight checks at every input jack,
wires the jacks as Fender's drawing does, and idles within the drawing's stated
+-20% of the voltages published for built amps (data/schematics/fender_5e3/README.md).
"""

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR

DELUXE = CONFIG_DIR / "circuits" / "fender_5e3.yaml"

# Published idle voltages (README, "Published voltages"): Amplified Parts' kit with its
# reproduction transformers (P-TGP-002's voltages sheet), the ones the circuit's power
# transformer figures come from. The drawing's notice box: "values shown + or - 20 %".
AP_V = {"b1": 370.0, "b2": 325.5, "b3": 240.8, "k6": 21.1, "p3": 195.1, "k3": 45.9,
        "p2": 157.7, "k2": 1.22, "p1b": 136.2, "p1n": 128.5, "k1": 1.76}  # fmt: skip


@pytest.fixture(scope="module")
def deluxe():
    return spec.load_circuit(DELUXE)


def test_builds_and_every_value_is_sourced(deluxe):
    for cores in ("ja", "linear"):
        c = builder.build(deluxe, cores=cores)
        assert (c.text is None) == (cores == "ja")
    assert spec.check_genome_links(deluxe) == []
    a = builder.build_ir(deluxe, spec.resolve(deluxe, {"passive_spread": 1.0, "passive_seed": 3}))
    b = builder.build_ir(deluxe, spec.resolve(deluxe))
    moved = sum(e != e0 for e, e0 in zip(a.elements(), b.elements(), strict=True))
    assert moved > 25


def test_guitar_level_in_sound_pressure_out(deluxe):
    # 0 dBFS is a hot pickup's ~1 V peak; the output is the sound pressure 1 m in front of
    # the speaker (component editor C3), with room for its peaks on a guitar take (40 Pa).
    assert deluxe.full_scale == (1.0, 50.0)
    assert deluxe.full_scale_unit == "Pa"
    assert builder.build(deluxe).full_scale == (1.0, 50.0)
    # A drawing made from it keeps the convention (the KiCad export's sidecar, which
    # the editor's layouts start from).
    from varimu.kicad.export import _Exporter

    assert _Exporter(deluxe).sidecar()["full_scale"] == deluxe.full_scale_block


def test_preflight_passes_at_every_jack(deluxe):
    assert preflight.check_circuit(deluxe) == []
    assert len(preflight.switch_configs(deluxe)) == 4


def _input_divider(deluxe, jack):
    """DC gain from `in` to the plugged channel's grid through the jack network (the
    resistors alone: tubes and capacitors left out)."""
    from varimu.circuit.ir import Resistor

    els = [
        e
        for e in builder.build_ir(deluxe, spec.resolve(deluxe, {"input_jack": jack})).elements()
        if isinstance(e, Resistor) and e.name.startswith(("RIN1", "RGA", "RGB", "RJ"))
    ]
    nodes = sorted({n for e in els for n in (e.a, e.b)} - {"0", "in"})
    ix = {n: i for i, n in enumerate(nodes)}
    g, rhs = np.zeros((len(nodes), len(nodes))), np.zeros(len(nodes))
    for e in els:
        for p, q in ((e.a, e.b), (e.b, e.a)):
            if p in ix:
                g[ix[p], ix[p]] += 1 / e.r_ohm
                if q in ix:
                    g[ix[p], ix[q]] -= 1 / e.r_ohm
                elif q == "in":
                    rhs[ix[p]] += 1 / e.r_ohm
    v = np.linalg.solve(g, rhs)
    return {n: v[ix[n]] for n in ("g1b", "g1n")}


def test_jacks_as_drawn(deluxe):
    """Input 1: both 68K in parallel to the grid (full level); input 2: the 68K / 68K
    divider with input 1's tip grounded (-6 dB); the other channel's grid sees ground."""
    assert _input_divider(deluxe, 1)["g1b"] == pytest.approx(1.0, abs=1e-6)
    assert _input_divider(deluxe, 2)["g1b"] == pytest.approx(0.5, abs=1e-6)
    assert _input_divider(deluxe, 3)["g1n"] == pytest.approx(1.0, abs=1e-6)
    assert _input_divider(deluxe, 4)["g1n"] == pytest.approx(0.5, abs=1e-6)
    assert _input_divider(deluxe, 1)["g1n"] == pytest.approx(0.0, abs=1e-6)


def test_idles_within_the_drawings_tolerance(deluxe):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    st = TransientSettings.from_sim_settings(engine="circuitsim")
    x = np.zeros(int(0.5 * st.sample_rate))
    v = fast.run_transient(builder.build(deluxe).ir, x, settings=st).vectors
    n = int(0.1 * st.sample_rate)
    for node, d in AP_V.items():
        assert np.mean(v[f"v({node})"][-n:]) == pytest.approx(d, rel=0.20), node
    # The supply, from the reproduction transformer's own figures, within 3%.
    for node in ("b1", "b2", "b3"):
        assert np.mean(v[f"v({node})"][-n:]) == pytest.approx(AP_V[node], rel=0.03), node
