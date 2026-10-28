"""Train the net on the teacher's (B, H) sequences, teacher-forced (open loop).

Truncated backpropagation through time: a batch of whole sequences, cut into 10 ms chunks
(50 ms let gradients overflow to inf: v1, v2), the hidden state carried (detached) from
chunk to chunk; a step whose gradient isn't finite is skipped, so the net sees each sequence from
the demagnetized start as the bench does. The loss is the residual's error relative to
its local level (a 20 ms rms envelope of the teacher's residual), through log1p so that a
wild early error can't blow up a step (`--loss rel`):

    loss = mean(log1p(((r_net - r_teacher) / env)^2))

or the error of the companded output itself (`--loss y`, the default: no sinh in the loss,
well-conditioned from the start; v1 with `rel` learned slowly, then overflowed):

    loss = mean((y_net - asinh(r_teacher / R0))^2)

Validation is open loop on the test split's random items, every few epochs: the
residual's relative rms error per family (dB). The closed-loop checks are `evaluate.py`.

    uv run --extra ml python -m spike.neural_core.train [--name v1] [--epochs 400]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from spike.neural_core.bench import t101_bench
from spike.neural_core.model import R0_A_PER_M, TorchNet, features
from spike.neural_core.teacher import OUT_DIR, load

ENV_S = 0.02
ENV_FLOOR_A_PER_M = 1e-10


def s_lin() -> float:
    from varimu.devices.core import MU0

    return 1 / (MU0 * (1 + t101_bench().core_model().initial_susceptibility()))


def prepare(seqs_b, seqs_h, fs: int, slope: float):
    """Features (float32), teacher residual and its envelope, per sequence."""
    xs, rs, envs = [], [], []
    k = max(1, int(ENV_S * fs))
    win = np.ones(k) / k
    for b, h in zip(seqs_b, seqs_h, strict=True):
        b_prev = np.concatenate([[0.0], b[:-1]])
        xs.append(np.stack(features(b, b_prev), -1))
        r = h - slope * b
        rs.append(r)
        envs.append(np.sqrt(np.convolve(r * r, win, mode="same")) + ENV_FLOOR_A_PER_M)
    return xs, rs, envs


def rel_err_db(pred: np.ndarray, true: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean((pred - true) ** 2) / np.mean(true**2))))


def validate(net, items, xs, rs, device) -> dict[str, float]:
    """Open loop: per-family mean of the residual's relative rms error (dB)."""
    net.eval()
    per_fam: dict[str, list[float]] = {}
    with torch.no_grad():
        for (_name, meta), x, r in zip(items, xs, rs, strict=True):
            if "family" not in meta:
                continue
            y, _ = net(torch.tensor(x, dtype=torch.float32, device=device)[None])
            pred = R0_A_PER_M * np.sinh(y[0].double().cpu().numpy())
            per_fam.setdefault(meta["family"], []).append(rel_err_db(pred, r))
    net.train()
    return {f: float(np.mean(v)) for f, v in sorted(per_fam.items())}


