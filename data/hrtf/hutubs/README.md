# HUTUBS HRTF database

Brinkmann, Dinakaran, Pelzer, Grosche, Voss and Weinzierl (2019), "A cross-evaluated database
of measured and simulated HRTFs including 3D head meshes, anthropometric features, and
headphone impulse responses", J. Audio Eng. Soc. 67(9), 705-718. Data: DOI
10.14279/depositonce-8487 (TU Berlin DepositOnce), **CC BY 4.0**.

96 subjects (1 and 96: the FABIAN head and torso simulator; 22 and 88: one person twice):
measured HRIRs (440 directions, 1.47 m, 44.1 kHz, blocked ear canal) and HRIRs simulated
by Mesh2HRTF's BEM on the head meshes (1730 directions); 58 closed head meshes (PLY, metres,
x forward, y left, z up, origin at the interaural centre; head and neck, no torso);
headphone IRs of the Sennheiser HD800S (all) and HD650 (64); anthropometry.

Not committed (`.gitignore`). To fetch again (the DSpace API, no browser needed):

    python - <<'PY'
    import json, urllib.request
    API = "https://api-depositonce.tu-berlin.de/server/api"
    get = lambda u: json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "varimu"})))
    item = get(API + "/pid/find?id=10.14279/depositonce-8487")
    for b in get(item["_links"]["bundles"]["href"])["_embedded"]["bundles"]:
        if b["name"] == "ORIGINAL":
            for bs in get(b["_links"]["bitstreams"]["href"])["_embedded"]["bitstreams"]:
                print(bs["name"], bs["_links"]["content"]["href"])
    PY

then `curl -L -o download/<name> <url>` each into `download/` and unzip here (`3D head meshes/`,
`HRIRs/`, `HpIRs/`, `anthropometry/`). Used by `varimu/binaural/` and
`scripts/binaural_validate.py` (docs/BINAURAL_PLAN.md).
