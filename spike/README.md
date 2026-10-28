# Spikes

Experiments that answer a question before anything goes into the product. A spike may
cut corners the project's hard rules don't allow in `varimu/` (one implementation, no
SPICE, fixed rates), as long as its README says which and why. Nothing here is imported
by `varimu/` or `crates/`, and nothing here is in the render cache key.

| Spike | Question | Status |
|---|---|---|
| [neural_core/](neural_core/) | Can a recurrent network, trained on an accurate (slow) simulation of a component with memory, stand in for it inside a circuit? | Stage 1: 3 of 4 checks pass; where we left off: [STATUS.md](neural_core/STATUS.md) (2026-10-28) |
