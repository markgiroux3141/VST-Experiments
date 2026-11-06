"""The D6 played live (docs/CLAVINET_PLAN.md, CL3): clavinet_d6_live.yaml is what
scripts/derive_clavinet_live.py generates, it builds with the strings as a medium in place
of the control inputs, and a note through it is the offline path's (the strings rendered
alone, then driving clavinet_d6.yaml's control inputs), bit for bit."""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys

import numpy as np
import pytest

from varimu.circuit import builder, spec
from varimu.circuit.ir import ClavStrings, VoltageProbe
from varimu.config import REPO_ROOT
from varimu.preflight import check_circuit
from varimu.sim import io

circuitsim = pytest.importorskip("circuitsim")


def test_the_live_circuit_is_generated():
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "derive_clavinet_live.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def _ir(name: str):
    s = spec.load_circuit(spec.circuit_path(name))
    ir = builder.build_ir(s, spec.resolve(s, {}))
    return dataclasses.replace(ir, probes=(VoltageProbe("out"),))


def test_it_builds_with_the_strings_in_place_of_the_control_inputs():
    ir = _ir("clavinet_d6_live")
    (el,) = [e for e in ir.elements() if isinstance(e, ClavStrings)]
    assert (el.centre, el.bridge, el.bridge_neg) == ("ec", "eb", "ebn")
    assert not ir.controls
    s = spec.load_circuit(spec.circuit_path("clavinet_d6_live"))
    assert not check_circuit(s), "the pre-flight checks pass"


def test_a_note_through_the_medium_is_the_offline_paths():
    from varimu.sim import fast

    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft"),
        full_scale_volts_peak=1.0,
    )
    assert st.sim_rate == st.sample_rate, "draft steps at the sample rate"
    fs = st.sample_rate
    n = int(0.25 * fs)
    on, off = int(0.01 * fs), int(0.15 * fs)
    live = _ir("clavinet_d6_live")
    notes = [(on / fs, "on", 60, 100), (off / fs, "off", 60, 0)]
    y_live = np.asarray(
        fast.run_transient(live, np.zeros(n), settings=st, notes=notes).vectors["v(out)"]
    )
    (el,) = [e for e in live.elements() if isinstance(e, ClavStrings)]
    d = {f.name: getattr(el, f.name) for f in dataclasses.fields(el)}
    yc, yb, _, _, _ = circuitsim.clav_render(
        json.dumps(d), fs, n, [(on, "on", 60, 100), (off, "off", 60, 0)], 0
    )
    off_ir = _ir("clavinet_d6")
    y_off = np.asarray(
        fast.run_transient(
            off_ir,
            np.zeros(n),
            settings=st,
            controls={"centre": yc, "bridge": yb, "bridge_neg": -yb},
        ).vectors["v(out)"]
    )
    assert np.max(np.abs(y_off)) > 1e-3, "it sounds"
    # the medium's output lands as a control input's sample would: the same, bit for bit
    np.testing.assert_array_equal(y_live, y_off)
