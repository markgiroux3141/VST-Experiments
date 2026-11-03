"""Sort the drum and percussion one-shots of a sample library into samples/drums/.

    uv run python scripts/import_samples.py --root "D:/Music stuff/Reason/SAMPLE LIBRARY"
    uv run python scripts/import_samples.py --root DIR --dry-run   # classify, report, write nothing

Reads every WAV / AIFF under the root (and inside its .zip files), decides from the
name, the folder and a few packs' naming schemes what each one is (`classify`), and
copies the drums and percussion into samples/drums/<category>/<pack>_<name>.wav.

Numbered hits in drum kits (`DRE1-1AB 007`, `hbx04-03`) have no name to go by: a
nearest-neighbour vote on spectral and envelope features, trained on the library's
named one-shots (`guess`), puts them in samples/drums/unlabeled/<guess>/. Its
leave-one-out accuracy on the named ones is printed and saved in the index.

Every output is a PCM WAV at the source's rate and channel count (16-bit for 8- and
16-bit, ADPCM and mu-law sources, 24-bit for 24-bit, float for 32-bit): what the
app's WAV reader (hound) takes, lossless from the source. Identical audio is copied
once; the index lists every source it came from.

Writes samples/drums/index.json: per sample its category, how it was decided (name,
pack, guess), the pack, rate, channels, duration, the PCM's SHA-256 and the sources.
The library is the user's; samples/ is never committed (only its README).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "samples" / "drums"
AUDIO_EXT = {".wav", ".aif", ".aiff"}
MIN_DUR_S = 0.02  # shorter is a ROM's looped single cycle, not a hit
GUESS_MAX_DUR_S = 2.5  # numbered files longer than this aren't guessed (loops, phrases)
LOOP_MIN_DUR_S = 1.0

# The categories, in the order the name rules try them (first match wins).
# Each: (category, pattern on the normalized name, needs a drum folder).
_W = r"(?:^|\s)"  # word start on the normalized name (letters, digits, single spaces)
_E = r"(?:\s|$)"
RULES: list[tuple[str, str, bool]] = [
    (
        "loop",
        rf"{_W}(?:drum ?)?loops?{_E}|{_W}breaks?{_E}|{_W}break ?beat|{_W}\d+ ?bpm{_E}|{_W}bpm",
        False,
    ),
    ("roll", rf"{_W}(?:drum ?)?rolls?{_E}|drumroll", False),
    (
        "hihat_open",
        rf"{_W}(?:o ?hh|hho|hhopen|ohh|open ?hats?|hat ?op(?:en)?|hi ?hat open|hh open"
        rf"|open hi ?hat){_E}",
        False,
    ),
    ("hihat_open", rf"{_W}oh{_E}", True),
    ("hihat_pedal", rf"{_W}(?:hhp|pedal ?hats?|pedal){_E}", False),
    (
        "hihat_closed",
        rf"{_W}(?:hhc|chh|c ?hh|hhclose|closed ?hats?|hat ?cl(?:osed)?|closed){_E}",
        False,
    ),
    ("hihat_closed", rf"{_W}ch{_E}", True),
    (
        "hihat",
        rf"{_W}(?:hi ?hats?|hihats?|hh|hats?|ughat|schat|crunch ?hat|punch ?hat|fast hats?){_E}",
        False,
    ),
    ("hihat", r"(?<![wct])hatt?[sz]?a?\b|\bhat", False),  # glued: frathat, madhattz, hatphat
    ("orchestral", r"timpani|concert bass drum|orchestra", False),
    ("crash", rf"{_W}crash", False),
    ("ride", rf"{_W}ride{_E}|{_W}ride ?bell", False),
    ("cymbal", rf"{_W}(?:china|chinese|splash|cymbals?|cym|cymb|crm|rev cymbal){_E}", False),
    ("rim", rf"{_W}rim|side ?stick|sidestick", False),
    ("clap", rf"{_W}(?:claps?|clappo|claptrap|multi ?clap|delay ?clap|cl[ab]?){_E}|clap", False),
    ("snap", rf"{_W}(?:snaps?|finger ?snap|finger|delay ?snap){_E}", True),
    (
        "snare",
        rf"snare|{_W}snr{_E}|{_W}(?:sd|snar|scsnr|bsnrb?|crunch ?snr|punch ?snr){_E}|snr",
        False,
    ),
    (
        "tom",
        rf"{_W}toms?{_E}|tomhi|tomlow|tommid|{_W}(?:ltm|mtm|htm|ftm|mth|hth|lth|tm){_E}|floor ?tom",
        False,
    ),
    (
        "kick",
        rf"kick|{_W}(?:kik|kix|bd|bdrum|b drum|kic|sub ?kick|ugkick|crunch ?kik|punch ?kik){_E}"
        rf"|bass ?drum|kik\b|kix\b|kiked|{_W}k{_E}",
        False,
    ),  # glued: nicekik, fratkix
    (
        "hand_drum",
        r"conga|bongo|timbale|djembe|tabla|surdo|cuica|taiko|\budu\b|darbuka|doumbek|bodhran|quinto|tumba|dhol",
        False,
    ),
    ("shaker", r"shaker|shkr|\bshake\b|maraca|cabasa|rassel|\begg\b|rattle", False),
    ("tambourine", r"tambourine|tamborine|\btambo|\btamb\b|pandeir", False),
    ("cowbell", r"cow ?bell|\bcb\b", False),
    ("metal_perc", r"agogo|triangle|bell ?tree|chimes?\b|\bgong\b|anvil", False),
    ("metal_perc", r"\bbells?\b", True),
    (
        "wood_perc",
        r"clave|wood ?block|castanet|guiro|temple ?block|vibraslap|\bwhip\b|slapstick",
        False,
    ),
    (
        "mallet",
        r"marimba|vibraphone|\bvibra\b|glock|glokenspiel|xylophone|kalimba|steel ?drum|gamelan"
        r"|celest",
        False,
    ),
    ("perc", r"percussion|\bperc\b|\bperk\b|drum hit|\bdrum\b|whistle", False),
    (
        "perc_fx",
        r"knock|wack|whack|tink|clank|click|crunch|crackle|scrape|thluck|\bslap\b|pluck|\bhit\b|\bzap\b"
        r"|\bnoise\b|\bbuzz\b|\bboom\b|\bblip\b|smack|\bpuh\b|\bpop\b|thump",
        True,
    ),
]
# Words that make a file something other than a drum (unless a drum word is also there).
NOT_DRUM = re.compile(
    r"guitar|gtr|\bgt\b|piano|keyboard|\bkeys?\b|organ|string|violin|viola|cello|synth|\bsyn\b|\bpad\b|choir"
    r"|\bvox\b|vocal|voice|horn|brass|\bsax\b|flute|trumpet|\blead\b|arpeggio|\barp\b|chord|\bstab\b|sitar|koto"
    r"|\bharp\b|accordion|\bbass\b(?! ?drum)|\bsub\b(?! ?kick)|bassline|scratch|vinyl ?crackle"
    r"|applause"
)
STRONG = {
    "kick",
    "snare",
    "hihat",
    "hihat_open",
    "hihat_closed",
    "hihat_pedal",
    "clap",
    "crash",
    "ride",
    "cymbal",
    "tom",
    "rim",
}
# The guess's coarse classes (a category maps to one; None: not trained on).
COARSE = {
    "kick": "kick",
    "snare": "snare",
    "rim": "snare",
    "clap": "clap",
    "snap": "clap",
    "hihat_closed": "hihat_closed",
    "hihat_pedal": "hihat_closed",
    "hihat_open": "hihat_open",
    "crash": "cymbal",
    "ride": "cymbal",
    "cymbal": "cymbal",
    "tom": "tom",
    "hand_drum": "perc",
    "shaker": "perc",
    "tambourine": "perc",
    "cowbell": "perc",
    "metal_perc": "perc",
    "wood_perc": "perc",
    "perc": "perc",
    "perc_fx": "perc",
}
# Folders whose names say they are drum kits, whatever their files are called.
DRUM_FOLDER = re.compile(
    r"drum|kit|beats?\b|perc|machines|knock|snare|hotbox|timb|dre\d|inter\d|neptun", re.I
)
# Packs that name hits by a code: (folder pattern, name pattern, category by the code's group).
CODED = [
    (
        re.compile(r"MACHINES$"),
        re.compile(r"^([A-Z])-\d+"),
        {
            "K": "kick",
            "S": "snare",
            "T": "tom",
            "H": "hihat",
            "C": "cymbal",
            "P": "perc",
            "M": "mallet",
        },
    ),
    (
        re.compile(r"Neptunian Drumz"),
        re.compile(r"^N\d([KSP])\d+$"),
        {"K": "kick", "S": "snare", "P": "perc"},
    ),
    # dpadex's Ambience Kit: GM note, code, velocity (A49CR1095: crash 1 at 95, A37CRM: cross rim)
    (
        re.compile(r"Ambience Kit"),
        re.compile(r"^A\d\d([A-Z]+?)\d?\d{3}$"),
        {
            "ORM": "rim",
            "CRM": "rim",
            "BD": "kick",
            "SD": "snare",
            "FTM": "tom",
            "LTM": "tom",
            "MTH": "tom",
            "HTH": "tom",
            "HHC": "hihat_closed",
            "HHP": "hihat_pedal",
            "HHO": "hihat_open",
            "CR": "crash",
            "RD": "ride",
            "RDC": "ride",
        },
    ),
]
# The Dre / Timb / Inter / Vinyl / ModernBeats banks (DRE1-1AB 007): 32 hits, 001-012 kicks,
# 013-022 snares (the blind guess agreed for ~95% of them, 2026-11-02), 023-032 mixed.
BANK = re.compile(r"^[A-Z0-9]+-\d(?:AB|CD) (\d{3})$")
# Codes that mean "not a drum" in those packs (MACHINES' E effects, B basses).
CODED_SKIP = {"MACHINES": {"E", "B"}}


@dataclass
class Item:
    source: str  # relative to the root ("a.zip!inner.wav" inside a zip)
    pack: str
    folder: str  # the file's own folder, relative
    stem: str
    fs: int = 0
    ch: int = 0
    subtype: str = ""
    dur_s: float = 0.0
    pcm_sha256: str = ""
    audio: np.ndarray | None = field(default=None, repr=False)
    category: str | None = None
    how: str = ""
    error: str = ""


def normalize(stem: str) -> str:
    s = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", stem)  # camelCase, ZKRide
    s = re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", s)
    s = re.sub(r"[^A-Za-z0-9]+", " ", s.lower())
    return " ".join(s.split())


def pack_of(rel_dir: str) -> str:
    parts = rel_dir.split("/") if rel_dir else ["root"]
    head = parts[0]
    if head.lower() == "uncompressed refils" and len(parts) > 1:
        head = parts[1]
    return re.sub(r"[^a-z0-9]+", "-", head.lower()).strip("-") or "root"


def sources(root: Path):
    """(relative source, folder, stem, bytes or path) for every audio file, zips included."""
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        folder = p.parent.relative_to(root).as_posix() if p.parent != root else ""
        if p.suffix.lower() in AUDIO_EXT:
            yield rel, folder, p.stem, p
        elif p.suffix.lower() == ".zip":
            try:
                zf = zipfile.ZipFile(p)
            except zipfile.BadZipFile:
                continue
            with zf:
                for name in zf.namelist():
                    if Path(name).suffix.lower() in AUDIO_EXT:
                        inner = Path(name)
                        sub = "/".join(
                            x for x in (folder, p.stem, inner.parent.as_posix()) if x and x != "."
                        )
                        yield f"{rel}!{name}", sub, inner.stem, zf.read(name)


def load(root: Path) -> list[Item]:
    items = []
    for rel, folder, stem, src in sources(root):
        it = Item(source=rel, pack=pack_of(folder), folder=folder, stem=stem)
        try:
            f = io.BytesIO(src) if isinstance(src, bytes) else str(src)
            info = sf.info(f)
            if isinstance(f, io.BytesIO):
                f.seek(0)
            x, fs = sf.read(f, dtype="float32", always_2d=True)
            it.fs, it.ch, it.subtype, it.dur_s = fs, info.channels, info.subtype, len(x) / fs
            it.pcm_sha256 = hashlib.sha256(np.ascontiguousarray(x).tobytes()).hexdigest()
            it.audio = x
        except Exception as e:  # noqa: BLE001 (a malformed file is reported, not fatal)
            it.error = f"{type(e).__name__}: {e}"
        items.append(it)
    return items


def by_name(norm: str, drum_folder: bool) -> str | None:
    for cat, pat, needs_folder in RULES:
        if needs_folder and not drum_folder:
            continue
        if re.search(pat, norm):
            return cat
    return None


def classify(items: list[Item]) -> None:
    """Category from the name, a pack's code or layout (None: not a drum, or left to the guess)."""
    hits = defaultdict(lambda: [0, 0])  # folder -> [strong drum names, files]
    for it in items:
        cat = by_name(normalize(it.stem), True)
        hits[it.folder][0] += cat in STRONG
        hits[it.folder][1] += 1
    for it in items:
        if it.error:
            continue
        if it.dur_s < MIN_DUR_S or not np.any(it.audio):
            it.how = "skipped: too short or silent"
            continue
        strong, n = hits[it.folder]
        mostly_drums = strong / n >= 0.25
        drum_folder = bool(DRUM_FOLDER.search(it.folder)) or mostly_drums
        bank = BANK.match(it.stem)
        if bank:
            n = int(bank.group(1))
            it.category, it.how = (
                ("kick", "bank layout")
                if n <= 12
                else ("snare", "bank layout")
                if n <= 22
                else (None, "to guess")
            )
            continue
        for fpat, npat, groups in CODED:
            m = npat.match(it.stem)
            if fpat.search(it.folder) and m:
                code = m.group(1)
                if code in CODED_SKIP.get(it.folder, set()):
                    it.how = f"skipped: {it.folder} code {code}"
                elif code in groups:
                    # the code's group, refined by the rest (H-306 Heavy Open: hihat_open)
                    group = groups[code]
                    rest = normalize(it.stem[m.end() :])
                    if group == "hihat":  # H-315 Pop Open: the hat's state is the word
                        rest = next(
                            (f"{w} hat" for w in ("open", "pedal", "closed") if w in rest.split()),
                            "hat",
                        )
                    named = by_name(rest, True)
                    refine = named is not None and (
                        COARSE.get(named) == COARSE.get(group)
                        or group in ("hihat", "cymbal", "perc")
                        or (group == "snare" and named in ("rim", "roll"))
                    )
                    it.category, it.how = (named if refine else group), f"pack code {code}"
                break
        if it.category or it.how:
            continue
        norm = normalize(it.stem)
        cat = by_name(norm, drum_folder)
        if cat is not None and NOT_DRUM.search(norm) and cat not in STRONG:
            cat = None
        if cat is None and NOT_DRUM.search(norm):
            continue
        drum_words = re.search(r"drum|beat|perc|rhythm|break|groove", norm)
        if cat == "loop" and (it.dur_s < LOOP_MIN_DUR_S or not (mostly_drums or drum_words)):
            cat = None
        if cat is not None:
            it.category, it.how = cat, "name"
        elif drum_folder and it.dur_s <= GUESS_MAX_DUR_S and numbered(norm):
            it.how = "to guess"  # numbered: the guess decides


