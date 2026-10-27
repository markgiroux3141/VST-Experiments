"""Draw the triode stage from scratch in the schematic editor, through its UI (mouse and
keys, in the installed Chrome), save it as a new circuit and hear it: device builder
B4a's "a circuit drawn from scratch" done-when, reproducible.

    uv run --extra listen --extra fast varimu listen          # in another terminal
    uv run --no-project --with playwright python scripts/editor_draw_triode.py \\
        [--url http://127.0.0.1:8765] [--name triode_stage_drawn] [--shots DIR]

Playwright runs from uv's cache, not the project (the editor has no dependencies).
Coordinates are the drawing's (mm); they become screen points through the page's camera
(window.__editor). Values and sources are config/circuits/triode_stage.yaml's; the
output node is `out` (renders read it), not `o`. tests/test_editor.py checks that the
saved drawing builds the hand-written stage's IR. Saving over a drawn circuit replaces it.
"""

import argparse
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PROVISIONAL = "provisional: model knowledge"
SRC = {
    "b_plus_v": f"{PROVISIONAL} (a textbook 12AX7 plate supply, 250-300 V)",
    "r_source_ohm": f"{PROVISIONAL} (a source impedance that lets the grid-current peaks show)",
    "c_in_f": f"{PROVISIONAL} (coupling capacitor: 1.6 Hz with the grid leak)",
    "r_grid_ohm": f"{PROVISIONAL} (12AX7 grid leak, 0.5-1 MOhm)",
    "r_plate_ohm": f"{PROVISIONAL} (12AX7 plate load, 100k)",
    "r_cathode_ohm": f"{PROVISIONAL} (12AX7 self-bias with a 100k plate load, 1.5k)",
    "c_cathode_f": f"{PROVISIONAL} (cathode bypass, a few Hz)",
    "c_out_f": f"{PROVISIONAL} (output coupling capacitor)",
    "r_load_ohm": f"{PROVISIONAL} (the next stage's grid leak)",
}
# (symbol, ref, x, y, quarter turns, value, source key)
PARTS = [
    ("Triode", "V1", 40.64, 0, 0, None, None),
    ("V", "VB", 25.4, -22.86, 0, "250", "b_plus_v"),
    ("R", "RS", 10.16, 0, 1, "10k", "r_source_ohm"),
    ("C", "CI", 22.86, 0, 1, "100n", "c_in_f"),
    ("R", "RG", 30.48, 7.62, 0, "1M", "r_grid_ohm"),
    ("R", "RP", 40.64, -15.24, 0, "100k", "r_plate_ohm"),
    ("R", "RK", 40.64, 15.24, 0, "1.5k", "r_cathode_ohm"),
    ("C", "CK", 48.26, 15.24, 0, "22u", "c_cathode_f"),
    ("C", "CO", 50.8, -8.89, 1, "100n", "c_out_f"),
    ("R", "RL", 58.42, -5.08, 0, "470k", "r_load_ohm"),
]
WIRES = [
    [(13.97, 0), (19.05, 0)],  # RS - CI: a
    [(26.67, 0), (33.02, 0)],  # CI - V1.g: g
    [(30.48, 3.81), (30.48, 0)],  # RG ends on the grid wire (a T)
    [(40.64, 7.62), (40.64, 11.43)],  # V1.k - RK: k
    [(48.26, 11.43), (48.26, 10.16), (40.64, 10.16)],  # CK ends on the cathode wire
    [(40.64, -11.43), (40.64, -7.62)],  # RP - V1.p: p
    [(40.64, -8.89), (46.99, -8.89)],  # the plate wire to CO
    [(54.61, -8.89), (58.42, -8.89)],  # CO - RL: out
    [(25.4, -27.94), (25.4, -30.48), (40.64, -30.48), (40.64, -19.05)],  # VB + to RP: bp
]
LABELS = [("in", 6.35, 0), ("a", 16.51, 0), ("g", 31.75, 0), ("k", 40.64, 8.89),
          ("p", 43.18, -8.89), ("out", 58.42, -8.89), ("bp", 33.02, -30.48)]  # fmt: skip
GROUNDS = [(30.48, 11.43), (40.64, 19.05), (48.26, 19.05), (58.42, -1.27), (25.4, -17.78)]

CANVAS = "document.querySelector('#canvas').getBoundingClientRect()"
CHECKS_DONE = "!document.querySelector('#checks').classList.contains('busy')"
SUMMARY = """(() => { const s = window.__editor.state(); return {ok: s.analysis.ok,
  errors: s.analysis.errors, out: s.analysis.has_output,
  markers: s.markers.map(m => m.check + ': ' + m.message)}; })()"""
