"""The invented instruments' live tier (docs/INVENTED_LIVE_PLAN.md): each instrument's
keyboard as a reference that plays a performance step by step, written the way circuitsim's
`invented.rs` runs it (plain scalar arithmetic in the same order, sums in a loop), so the two
agree to rounding. The data each one reads is a component version of kind `invented_keys`
(`compile.py`), played by the IR element `invented_keys` (both builders).

Events are (step, kind, note, value) as `circuitsim.simulate(notes=)` takes them: kind "on"
(value = velocity 1-127, 0 = off), "off", "pedal" (value > 0 = down), "pressure"
(0-127, every key). An event at step p lands before sample p (circuitsim's keyed.rs).
"""