def numbered(norm: str) -> bool:
    """A code and numbers only (hbx 04 01, hotbox 02 01), not a note name (02 c) or words."""
    tokens = norm.split()
    return (
        any(t.isdigit() for t in tokens)
        and all(t.isdigit() or 2 <= len(t) <= 6 for t in tokens)
        and sum(not t.isdigit() for t in tokens) <= 1
    )


# --- the guess ------------------------------------------------------------------------------

BANDS_HZ = [20, 60, 120, 250, 500, 1000, 2000, 4000, 8000, 16000]


def features(x: np.ndarray, fs: int) -> np.ndarray:
    m = x.mean(axis=1).astype(np.float64)
    i0 = int(np.argmax(np.abs(m) > 0.05 * np.abs(m).max()))  # the onset
    m = m[i0:]
    env = np.abs(m)
    win = max(1, int(0.005 * fs))
    env = np.convolve(env, np.ones(win) / win, mode="same")
    peak_i = int(np.argmax(env))
    pk = env[peak_i] + 1e-12

    def time_below(db):
        below = np.nonzero(env[peak_i:] < pk * 10 ** (db / 20))[0]
        return (below[0] if len(below) else len(env) - peak_i) / fs

    feats = [
        np.log(peak_i / fs + 1e-4),
        np.log(time_below(-10) + 1e-3),
        np.log(time_below(-30) + 1e-3),
    ]
    for seg_s in ((0.0, 0.03), (0.03, 0.25)):
        seg = m[int(seg_s[0] * fs) : int(seg_s[1] * fs)]
        n = 1 << max(10, int(np.ceil(np.log2(max(len(seg), 2)))))
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)) if len(seg) > 1 else seg, n)) ** 2
        f = np.fft.rfftfreq(n, 1 / fs)
        e = np.array(
            [
                spec[(f >= lo) & (f < hi)].sum()
                for lo, hi in zip(BANDS_HZ[:-1], BANDS_HZ[1:], strict=True)
            ]
        )
        feats.extend(np.log(e / (e.sum() + 1e-20) + 1e-6))
        p = spec[(f > 20) & (f < min(fs / 2, 16000))] + 1e-20
        feats.append(np.mean(np.log(p)) - np.log(np.mean(p)))  # spectral flatness (log)
    return np.array(feats)


