"""The Variable-D rear path (docs/CHAINS_PLAN.md WP13): the `slotted_line` network kind, the
exact reduction of its N slot entries to one rear entry (`moving_coil.rear_entry_weights`), and
the `variable_d` body's slot bands in the BEM (`bor.variable_d_mesh`, `bor.rear_weights`)."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from varimu.circuit import parts
from varimu.circuit.ir import CircuitIR, Control, Resistor, Section, VoltageProbe
from varimu.devices import moving_coil as mc
from varimu.measure import ac
from varimu.mics import bor
from varimu.mics.networks import moving_coil_ir

N = 6
G = {
    "diaphragm": {"radius_m": 0.0125, "moving_mass_kg": 1.0e-3, "resonance_hz": 60.0, "q": 2.0},
    "coil": {"bl_tm": 5.0, "re_ohm": 150.0, "le_h": 1.0e-3},
    "network": [
        {"name": "grille", "kind": "screen", "a": "front", "b": "g", "rayl": 20.0,
         "area_m2": 1.0e-3},
        {"name": "dia", "kind": "diaphragm", "a": "g", "b": "u"},
        {"name": "cav", "kind": "cavity", "a": "u", "volume_m3": 2.0e-6},
        {"name": "vd", "kind": "slotted_line", "a": "u", "b": "rear", "tubes": 2,
         "radius_m": 3.0e-3, "lead_m": 5.0e-3, "slot_rayl": 300.0, "slot_width_m": 2.0e-3},
        {"name": "term", "kind": "cavity", "a": f"vd_{N}", "volume_m3": 5.0e-6},
    ],
    "body": {"form": "variable_d", "radius_m": 0.0246, "length_m": 0.2, "slot_m": [0.01, 0.09],
             "slot_sections": N},
}  # fmt: skip
F = np.geomspace(30.0, 12000.0, 25)


def _full_ir(g):
    """The cartridge with every slot entry its own driven node (the reference the reduction
    must equal): entry k > 1 on control `c<k>` (node mc_s<k>: ac drives by node)."""
    lumped = mc.compile_network(g)
    for e in lumped["elements"]:
        for k in range(2, N + 1):
            if e["name"] == f"vd_{k}_s":
                assert e["b"] == "0"
                e["b"] = f"s{k}"
    c = mc.moving_coil_from_data({"name": "T", "kind": "moving_coil", "lumped": lumped})
    els = parts.moving_coil("MC", "in", "p_rear", "out", "0", c)
    els.append(Resistor("RLOAD", "out", "0", 1e9))
    ctl = [Control("p_rear", "p_rear")] + [Control(f"c{k}", f"mc_s{k}") for k in range(2, N + 1)]
    return CircuitIR(
        title="full", input_node="in", probes=(VoltageProbe("out"),), models=(),
        sections=(Section("cartridge", tuple(els)),), controls=tuple(ctl),
    )  # fmt: skip


def test_the_reduction_is_exact():
    """Entries driven by a wave along the body (each its own delay and level): the reduced
    cartridge (entry 1 at sum_k w_k p_k, the others at the ambient) equals the full N-entry
    solve to rounding."""
    z = np.array([0.01 + (k + 0.5) * 0.08 / N for k in range(N)])
    p = np.array([(0.9**k) * np.exp(-2j * np.pi * F * zk / 343.0) for k, zk in enumerate(z)])
    drives = {"p_rear": p[0], **{f"mc_s{k + 1}": p[k] for k in range(1, N)}}
    full = ac.transfer(_full_ir(G), F, "out", drives=drives)
    w = mc.rear_entry_weights(G, F)
    assert w.shape == (N, len(F)) and np.allclose(w[0], 1.0)
    c = mc.moving_coil_from_data(
        {"name": "T", "kind": "moving_coil", "lumped": mc.compile_network(G)}
    )
    reduced = ac.transfer(moving_coil_ir(c), F, "out", drives={"p_rear": (w * p).sum(axis=0)})
    assert np.max(abs(reduced - full) / abs(full)) < 1e-9


def test_far_slots_matter_only_at_low_frequencies():
    """The continuously variable distance: a far slot's weight falls with frequency (the
    tube's masses and compliances filter it), the near slot passes the top."""
    w = abs(mc.rear_entry_weights(G, np.array([50.0, 5000.0])))
    assert w[-1, 0] > 0.3
    assert w[-1, 1] < 0.3 * w[-1, 0]


def test_slotted_line_needs_its_body():
    g = copy.deepcopy(G)
    g["body"] = {"form": "dynamic"}
    with pytest.raises(ValueError, match="variable_d"):
        mc.compile_network(g)


def test_a_cartridge_without_slots_has_unit_weights():
    g = copy.deepcopy(G)
    g["network"] = g["network"][:3]
    assert np.all(mc.rear_entry_weights(g, F) == 1.0)