HEARD = """new Promise(r => {
  const t = setInterval(() => { if (window.__tweakToHear) {
    clearInterval(t); r(JSON.stringify(window.__tweakToHear)); } }, 300);
  setTimeout(() => r('timeout'), 300000); })"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--name", default="triode_stage_drawn")
    ap.add_argument("--shots", type=Path, help="save a screenshot after each stage here")
    args = ap.parse_args()
    t_start = time.perf_counter()
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        pg = b.new_page(viewport={"width": 1600, "height": 900})
        msgs: list[str] = []
        pg.on("pageerror", lambda e: msgs.append(f"pageerror: {e}"))

        def shot(name: str) -> None:
            if args.shots:
                args.shots.mkdir(parents=True, exist_ok=True)
                pg.screenshot(path=str(args.shots / f"{name}.png"))

        def idle() -> None:
            pg.wait_for_timeout(120)
            pg.wait_for_function("window.__editor.idle()", timeout=30000)

        def screen(x: float, y: float) -> tuple[float, float]:
            return pg.evaluate(f"""(() => {{ const c = window.__editor.cam, r = {CANVAS};
                const [sx, sy] = c.toScreen({x}, {y}); return [sx + r.left, sy + r.top]; }})()""")

        def click(x: float, y: float) -> None:
            sx, sy = screen(x, y)
            pg.mouse.move(sx, sy, steps=3)
            pg.mouse.click(sx, sy)

        pg.goto(f"{args.url}/editor#c=pultec_eqp1a")
        pg.wait_for_function("window.__editor && window.__editor.idle()", timeout=60000)
        pg.locator("#circuit").select_option("__new__")
        pg.wait_for_function("window.__editor.state().kind === 'new'", timeout=30000)
        # A fixed camera: 9 px per mm, the stage in the middle.
        pg.evaluate(
            f"(() => {{ const r = {CANVAS};"
            " window.__editor.cam.set(r.width / 2 - 34 * 9, r.height / 2 + 6 * 9, 9); })()"
        )

        for sym, ref, x, y, turns, value, src in PARTS:
            pg.click(f'.tile[data-sym="{sym}"]')
            sx, sy = screen(x, y)
            pg.mouse.move(sx, sy, steps=4)
            for _ in range(turns):
                pg.keyboard.press("r")
            pg.mouse.click(sx, sy)
            idle()
            pg.keyboard.press("Escape")  # back to selecting; the new part stays selected
            if pg.evaluate("window.__editor.state().sel.symbols[0]") != ref:
                pg.fill("#v-ref", ref)
                pg.press("#v-ref", "Enter")
                idle()
            if value:
                pg.fill("#v-src", SRC[src])
                pg.fill("#v-in", value)
                pg.press("#v-in", "Enter")
                idle()
        shot("1_parts")

        pg.keyboard.press("w")
        for w in WIRES:
            for x, y in w:
                click(x, y)
            pg.keyboard.press("Enter")
            idle()
        pg.keyboard.press("Escape")
        shot("2_wires")

        pg.keyboard.press("l")
        for name, x, y in LABELS:
            click(x, y)
            pg.wait_for_selector("#prompt.on")
            pg.fill("#promptin", name)
            pg.press("#promptin", "Enter")
            idle()
        pg.keyboard.press("g")
        for x, y in GROUNDS:
            click(x, y)
            idle()
        pg.keyboard.press("Escape")

        click(5, 25)  # nothing selected: the circuit's own settings
        pg.keyboard.press("Escape")
        pg.fill('[data-circ="title"]', "12AX7 common-cathode stage (drawn in the editor)")
        pg.press('[data-circ="title"]', "Enter")
        idle()
        pg.fill('[data-circ="probes"]', "g, p, k")
        pg.press('[data-circ="probes"]', "Enter")
        idle()
        pg.wait_for_timeout(1500)
        pg.wait_for_function(CHECKS_DONE, timeout=60000)
        shot("3_drawn")
        print("analysis:", pg.evaluate(SUMMARY))

        pg.keyboard.press("Control+s")
        pg.fill("#savename", args.name)
        pg.press("#savename", "Enter")
        pg.wait_for_function(f"window.__editor.state().name === '{args.name}'", timeout=30000)
        idle()
        print(f"saved as {args.name}: drawn and saved in {time.perf_counter() - t_start:.1f} s")

        pg.select_option("#lsource", "signal:burst_1000hz_-10dbfs")  # hear 2 s of a burst
        pg.fill("#llen", "2")
        pg.keyboard.press("Escape")
        pg.keyboard.press("Control+Enter")
        print("heard:", pg.evaluate(HEARD))
        shot("4_heard")
        for m in msgs:
            print(m)
        b.close()


if __name__ == "__main__":
    main()
