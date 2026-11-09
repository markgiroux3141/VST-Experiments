"""The LM393 comparator macro (config/circuits/lm393_test.yaml; docs/MINIMOOG_PLAN.md MM3) fitted to
TI's response times (SLCS005AH, "Switching Characteristics: LM193, LM239, LM393, ...", VCC 5 V,
RL 5.1 kOhm, CL 15 pF; the response time ends where the output crosses 1.4 V):

- 1.3 us for a 100 mV input step with 5 mV overdrive;
- 0.3 us for a TTL-level input step (0 to 3 V against a 1.4 V reference: 1.6 V of overdrive).

Two unknowns, the macro's gain-bandwidth and its slew limit, for the two figures; each figure is
the mean of the output's rising and falling response (the sheet gives one typical number).

    uv run --extra fast python scripts/fit_lm393.py [--write]

--write puts the fitted cmp_gbw_hz and cmp_slew_v_per_s into lm393_test.yaml and every circuit
listed in TARGETS (the files that carry the LM393's values)."""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR
from varimu.sim import fast
from varimu.sim.io import TransientSettings

CIRCUIT = CONFIG_DIR / "circuits" / "lm393_test.yaml"
TARGETS = [CIRCUIT, CONFIG_DIR / "circuits" / "minimoog_vco.yaml"]
OUT = Path(__file__).resolve().parents[1] / "reports" / "minimoog" / "lm393"
FS = 200_000_000  # 5 ns a sample
LEAD_S, RUN_S = 2e-6, 6e-6
THRESHOLD_V = 1.4
SHEET = {"small": 1.3e-6, "ttl": 0.3e-6}
# Each step as (input before, input after), IN- at 0 V: the sheet's 100 mV step with 5 mV of
# overdrive, and a TTL step (0 -> 3 V against 1.4 V), both ways.
STEPS = {
    "small": [(-0.095, 0.005), (0.095, -0.005)],
    "ttl": [(-1.4, 1.6), (1.6, -1.4)],
}


def settings() -> TransientSettings:
    s = TransientSettings.from_sim_settings(engine="circuitsim")
    return dataclasses.replace(
        s, sample_rate=FS, oversample=1, settle_s=2e-6, error_abstol=1e-6, error_reltol=1e-6,
        newton_reltol=1e-9, newton_vntol=1e-9, input_order=1,
    )  # fmt: skip


def response_s(s, gbw_hz: float, slew: float, before: float, after: float) -> float:
    ir = builder.build_ir(
        s, spec.resolve(s, {"cmp_gbw_hz": gbw_hz, "cmp_slew_v_per_s": slew}), "linear"
    )
    n0, n = round(LEAD_S * FS), round((LEAD_S + RUN_S) * FS)
    x = np.full(n, after)
    x[: n0 + 1] = before  # the step between samples n0 and n0 + 1 (linear in between)
    out = fast.run_transient(ir, x, settings=settings()).vectors["v(out)"]
    rising = out[n0] < THRESHOLD_V
    past = np.nonzero(out[n0:] > THRESHOLD_V if rising else out[n0:] < THRESHOLD_V)[0]
    if len(past) == 0:
        return float("inf")
    k = n0 + past[0]
    a, b = out[k - 1] - THRESHOLD_V, out[k] - THRESHOLD_V
    return ((k - 1 + a / (a - b)) - (n0 + 0.5)) / FS  # from the step's middle


def responses(s, gbw_hz: float, slew: float) -> dict[str, list[float]]:
    return {k: [response_s(s, gbw_hz, slew, *st) for st in v] for k, v in STEPS.items()}


def write(gbw_hz: float, slew: float) -> None:
    for path in TARGETS:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for key, v in (("cmp_gbw_hz", gbw_hz), ("cmp_slew_v_per_s", slew)):
            text, n = re.subn(rf"(\n  {key}: \{{value: )[^,]+", rf"\g<1>{v:.4e}", text)
            if n != 1:
                raise SystemExit(f"{path.name}: {key} not found once")
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.name}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    s = spec.load_circuit(CIRCUIT)

    def residual(p):
        r = responses(s, *np.exp(p))
        return [np.log(np.mean(r[k]) / SHEET[k]) for k in SHEET]

    x0 = np.log([20e6, 5e6])
    fit = least_squares(residual, x0, diff_step=1e-3, xtol=1e-6)
    gbw_hz, slew = (float(v) for v in np.exp(fit.x))
    r = responses(s, gbw_hz, slew)
    summary = {
        "gbw_hz": gbw_hz,
        "slew_v_per_s": slew,
        "response_s": r,
        "sheet_s": SHEET,
        "note": "each figure fitted as the mean of the rising and falling output's response",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "fit.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    if args.write:
        write(gbw_hz, slew)


if __name__ == "__main__":
    main()
