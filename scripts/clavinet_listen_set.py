"""The D6 to listen to (docs/CLAVINET_PLAN.md, CL1-CL2) -> reports/clavinet/listen/
(WAVs at the circuit's full scale, 2 V = 0 dBFS, and LISTEN.md, what each one is).

The strings are rendered once per phrase (the pickups' EMFs); the electronics' settings
(pickup selector, tone rockers) then run the circuit on the same EMFs, so the comparisons
differ in the electronics only. The mute bar changes the strings, so it is its own render.

    uv run --extra fast python scripts/clavinet_listen_set.py [--quality production|draft]
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.clavinet import keyboard
from varimu.config import CONFIG_DIR
from varimu.rhodes import midi
from varimu.sim import fast, io

ROOT = Path(__file__).parents[1]
OUT = ROOT / "reports" / "clavinet" / "listen"
CIRCUIT = CONFIG_DIR / "circuits" / "clavinet_d6.yaml"
FS = 96000

_r = importlib.util.spec_from_file_location(
    "clavinet_render", Path(__file__).parent / "clavinet_render.py"
)
render_mod = importlib.util.module_from_spec(_r)
sys.modules["clavinet_render"] = render_mod
_r.loader.exec_module(render_mod)

TONES = {
    "soft": "soft",
    "medium": "medium",
    "treble": "treble",
    "brilliant": "brilliant",
    "medium+treble": "medium,treble",
    "all": "soft,medium,treble,brilliant",
}
PICKUPS = {"AC_centre": 0, "BC_bridge": 1, "AD_anti": 2, "BD_both": 3}


STRINGS_DIR = ROOT / "cache" / "clavinet" / "listen"


def strings_key(events: list[midi.Event], mute: float) -> str:
    """The strings' render depends on the events, the mute, the fits and the reference's
    code: hashed, so the electronics can be rerun alone."""
    import hashlib

    from varimu.clavinet import fit

    here = ROOT / "varimu" / "clavinet"
    blob = repr([(e.t_s, e.kind, e.note, e.value) for e in events]).encode() + repr(mute).encode()
    blob += fit._cache_key("d6").encode()
    for mod in ("note.py", "knock.py", "pickup.py", "keyboard.py"):
        blob += (here / mod).read_bytes()
    return hashlib.sha256(blob).hexdigest()[:16]


def strings(events: list[midi.Event], mute: float = 0.0) -> tuple[dict, dict]:
    STRINGS_DIR.mkdir(parents=True, exist_ok=True)
    path = STRINGS_DIR / f"{strings_key(events, mute)}.npz"
    if path.exists():
        d = np.load(path)
        return {"centre": d["centre"], "bridge": d["bridge"]}, json.loads(str(d["stats"]))
    emf, st = keyboard.render(events, FS, mute=mute)
    np.savez(path, centre=emf["centre"], bridge=emf["bridge"], stats=json.dumps(st))
    return emf, st


def circuit(emf: dict, sets: dict, quality: str) -> np.ndarray:
    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(s, spec.resolve(s, sets))
    ir = dataclasses.replace(ir, probes=(VoltageProbe("out"),))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality=quality),
        full_scale_volts_peak=1.0,
    )
    c, b = emf["centre"], emf["bridge"]
    v = fast.run_transient(
        ir, np.zeros_like(c), settings=st, controls={"centre": c, "bridge": b, "bridge_neg": -b}
    ).vectors
    return np.asarray(v["v(out)"])


def sets_for(tone: str, pickups: int, volume: float = 0.8) -> dict:
    on = set(tone.split(","))
    d = {k: int(k in on) for k in ("soft", "medium", "treble", "brilliant")}
    d.update(pickup_select=pickups, volume=volume)
    return d


def scale_events(events: list[midi.Event], vel: int | None) -> list[midi.Event]:
    return [dataclasses.replace(e, value=vel) if (vel and e.kind == "on") else e for e in events]


def notes_events(keys_midi: list[int], vel: int, hold_s: float, gap_s: float) -> list[midi.Event]:
    ev = []
    t = 0.1
    for m in keys_midi:
        ev += [midi.Event(t, "on", m, vel), midi.Event(t + hold_s, "off", m, 0)]
        t += hold_s + gap_s
    return ev


def write(name: str, x: np.ndarray, what: str, lines: list[str]) -> None:
    sf.write(OUT / f"{name}.wav", (x / 2.0).astype(np.float32), FS, subtype="FLOAT")
    lines.append(f"- `{name}.wav`: {what} (peak {np.max(np.abs(x)):.2f} V)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quality", default="production")
    ap.add_argument(
        "--strings-only", action="store_true", help="render and cache the strings, no electronics"
    )
    args = ap.parse_args()
    if args.strings_only:
        demo = render_mod.demo_events()
        strings(notes_events([29, 40, 52, 64, 76, 88], 80, 1.5, 0.6))
        ev = []
        t = 0.1
        for vel in (25, 70, 120):
            for hold in (0.12, 1.2):
                ev += [midi.Event(t, "on", 52, vel), midi.Event(t + hold, "off", 52, 0)]
                t += hold + 0.5
        strings(ev)
        strings(demo)
        strings(demo, mute=1.0)
        print("strings cached")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    lines = [
        "# The Clavinet D6, to listen to",
        "",
        "Rendered by `scripts/clavinet_listen_set.py`: the strings from physics",
        "(varimu/clavinet), the D6's electronics (config/circuits/clavinet_d6.yaml, the amp",
        "provisional until the schematic is read). 0 dBFS = 2 V at the volume pot's wiper",
        "(volume 0.8). The tone and pickup comparisons share one strings render each.",
        "",
    ]
    default = sets_for("medium,treble", 3)

    # 1. single notes over the keyboard, mf, held 1.5 s, released
    keys = [29, 40, 52, 64, 76, 88]  # F1 E2 E3 E4 E5 E6
    emf, _ = strings(notes_events(keys, 80, 1.5, 0.6))
    write(
        "notes_keyboard",
        circuit(emf, default, args.quality),
        "F1, E2, E3, E4, E5, E6 at mf, each held 1.5 s then released"
        " (the 3-semitone release and the yarn's kill)",
        lines,
    )

    # 2. velocity on E3: pp, mf, ff (staccato and held)
    ev = []
    t = 0.1
    for vel in (25, 70, 120):
        for hold in (0.12, 1.2):
            ev += [midi.Event(t, "on", 52, vel), midi.Event(t + hold, "off", 52, 0)]
            t += hold + 0.5
    emf, _ = strings(ev)
    write(
        "velocity_e3",
        circuit(emf, default, args.quality),
        "E3 at pp, mf, ff, each staccato then held",
        lines,
    )

    # 3. the demo phrase through every pickup setting and tone rocker
    demo = render_mod.demo_events()
    emf, st = strings(demo)
    for name, sel in PICKUPS.items():
        write(
            f"riff_pickups_{name}",
            circuit(emf, sets_for("medium,treble", sel), args.quality),
            f"the demo phrase, pickups {name} (MEDIUM + TREBLE)",
            lines,
        )
    for name, tone in TONES.items():
        write(
            f"riff_tone_{name}",
            circuit(emf, sets_for(tone, 3), args.quality),
            f"the demo phrase, tone {name.upper()} (both pickups in phase)",
            lines,
        )

    # 4. the mute bar
    emf_m, _ = strings(demo, mute=1.0)
    write(
        "riff_muted",
        circuit(emf_m, default, args.quality),
        "the demo phrase with the mute bar fully on",
        lines,
    )

    lines += [
        "",
        "What to listen for: the attack's click (the tangent's strike on the anvil), the",
        "release's drop (three semitones, then gone), the bass's long sustain, the pickups'",
        "comb (A+D thin, B+D full), the rockers' colours, the knock under the attack (CL4: the",
        "board under the anvils, subtle). The amp is drawn from Hohner's E7 schematic (since",
        "2026-11-06), the pickup level set so normal playing peaks at its 1% THD. Not modelled",
        "yet: aftertouch bends in renders.",
    ]
    (OUT / "LISTEN.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT / "notes.json").write_text(
        json.dumps({"quality": args.quality, "demo_notes": st}, indent=1)
    )
    print("\n".join(lines))


if __name__ == "__main__":
    main()