def test_variable_d_mesh_bands_and_weights():
    """The slot band cut into N entries; the rear entry needs the cartridge's weights; with
    the weights the rear entry is their sum of band averages."""
    m = bor.variable_d_mesh(G["body"], G["diaphragm"]["radius_m"], panel_m=1.0e-3)
    assert {bor.SLOT0 + k for k in range(1, N + 1)} <= set(m.tag.tolist())
    op = bor.operator(m)
    f = np.array([200.0, 2000.0])
    th = np.radians([0.0, 180.0])
    with pytest.raises(ValueError, match="weights"):
        bor.entry_factors(op, f, th)
    w = mc.rear_entry_weights(G, f)
    front, rear = bor.entry_factors(op, f, th, rear=bor.rear_weights(m, w, f))
    bands = []
    for k in range(1, N + 1):
        one = np.zeros_like(w)
        one[k - 1] = 1.0
        bands.append(bor.entry_factors(op, f, th, rear=bor.rear_weights(m, one, f))[1])
    assert np.allclose(rear, sum(w[k][:, None] * bands[k] for k in range(N)))
    # a wave from the front reaches the far slot later than the near one
    near, far = bands[0][1, 0], bands[-1][1, 0]
    assert np.angle(far / near) < 0


def test_free_field_entries_use_the_weights():
    """varimu.mics.free_field (the fits', mic_print's and the tests' path): a variable_d body's
    rear entry is the weighted band sum, and it refuses without the cartridge's geometry."""
    from varimu.mics.free_field import body_entry_factors

    f, th = np.array([300.0]), np.radians([0.0, 90.0])
    a = G["diaphragm"]["radius_m"]
    with pytest.raises(ValueError, match="geometry"):
        body_entry_factors(f, th, G["body"], a)
    front, rear = body_entry_factors(f, th, G["body"], a, geometry=G)
    op = bor.operator(bor.body_mesh(G["body"], a))
    w = mc.rear_entry_weights(G, f)
    want = bor.entry_factors(op, f, th, rear=bor.rear_weights(op.mesh, w, f))
    assert np.allclose(front, want[0]) and np.allclose(rear, want[1])


def test_the_reduction_is_exact_with_ports():
    """With the body's `ports_m` (the head's rear ports, entry 1, driven by a near path) every
    slot section is an entry of its own: the reduction still equals the full solve."""
    g = copy.deepcopy(G)
    g["network"][2:3] = [
        {"name": "near", "kind": "acoustic", "a": "u", "b": "rear", "r_pa_s_m3": 3.0e6,
         "m_kg_m4": 500.0},
        {"name": "damp", "kind": "acoustic", "a": "u", "b": "t", "r_pa_s_m3": 1.0e6},
    ]  # fmt: skip
    g["network"][4]["a"], g["network"][4]["b"] = "t", "0"
    g["body"] = {**g["body"], "ports_m": [0.003, 0.008]}
    lumped = mc.compile_network(g)
    for e in lumped["elements"]:
        for k in range(1, N + 1):
            if e["name"] == f"vd_{k}_s":
                assert e["b"] == "0"
                e["b"] = f"s{k}"
    c = mc.moving_coil_from_data({"name": "T", "kind": "moving_coil", "lumped": lumped})
    els = parts.moving_coil("MC", "in", "p_rear", "out", "0", c)
    els.append(Resistor("RLOAD", "out", "0", 1e9))
    ctl = [Control("p_rear", "p_rear")] + [Control(f"c{k}", f"mc_s{k}") for k in range(1, N + 1)]
    full_ir = CircuitIR(
        title="full", input_node="in", probes=(VoltageProbe("out"),), models=(),
        sections=(Section("cartridge", tuple(els)),), controls=tuple(ctl),
    )  # fmt: skip
    z = np.array([0.005] + [0.01 + (k + 0.5) * 0.08 / N for k in range(N)])
    p = np.array([(0.9**k) * np.exp(-2j * np.pi * F * zk / 343.0) for k, zk in enumerate(z)])
    full = ac.transfer(
        full_ir, F, "out", drives={"p_rear": p[0], **{f"mc_s{k}": p[k] for k in range(1, N + 1)}}
    )
    w = mc.rear_entry_weights(g, F)
    assert w.shape == (N + 1, len(F)) and np.allclose(w[0], 1.0)
    cr = mc.moving_coil_from_data(
        {"name": "T", "kind": "moving_coil", "lumped": mc.compile_network(g)}
    )
    reduced = ac.transfer(moving_coil_ir(cr), F, "out", drives={"p_rear": (w * p).sum(axis=0)})
    assert np.max(abs(reduced - full) / abs(full)) < 1e-9
    m = bor.variable_d_mesh(g["body"], 0.0125)
    assert m.uniform == (bor.SLOT0,) + tuple(bor.SLOT0 + k for k in range(1, N + 1))


def test_a_node_named_like_the_coils_is_refused():
    """parts.moving_coil prefixes acoustic and electrical nodes alike: an acoustic `v` would be
    the coil's node."""
    g = copy.deepcopy(G)
    g["network"][2] = {"name": "cav", "kind": "cavity", "a": "v", "volume_m3": 2.0e-6}
    with pytest.raises(ValueError, match="coil's own"):
        mc.compile_network(g)
