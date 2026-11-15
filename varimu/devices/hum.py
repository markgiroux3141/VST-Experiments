"""Hum from a stray mains field (2026-11-14): the constants both builders use.

A circuit file's `hum` block (varimu.circuit.spec) names its pickups: transformer parts whose
every winding of N turns sees an EMF N A_eff dB/dt from a stray field B (A_eff the part's
effective area, m^2: what of the field the core and its shield let through the turns), or a
single element (a moving coil's voice coil) with its turn-area N A_eff. A build with hum on
(`build(..., hum=)`, Rust `Hum`) puts that EMF in series with each pickup as one sine source per
harmonic of the field, in phase 0 (each starts at zero: no jump at the operating point), and
lists them with the mains parts (B5's mains wander moves them too, when the noise is on).
Nothing is added with hum off: the IR is the one without the block.

The field's spectrum: a power transformer's leakage field follows its magnetizing current,
whose saturation makes odd harmonics.
"""

# (harmonic of the mains, the field's amplitude re the fundamental). The EMF rises with
# frequency, so the EMFs are 1 : 0.3 : 0.1 (chain_spike's stray hum).
HARMONICS: tuple[tuple[int, float], ...] = ((1, 1.0), (3, 0.1), (5, 0.02))
HARMONICS_SOURCE = (
    "provisional: model knowledge (a power transformer's leakage field: the magnetizing "
    "current's odd harmonics, the 3rd ~10 % and the 5th ~2 % of the fundamental)"
)

FIELD_T = 1.0e-7
FIELD_SOURCE = (
    "provisional: the makers' reference field for hum pickup (RCA's 1e-3 gauss, Shure's "
    "milli-oersted, the BBC's 1 mG; 1 G = 100 uT in air): a quiet room. ~1 uT near equipment, "
    "~10 uT next to a power transformer"
)
AREA_M2 = 1.0e-4
AREA_SOURCE = (
    "provisional: no published hum figure; the order of the calibrated pickups (the 4038's "
    "4.2e-5, the 77-DX's 1.8e-4 m^2 a turn: scripts/hum_calibrate.py) and of the V76 hum "
    "spike's spec-bound 1e-4 (reports/chain_spike/)"
)


def transformer_block(part: str, hz: float | None) -> dict:
    """A generated circuit's `hum` block: transformer `part` at the provisional area, in the
    reference field; `hz` None takes the circuit's `mains` block's frequency."""
    block: dict = {}
    if hz is not None:
        where = "European" if hz == 50.0 else "US"
        block["hz"] = {
            "value": float(hz),
            "source": f"provisional: model knowledge ({where} mains, where it was made)",
        }
    block["field_t"] = {"value": FIELD_T, "source": FIELD_SOURCE}
    block["pickups"] = {part: {"area_m2": {"value": AREA_M2, "source": AREA_SOURCE}}}
    return block
