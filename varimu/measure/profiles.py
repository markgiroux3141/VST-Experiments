"""Per-circuit profiles (device builder B2): which measurements, setup and checks apply.

A profile names a circuit file (config/circuits/<name>.yaml) and the suite that
measures it: run(name, genome, clips=..., settings=..., log=...) -> report, with
report["plausible"] and report["checks"] (its plausibility screen: the generic
checks of varimu.measure.generic and the circuit's own).

- fairchild_670 (compressor): varimu.measure.suite, unchanged: the manual's setup
  procedures, compression curves, timing, response under gain reduction, IMD,
  thump, program clips; its checks are varimu.measure.plausibility's.
- pultec_eqp1a (equalizer): varimu.measure.eq_suite: response at every published
  family's extreme against the curves, THD vs level, the generic screen.
- fender_5e3 (guitar amplifier, B9): varimu.measure.amp_suite: gain per volume,
  response per tone, THD and power vs level (the clipping onset), supply sag on bursts,
  aliasing per quality; the generic screen with the kit's voltages at +-20%.
- ampex_351 (tape machine, TM5): varimu.measure.tape_suite: aligned by the manual's
  procedure (varimu.measure.tape_align), then the specs: idle voltages, response at
  -10 dB, THD against level (the 1% and 3% levels), S/N with the circuit's noise.
- telefunken_v76 (microphone preamp, B10): varimu.measure.preamp_suite: the Braunbuch's
  acceptance specs: gain at every position, response per filter, k2 / k3, THD against
  level, output impedance.
- telefunken_v72 (microphone preamp, the chains build-out's WP1): varimu.measure.v72_suite:
  the Braunbuch's specs: gain, response at two levels, input and output impedance, THD at
  the specs' points and against level (the datasheet's maximum output).
- ua_610 (microphone preamp, the chains build-out's WP2): varimu.measure.ua610_suite: gain
  (the links, the LEVEL law), response per HF / LF position, input and output impedance,
  THD against level; the 2-610 reissue's figures as a reference only.
- ampex_351_record (microphone preamp, the chains build-out's WP7): the 351's direct
  monitor, varimu.measure.a351_record_suite: RECORD LEVEL's law, the sensitivity and the
  drawing's stage levels, response, impedances, THD against level, the input stage's
  overload.
- fairchild_670_keyed (compressor with a KEY input, SIDECHAIN_PLAN.md K1):
  varimu.measure.keyed_suite: INT against the stock 670, the duck against the key's
  level, recovery per time constant, thump; keyed by a kick under a bass tone.
- ampex_300_4 (four-track tape deck, PERIOD_GEAR_BACKLOG.md PG1 MT5):
  varimu.measure.deck_suite: per channel the 351's response and THD, S/N against AI-14's
  four-track figure, crosstalk between neighbours against MT3's fitted curve.
- urei_1176 (FET limiter, B12): varimu.measure.limiter_suite: UA's reissue manual's
  figures: gain, response, maximum output, static curves per ratio, attack and release
  on the GR line, THD while limiting.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Profile:
    circuit: str
    kind: str  # "compressor" | "equalizer" | "guitar_amp" | "tape_machine" | "mic_preamp"
    run: Callable[..., dict[str, Any]]


def _run_670(*args, **kwargs):
    from varimu.measure import suite

    return suite.run(*args, **kwargs)


def _run_eq(*args, **kwargs):
    from varimu.measure import eq_suite

    return eq_suite.run(*args, **kwargs)


def _run_amp(*args, **kwargs):
    from varimu.measure import amp_suite

    return amp_suite.run(*args, **kwargs)


def _run_preamp(*args, **kwargs):
    from varimu.measure import preamp_suite

    return preamp_suite.run(*args, **kwargs)


def _run_v72(*args, **kwargs):
    from varimu.measure import v72_suite

    return v72_suite.run(*args, **kwargs)


def _run_ua610(*args, **kwargs):
    from varimu.measure import ua610_suite

    return ua610_suite.run(*args, **kwargs)


def _run_ssl(*args, **kwargs):
    from varimu.measure import opamp_pre_suite

    return opamp_pre_suite.run(*args, circuit="ssl_4000e", **kwargs)


def _run_neve1073(*args, **kwargs):
    from varimu.measure import opamp_pre_suite

    return opamp_pre_suite.run(*args, circuit="neve_1073", **kwargs)


def _run_api312(*args, **kwargs):
    from varimu.measure import opamp_pre_suite

    return opamp_pre_suite.run(*args, circuit="api_312", **kwargs)


def _run_helios(*args, **kwargs):
    from varimu.measure import opamp_pre_suite

    return opamp_pre_suite.run(*args, circuit="helios", **kwargs)


def _run_tg(*args, **kwargs):
    from varimu.measure import opamp_pre_suite

    return opamp_pre_suite.run(*args, circuit="emi_tg12345", **kwargs)


def _run_porta(*args, **kwargs):
    from varimu.measure import opamp_pre_suite

    return opamp_pre_suite.run(*args, circuit="tascam_portastudio", **kwargs)


def _run_a351_record(*args, **kwargs):
    from varimu.measure import a351_record_suite

    return a351_record_suite.run(*args, **kwargs)


def _run_keyed(*args, **kwargs):
    from varimu.measure import keyed_suite

    return keyed_suite.run(*args, **kwargs)


def _run_limiter(*args, **kwargs):
    from varimu.measure import limiter_suite

    return limiter_suite.run(*args, **kwargs)


def _run_tape(*args, **kwargs):
    from varimu.measure import tape_suite

    return tape_suite.run(*args, **kwargs)


def _run_deck(*args, **kwargs):
    from varimu.measure import deck_suite

    return deck_suite.run(*args, **kwargs)


PROFILES = {
    "fairchild_670": Profile("fairchild_670", "compressor", _run_670),
    "pultec_eqp1a": Profile("pultec_eqp1a", "equalizer", _run_eq),
    "fender_5e3": Profile("fender_5e3", "guitar_amp", _run_amp),
    "ampex_351": Profile("ampex_351", "tape_machine", _run_tape),
    "ampex_300_4": Profile("ampex_300_4", "tape_machine", _run_deck),
    "telefunken_v76": Profile("telefunken_v76", "mic_preamp", _run_preamp),
    "telefunken_v72": Profile("telefunken_v72", "mic_preamp", _run_v72),
    "ua_610": Profile("ua_610", "mic_preamp", _run_ua610),
    "ssl_4000e": Profile("ssl_4000e", "mic_preamp", _run_ssl),
    "tascam_portastudio": Profile("tascam_portastudio", "mic_preamp", _run_porta),
    "api_312": Profile("api_312", "mic_preamp", _run_api312),
    "neve_1073": Profile("neve_1073", "mic_preamp", _run_neve1073),
    "helios": Profile("helios", "mic_preamp", _run_helios),
    "emi_tg12345": Profile("emi_tg12345", "mic_preamp", _run_tg),
    "ampex_351_record": Profile("ampex_351_record", "mic_preamp", _run_a351_record),
    "fairchild_670_keyed": Profile("fairchild_670_keyed", "compressor", _run_keyed),
    "urei_1176": Profile("urei_1176", "compressor", _run_limiter),
}


def profile(circuit: str) -> Profile:
    try:
        return PROFILES[circuit]
    except KeyError:
        raise KeyError(f"no measurement profile for {circuit!r} ({', '.join(PROFILES)})") from None