def guess(items: list[Item], k: int = 7) -> dict:
    train = [
        it
        for it in items
        if it.category
        and COARSE.get(it.category)
        and it.dur_s <= GUESS_MAX_DUR_S
        and it.how != "bank layout"
    ]
    todo = [it for it in items if it.how == "to guess"]
    xt = np.array([features(it.audio, it.fs) for it in train])
    yt = np.array([COARSE[it.category] for it in train])
    mu, sd = xt.mean(0), xt.std(0) + 1e-9
    zt = (xt - mu) / sd

    def vote(z, exclude=None):
        d = ((zt - z) ** 2).sum(1)
        if exclude is not None:
            d[exclude] = np.inf
        nn = np.argsort(d)[:k]
        c = Counter(yt[nn])
        lab, n = c.most_common(1)[0]
        return lab, n / k

    loo = [vote(zt[i], exclude=i)[0] for i in range(len(zt))]
    acc = float(np.mean(np.array(loo) == yt))
    confusion = defaultdict(Counter)
    for t, p in zip(yt, loo, strict=True):
        confusion[t][p] += 1
    for it in todo:
        lab, share = vote((features(it.audio, it.fs) - mu) / sd)
        it.category, it.how = lab, f"guess ({share:.0%} of {k} neighbours)"
    return {
        "k": k,
        "trained_on": len(train),
        "leave_one_out_accuracy": round(acc, 3),
        "confusion": {t: dict(c) for t, c in sorted(confusion.items())},
    }


