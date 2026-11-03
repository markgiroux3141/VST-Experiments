# Thyratron prototype (HYBRID_PHYSICS_PLAN.md H1, 2026-11-02)

The lumped 2D21 model before it moved into `varimu/devices/thyratron.py`, kept until the
fit module (`varimu/devices/thyratron_fit.py`) replaces it:

- `thy_proto.py`: the model (the same equations, short names) and its observables (the
  strike as the ion balance's tangency, the steady arc, the pre-conduction stable state).
- `thy_fit.py`: least squares on the Sylvania curves (control family at shield-grid 0, +2,
  +8 V; pre-conduction ion current's knee; Ig / Ia in the arc) and RCA's tabulated values
  (8 V drop, 0.5 us ionization, 35 / 75 us deionization). `thy_fit.npy` / `fit_*.json`: its
  result (21 evaluations, stopped on xtol: the strike search is discretized, so the
  objective is slightly noisy).
- `thy_osc.py`: the sawtooth (B+ 300 V, 330k, 10 nF, 270 ohm anode resistor, the grid on
  47k from a bias) as a stiff ODE (scipy Radau) with the tube's own capacitances.

    uv run python scripts/prototypes/thyratron/thy_fit.py 300   # ~5 min
    uv run python scripts/prototypes/thyratron/thy_osc.py -2.5 0.02