def in_range(items, seqs, b_range):
    """The items (and their sequences) whose peak |B| is within b_range (None: all)."""
    if b_range is None:
        return items, seqs
    keep = [i for i, b in enumerate(seqs["b"]) if b_range[0] <= np.abs(b).max() <= b_range[1]]
    return [items[i] for i in keep], {k: [v[i] for i in keep] for k, v in seqs.items()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--name", default="v1")
    ap.add_argument("--hidden", type=int, default=32)
    ap.add_argument("--epochs", type=int, default=400)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--chunk", type=int, default=960)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--loss", choices=("y", "rel"), default="y")
    ap.add_argument("--validate-every", type=int, default=10)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument(
        "--b-peak-range",
        type=float,
        nargs=2,
        metavar=("LO_T", "HI_T"),
        help="train and validate only on items whose peak |B| is in this range (a diagnostic)",
    )
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    torch.backends.cudnn.deterministic = True
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    run_dir = OUT_DIR / "runs" / args.name
    run_dir.mkdir(parents=True, exist_ok=True)

    items, seqs, info = load("train")
    fs = info["fs_hz"]
    items, seqs = in_range(items, seqs, args.b_peak_range)
    slope = s_lin()
    xs, rs, envs = prepare(seqs["b"], seqs["h"], fs, slope)
    x = torch.tensor(np.stack(xs), dtype=torch.float32, device=device)
    r = torch.tensor(np.stack(rs), dtype=torch.float32, device=device)
    env = torch.tensor(np.stack(envs), dtype=torch.float32, device=device)
    n_seq, n_t = r.shape
    t_items, t_seqs, _ = load("test")
    t_items, t_seqs = in_range(t_items, t_seqs, args.b_peak_range)
    t_xs, t_rs, _ = prepare(t_seqs["b"], t_seqs["h"], fs, slope)
    print(f"train: {n_seq} x {n_t} samples on {device}; S_LIN {slope:.4g} A/m per T")

    net = TorchNet(args.hidden).to(device)
    opt = torch.optim.Adam(net.parameters(), lr=args.lr)
    chunks_per_epoch = -(-n_seq // args.batch) * -(-n_t // args.chunk)
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=args.lr, total_steps=args.epochs * chunks_per_epoch, pct_start=0.05
    )
    log = {"args": vars(args), "s_lin": slope, "epochs": []}
    best = float("inf")
    gen = torch.Generator(device="cpu").manual_seed(args.seed)
    t0 = time.perf_counter()
    for epoch in range(1, args.epochs + 1):
        order = torch.randperm(n_seq, generator=gen)
        losses = []
        skipped = 0
        for start in range(0, n_seq, args.batch):
            idx = order[start : start + args.batch].to(device)
            hidden = None
            for c in range(0, n_t, args.chunk):
                xb, rb, eb = (a[idx, c : c + args.chunk] for a in (x, r, env))
                y, hidden = net(xb, hidden)
                if args.loss == "y":
                    loss = ((y - torch.asinh(rb / R0_A_PER_M)) ** 2).mean()
                else:
                    pred = R0_A_PER_M * torch.sinh(y)
                    loss = torch.log1p(((pred - rb) / eb) ** 2).mean()
                opt.zero_grad(set_to_none=True)
                loss.backward()
                norm = torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
                if torch.isfinite(norm):
                    opt.step()
                else:  # an overflowed gradient: clipping it would write NaN into the weights
                    skipped += 1
                sched.step()
                hidden = hidden.detach()
                if torch.isfinite(loss):
                    losses.append(loss.item())
        entry = {"epoch": epoch, "loss": float(np.mean(losses)), "s": time.perf_counter() - t0}
        entry["skipped_steps"] = skipped
        if not np.isfinite(entry["loss"]):
            print(f"epoch {epoch}: loss not finite, stopping")
            break
        if epoch % args.validate_every == 0 or epoch == args.epochs:
            val = validate(net, t_items, t_xs, t_rs, device)
            entry["val_db"] = val
            mean_db = float(np.mean(list(val.values())))
            entry["val_mean_db"] = mean_db
            fams = " ".join(f"{k} {v:.1f}" for k, v in val.items())
            print(
                f"epoch {epoch} loss {entry['loss']:.4g} val {mean_db:.1f} dB ({fams}) "
                f"{entry['s']:.0f} s",
                flush=True,
            )
            if mean_db < best:
                best = mean_db
                torch.save(net.state_dict(), run_dir / "net.pt")
        elif epoch % 5 == 0:
            print(f"epoch {epoch} loss {entry['loss']:.4g} {entry['s']:.0f} s", flush=True)
        log["epochs"].append(entry)
        (run_dir / "log.json").write_text(json.dumps(log, indent=1))
    print(f"best val {best:.1f} dB -> {Path(run_dir) / 'net.pt'}")


if __name__ == "__main__":
    main()
