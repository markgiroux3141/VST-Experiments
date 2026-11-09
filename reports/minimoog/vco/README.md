# Minimoog oscillator 1: the reference and its reset (2026-11-09)

`config/circuits/minimoog_vco.yaml` (docs/MINIMOOG_PLAN.md MM3), trimmed by
`scripts/minimoog_vco_trim.py` (`trim.json`), studied by `scripts/minimoog_vco_study.py`
(`study.json`; runs cached in `cache/minimoog/vco/`).

## The reference

The oscillator only runs right with local error control at a step of ~0.1 us:

| Rate (error control on) | Period jitter (rms / p-p, cents) | Mean pitch |
|---|---|---|
| 768 kHz | 23 / 72 | +29 c (A 2') |
| 3.072 MHz | 1.6-2.0 / 7 | +0.8 c |
| 12.288 MHz | 0.07-0.09 / 0.3 | within 0.03 c of 49 MHz |
| 24.576 / 49.152 MHz | 0.02-0.03 / 0.1 | converged |

The tolerance (1e-3 .. 1e-7) changes nothing at a given rate; error control does engage (~15
halvings per reset, its 4-level cap). The jitter is not the trigger's timing (2 us rms of period at
3 MHz, far above any substep) but the reset's end state: Q4's gate swings ~15 V through its gate
capacitances, the channel closing in tens of ns decides how much of that charge stays on C7, and a
few mV of start level is a cent or two of period. **The reference is 12.288 MHz with error control
(1e-5): 205-280x slower than real time per oscillator.**

## The trims (Folkman's procedure plus HI END, solved jointly)

SHIFT 0.831, SCALE 0.666, HI END 0.287 (R31 2.87K: R31 x C7 = 2.9 us), OCT ADJ 0.508. Low A, high A,
top C on 2' and the low A on 8' within 0.05 cents; the low A on 32' (not trimmed) -0.4 cents.

## The reset (anatomy at 24.576 MHz)

| | 27.5 Hz | 110 Hz | 440 Hz | 1760 Hz | 4186 Hz |
|---|---|---|---|---|---|
| comparator pulse | 0.28 us | 0.31 | 0.30 | 0.31 | 0.31 |
| dead time (threshold to restart) | 0.87 us | 0.81 | 0.71 | 0.65 | 0.61 |
| C7 short of the +5 V reference | 74 mV | 77 | 67 | 63 | 65 |
| ramp's restart level | 4.864 V | 4.863 | 4.859 | 4.842 | 4.808 |
| its spread, period to period | 0.17 mV | 0.05 | 0.07 | 0.03 | 0.04 |

The dead time is 0.25 % of the period at the top C; HI END's R31 x C7 (2.9 us) also takes out the
restart level's fall with pitch and the summer's offsets.

## Direct simulation against the reference

| Candidate | What happens |
|---|---|
| draft (96 kHz), draft-2x, production (esdirk4 2x, error control) | **stalls at every pitch**: the ramp sits at 0 V, no reset |
| production at 8x (768 kHz, error control) | runs to 1760 Hz, 17-24 c rms jitter, C7 over-charged (5.3 V); stalls at the top C |
| M1 island at 8-64x (no error control inside) | hundreds of cents off, the ramp overshooting to 8 V |
| M1 at 128x (12.288 MHz, no error control) | 8-27 c off, 16-26 c rms jitter, C7 over-charged |

The stall: at a step of microseconds the L-stable solver damps the comparator / Q4 loop (a ~0.3 us
regenerative pulse), and the loop settles into an equilibrium the real circuit can't hold: the
comparator in its linear region, Q4 half on, feeding exactly the expo's current. Without error
control even 12.288 MHz over-charges C7 (the gate's turn-off unresolved).

Costs (one job, quiet machine for the reference; the candidates' in study.json ran 12 at once):
the reference 205-280x real time; production-8x 9-21x; M1 8-128x islands 8-230x; the draft
0.5-0.9x while stalled (the summers, expo and shapers alone: the floor any live tier pays).

## Technique K: the reset and the rectangle as event kernels (built 2026-11-09)

The user's call after the study above: K for live play and renders (the circuit's `exceptions`
with `renders: true`; only a `literal` build, the reference's, has the parts). Tables by
`scripts/minimoog_event_tables.py` -> `config/events/minimoog_osc_{reset,edge}.json`:

- **reset** (`XRESET`, `varimu/devices/reset_events.py` ResetRun, circuitsim `reset_events.rs`):
  replaces Q4, IC8B and their network (C9, CR1, R32-R35, C12); senses the ramp, injects the
  reset's charge from the +5 V reference into C7's lower plate; Q4's off-state gate-to-drain
  capacitance stays as a part. Tables over the ramp's slope (62 points, 4 V/s .. 160 kV/s) from
  the oscillator less its summers with V01 driven (the expo itself, so Q7's dynamics are the
  instrument's: an ideal current sink there left K 2-7 cents sharp).
- **the deficit**: the band-limited capacitor reaches its new voltage ~1.5 samples after the
  physical one and Q7 (Early effect, G = Ic / 98.6 V from the clean runs' ramp curvature) removes
  less meanwhile: removed from C7 in the event's shape. Without it the top C ran 7 cents flat at
  96 kHz (first order in the step).
- **edge** (`XRECT`, EdgeRun): replaces IC8A; the collector's load current switched through a
  band-limited step, tables per direction over the input's slope (37 points). It **follows the
  reset** (`follows: XRESET`, `follow_gain` 0.7003 the ramp's divider to its input): it senses the
  physical input (the reset's lag taken out) and turns off at the reset's own phase. Stacked on
  the band-limited saw instead, the duty ran 63 % at 4 kHz.
- The live Newton tolerance for this circuit is 1e-3 V (`panel::Device::newton`): the draft's
  1e-2 V put tens of cents of error on the sensed ramp.

Against the reference (study.json `k-draft`: 96 kHz trbdf2; `k-production`: esdirk4 at 192 kHz):

| | 27.5 Hz | 110 Hz | 440 Hz | 1760 Hz | 4186 Hz |
|---|---|---|---|---|---|
| pitch, draft (cents) | -0.01 | -0.26 | +0.46 | +0.03 | +0.56 |
| pitch, production | +0.08 | +0.44 | -0.30 | +0.20 | +0.57 |
| saw inharmonic, draft / production (dB; reference) | -41 / -47 (-42) | -105 / -102 (-55) | -97 / -96 (-54) | -58 / -90 (-53) | -53 / -83 (-57) |
| rectangle duty, draft (reference) | 51.72 % (51.79) | 51.69 (51.97) | 51.64 (52.20) | 51.43 (51.63) | 51.52 (51.65) |
| triangle inharmonic, draft / production (reference) | -70 / -71 (-71) | -49 / -97 (-66) | -31 / -53 (-64) | -36 / -51 (-59) | -33 / -50 (-61) |

The triangle at the draft is the open item: its fold (Q6) maps the reset's band-limited jump
(~2 samples at 96 kHz) through the whole V, which the real jump (0.5 us) passes through C13 /
R41's 5 us unseen; at 192 kHz half that.

Cost (one job): draft 0.47-0.89x real time, production 1.2-2.1x. Live in varimu-app
(`minimoog_vco`, draft-2x, `examples/play.rs --hold`): 41 % load, worst block 67-70 %, no
dropouts at A3, A5 and C7.