# --- output ---------------------------------------------------------------------------------


def out_subtype(subtype: str) -> str:
    return {"PCM_24": "PCM_24", "PCM_32": "FLOAT", "FLOAT": "FLOAT", "DOUBLE": "FLOAT"}.get(
        subtype, "PCM_16"
    )


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "x"


def write(items: list[Item], report: dict, dry_run: bool) -> list[dict]:
    chosen: dict[str, Item] = {}
    dups: dict[str, list[str]] = defaultdict(list)
    for it in sorted(items, key=lambda i: (i.how.startswith("guess"), len(i.source), i.source)):
        if not it.category:
            continue
        dups[it.pcm_sha256].append(it.source)
        if it.pcm_sha256 not in chosen:
            chosen[it.pcm_sha256] = it
    if not dry_run and OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    used = set()
    index = []
    for sha, it in sorted(
        chosen.items(), key=lambda kv: (kv[1].category, kv[1].pack, kv[1].stem.lower())
    ):
        sub = Path("unlabeled", it.category) if it.how.startswith("guess") else Path(it.category)
        base = f"{it.pack}_{slug(it.stem)}"
        name, n = f"{base}.wav", 2
        while (sub / name).as_posix() in used:
            name, n = f"{base}-{n}.wav", n + 1
        rel = (sub / name).as_posix()
        used.add(rel)
        if not dry_run:
            (OUT_DIR / sub).mkdir(parents=True, exist_ok=True)
            sf.write(OUT_DIR / rel, it.audio, it.fs, subtype=out_subtype(it.subtype))
        index.append(
            {
                "file": rel,
                "category": it.category,
                "how": it.how,
                "pack": it.pack,
                "fs_hz": it.fs,
                "channels": it.ch,
                "duration_s": round(it.dur_s, 4),
                "source_subtype": it.subtype,
                "pcm_sha256": sha,
                "sources": dups[sha],
            }
        )
    if not dry_run:
        (OUT_DIR / "index.json").write_text(
            json.dumps({"report": report, "samples": index}, indent=1)
        )
    return index


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true", help="classify and report, write nothing")
    ap.add_argument(
        "--list",
        metavar="CATEGORY",
        help="print the sources sorted into CATEGORY ('none': not drums)",
    )
    args = ap.parse_args()

    items = load(args.root)
    classify(items)
    for it in items:
        if not it.category and it.how != "to guess":
            it.audio = None  # not a drum: free it
    g = guess(items)
    report = {
        "root": str(args.root),
        "files": len(items),
        "unreadable": [i.source for i in items if i.error],
        "guess": g,
    }
    index = write(items, report, args.dry_run)

    if args.list:
        want = None if args.list == "none" else args.list
        for it in items:
            if it.category == want and not it.error and not it.how.startswith("skipped"):
                print(f"  {it.dur_s:6.2f}s  {it.source}  [{it.how}]")
    cats = Counter(
        e["category"] if not e["how"].startswith("guess") else f"unlabeled/{e['category']}"
        for e in index
    )
    print(
        f"{len(items)} audio files, {sum(1 for i in items if i.error)} unreadable, "
        f"{sum(1 for i in items if i.category)} drums ({len(index)} unique)"
    )
    for c, n in sorted(cats.items()):
        print(f"  {c:28s} {n:5d}")
    acc = g["leave_one_out_accuracy"]
    print(f"guess: k={g['k']}, trained on {g['trained_on']}, leave-one-out accuracy {acc:.1%}")
    for t, row in g["confusion"].items():
        print(
            f"  {t:13s} "
            + " ".join(f"{p}:{n}" for p, n in sorted(row.items(), key=lambda kv: -kv[1]))
        )
    if not args.dry_run:
        print(f"-> {OUT_DIR.relative_to(REPO)}")


if __name__ == "__main__":
    main()
