"""Train the incremental net (model_inc.py): regression of each sample's slope.

Every training sample (B_{n-1}, H_{n-1}, dB) -> g* = log(((H_n - H_{n-1}) / dB) / S_LIN),
where dB is large enough for the secant to be exact in float64 (|dB| > DB_MIN_T and
|dH| > 1e-9 |H|). Shuffled minibatches, MSE on g.

Validation rolls the net out open loop on the test split's random items (the teacher's B
in, the net's own H carried from sample to sample, as in the bench) and reports the
residual's relative error per family (dB), like train.py, so the two nets compare.

    uv run --extra ml python -m spike.neural_core.train_inc [--name inc1]
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np
import torch

from spike.neural_core.model_inc import IncNet, inputs
from spike.neural_core.teacher import OUT_DIR, load
from spike.neural_core.train import rel_err_db, s_lin

DB_MIN_T = 1e-11


def samples(seqs_b, seqs_h, slope: float):
    """Inputs (n, 3) and targets g* (n,) of every usable sample."""
    us, gs = [], []
    for b, h in zip(seqs_b, seqs_h, strict=True):
        b_prev = np.concatenate([[0.0], b[:-1]])
        h_prev = np.concatenate([[0.0], h[:-1]])
        db, dh = b - b_prev, h - h_prev
        ok = (np.abs(db) > DB_MIN_T) & (np.abs(dh) > 1e-9 * np.abs(h))
        sec = np.where(ok, dh / np.where(ok, db, 1.0), 1.0)
        ok &= sec > 0
        us.append(np.stack(inputs(b_prev[ok], h_prev[ok], db[ok]), -1))
        gs.append(np.log(sec[ok] / slope))
    return np.concatenate(us), np.concatenate(gs)


def rollout(net: IncNet, seqs_b, slope: float):
    """H of every sequence, the net carried open loop on the given B (numpy, batched by
    length)."""
    cell = net.to_numpy(slope)
    out = [None] * len(seqs_b)
    by_len: dict[int, list[int]] = {}
    for i, b in enumerate(seqs_b):
        by_len.setdefault(len(b), []).append(i)
    for idx in by_len.values():
        b = np.stack([seqs_b[i] for i in idx])
        cell.reset(len(idx))
        h = np.zeros_like(b)
        for t in range(b.shape[1]):
            h[:, t], _ = cell.eval(b[:, t])
            cell.accept(b[:, t])
        for j, i in enumerate(idx):
            out[i] = h[j]
    return out


def validate(net, items, seqs, slope) -> dict[str, float]:
    keep = [i for i, (_, meta) in enumerate(items) if "family" in meta]
    hs = rollout(net, [seqs["b"][i] for i in keep], slope)
    per_fam: dict[str, list[float]] = {}
    for i, h in zip(keep, hs, strict=True):
        b, h_true = seqs["b"][i], seqs["h"][i]
        fam = items[i][1]["family"]
        per_fam.setdefault(fam, []).append(rel_err_db(h - slope * b, h_true - slope * b))
    return {f: float(np.mean(v)) for f, v in sorted(per_fam.items())}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--name", default="inc1")
    ap.add_argument("--width", type=int, default=64)
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--batch", type=int, default=32768)
    ap.add_argument("--lr", type=float, default=3e-3)
    ap.add_argument("--validate-every", type=int, default=10)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    run_dir = OUT_DIR / "runs" / args.name
    run_dir.mkdir(parents=True, exist_ok=True)
    slope = s_lin()
    _, seqs, _ = load("train")
    u_np, g_np = samples(seqs["b"], seqs["h"], slope)
    u = torch.tensor(u_np, dtype=torch.float32, device=device)
    g = torch.tensor(g_np, dtype=torch.float32, device=device)
    n = len(g)
    print(
        f"{n} samples of {sum(len(b) for b in seqs['b'])}; g* in [{g_np.min():.2f}, "
        f"{g_np.max():.2f}], mean {g_np.mean():.2f}; inputs within +-{np.abs(u_np).max():.2f}"
    )
    t_items, t_seqs, _ = load("test")

    net = IncNet(args.width, args.depth).to(device)
    opt = torch.optim.Adam(net.parameters(), lr=args.lr)
    steps = args.epochs * -(-n // args.batch)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, args.lr, total_steps=steps, pct_start=0.05)
    gen = torch.Generator(device=device).manual_seed(args.seed)
    log = {"args": vars(args), "s_lin": slope, "epochs": []}
    best = float("inf")
    t0 = time.perf_counter()
    for epoch in range(1, args.epochs + 1):
        order = torch.randperm(n, generator=gen, device=device)
        total = 0.0
        for start in range(0, n, args.batch):
            idx = order[start : start + args.batch]
            loss = ((net(u[idx]) - g[idx]) ** 2).mean()
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            sched.step()
            total += loss.item() * len(idx)
        entry = {"epoch": epoch, "loss": total / n, "s": time.perf_counter() - t0}
        if epoch % args.validate_every == 0 or epoch == args.epochs:
            val = validate(net.cpu(), t_items, t_seqs, slope)
            net.to(device)
            mean_db = float(np.mean(list(val.values())))
            entry |= {"val_db": val, "val_mean_db": mean_db}
            fams = " ".join(f"{k} {v:.1f}" for k, v in val.items())
            print(
                f"epoch {epoch} loss {entry['loss']:.3g} (rms g error "
                f"{np.sqrt(entry['loss']):.3g}) val {mean_db:.1f} dB ({fams}) "
                f"{entry['s']:.0f} s",
                flush=True,
            )
            if mean_db < best:
                best = mean_db
                torch.save(net.state_dict(), run_dir / "net.pt")
        log["epochs"].append(entry)
        (run_dir / "log.json").write_text(json.dumps(log, indent=1))
    print(f"best val {best:.1f} dB -> {run_dir / 'net.pt'}")


if __name__ == "__main__":
    main()
