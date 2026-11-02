"""Run a prompts file through Google Flow, one prompt at a time, keeping only the best takes.

Two steps per prompt, so only the chosen images are upscaled and saved:

  gen   generate COUNT takes (default 3) of the next prompt, wait until Flow has finished them, download small 1K
        previews to a temp folder and build one labelled contact sheet. Nothing is written to the output folder.
  keep  upscale only the chosen takes (default 2K) and save them in the output folder as NN_a.jpg, NN_b.jpg; the
        previews are deleted. The next `gen` refuses to run while a prompt is still waiting for `keep`.

Usage:
  python batch.py PROMPTS.txt --list
  python batch.py PROMPTS.txt --out DIR gen  [--set 1] [--n 10] [--adopt] [--count 3] [--model nano] [--aspect 16:9]
  python batch.py PROMPTS.txt --out DIR keep 1,3 [--quality 2k]
  python batch.py PROMPTS.txt --out DIR status

`gen` without --n takes the first prompt of the set that is not done yet. --adopt uses the newest COUNT tiles already in
the Flow project instead of generating (for a prompt that was generated but not downloaded). Takes are numbered 1..COUNT
in Flow's tile order (newest first), as on the contact sheet. Progress lives in DIR/_flowscript_state.json.

Prompts file: lines starting with "Prompt N:"; other lines are ignored. When the numbering restarts at 1, a new set
begins (set 1, set 2, ...). Every command prints one JSON object on stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLOW_PS1 = ROOT / "flow.ps1"
PICK_PS1 = ROOT / "scripts" / "pick.ps1"
PROMPT_RE = re.compile(r"^\s*Prompt\s+(\d+)\s*:\s*(.+?)\s*$")
PREVIEW_ROOT = Path(tempfile.gettempdir()) / "flowscript-preview"
LETTERS = "abcdefghij"


def parse_sets(text: str) -> list[list[tuple[int, str]]]:
    sets: list[list[tuple[int, str]]] = []
    for line in text.splitlines():
        m = PROMPT_RE.match(line)
        if not m:
            continue
        n, prompt = int(m.group(1)), m.group(2)
        if not sets or (n == 1 and sets[-1]):
            sets.append([])
        sets[-1].append((n, prompt))
    return sets


def ps(script: Path, args: list[str], timeout_s: int) -> subprocess.CompletedProcess:
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_s)


def flow(args: list[str], timeout_s: int = 1200) -> dict:
    p = ps(FLOW_PS1, args, timeout_s)
    for line in reversed(p.stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                break
    return {"ok": False, "error": "no JSON from flow.py", "stdout": p.stdout[-800:], "stderr": p.stderr[-800:]}


def emit(obj: dict) -> int:
    print(json.dumps(obj, ensure_ascii=False), flush=True)
    return 0 if obj.get("ok", True) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompts")
    ap.add_argument("--out", help="output folder")
    ap.add_argument("--list", action="store_true", help="show the sets and prompt counts")
    ap.add_argument("action", nargs="?", choices=["gen", "keep", "status"])
    ap.add_argument("takes", nargs="?", help="for keep: the take numbers to keep, e.g. 1,3")
    ap.add_argument("--set", type=int, default=1, help="which prompt set (1 = first)")
    ap.add_argument("--n", type=int, help="prompt number (default: the next one not done)")
    ap.add_argument("--adopt", action="store_true", help="use the newest tiles already in Flow instead of generating")
    ap.add_argument("--count", type=int, default=3)
    ap.add_argument("--quality", default="2k", help="for keep: 2k | 1080p | original | best")
    ap.add_argument("--model", default="nano")
    ap.add_argument("--aspect", default="16:9")
    ap.add_argument("--timeout-min", type=int, default=15)
    a = ap.parse_args()

    sets = parse_sets(Path(a.prompts).read_text(encoding="utf-8-sig"))
    if a.list or not a.action:
        return emit({"sets": [{"set": i + 1, "prompts": len(s), "first": s[0][1][:80]} for i, s in enumerate(sets)]})
    if not a.out:
        return emit({"ok": False, "error": "--out is required"})
    if not 1 <= a.set <= len(sets):
        return emit({"ok": False, "error": f"set {a.set} not found; the file has {len(sets)} set(s)"})

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    state_file = out / "_flowscript_state.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    state.setdefault("done", {})
    save = lambda: state_file.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
    prompts = dict(sets[a.set - 1])

    if a.action == "status":
        done = sorted(int(k.split(":")[1]) for k in state["done"] if k.startswith(f"{a.set}:"))
        todo = [n for n in prompts if n not in done]
        return emit({"ok": True, "set": a.set, "done": done, "todo": todo, "pending": state.get("pending")})

    if a.action == "gen":
        if state.get("pending"):
            p = state["pending"]
            return emit({"ok": False, "error": f"prompt {p['n']} is waiting for `keep` (sheet: {p['sheet']})", "pending": p})
        n = a.n
        if n is None:
            n = next((k for k in prompts if f"{a.set}:{k}" not in state["done"]), None)
            if n is None:
                return emit({"ok": True, "message": f"all prompts of set {a.set} are done"})
        if n not in prompts:
            return emit({"ok": False, "error": f"prompt {n} is not in set {a.set}"})
        nn = f"{n:02d}"
        prev = PREVIEW_ROOT / f"set{a.set}_{nn}"
        shutil.rmtree(prev, ignore_errors=True)
        prev.mkdir(parents=True)
        t0 = time.time()
        if a.adopt:
            r = flow(["list", "image", "--limit", str(a.count)])
            tiles = r.get("tiles") or []
            if len(tiles) < a.count or any(t.get("failed") or t.get("progress") for t in tiles):
                return emit({"ok": False, "error": "the newest tiles are not finished images", "tiles": tiles})
            for t in tiles:
                d = flow(["download", str(t["i"]), "--quality", "original", "--out", str(prev), "--name", f"{nn}_{t['i'] + 1}"])
                if not d.get("ok", True) and d.get("error"):
                    return emit({"ok": False, "error": f"preview download failed: {d['error']}"})
            spent = 0
        else:
            print(f"[batch] prompt {n}: generating x{a.count}…", file=sys.stderr, flush=True)
            r = flow(["image", "-p", prompts[n], "--model", a.model, "--aspect", a.aspect, "--count", str(a.count),
                      "--download", "original", "--out", str(prev), "--name", nn, "--timeout", str(a.timeout_min)],
                     timeout_s=(a.timeout_min + 10) * 60)
            if not r.get("results"):
                return emit({"ok": False, "n": n, "error": r.get("error"),
                             "hint": "run `flow.ps1 list image --limit 6` before retrying; use --adopt if the tiles exist"})
            tiles = [{"i": x["index"], "title": x["title"], "failed": x["failed"]} for x in r["results"]]
            spent = r.get("credits_spent")
        takes = sorted(int(m.group(1)) for f in prev.iterdir() if (m := re.match(rf"^{nn}_(\d+)\.", f.name)))
        sheet = ps(PICK_PS1, ["-Out", str(prev), "-N", str(n), "-Sheet"], 120).stdout.strip().splitlines()
        state["pending"] = {"set": a.set, "n": n, "takes": takes, "tiles": tiles, "preview": str(prev),
                            "sheet": sheet[-1] if sheet else None}
        save()
        return emit({"ok": True, "n": n, "takes": takes, "sheet": state["pending"]["sheet"],
                     "failed": [t for t in tiles if t.get("failed")], "credits_spent": spent,
                     "seconds": round(time.time() - t0, 1), "next": f"keep <two of {takes}>"})

    if a.action == "keep":
        p = state.get("pending")
        if not p:
            return emit({"ok": False, "error": "nothing is waiting: run gen first"})
        try:
            chosen = [int(x) for x in (a.takes or "").split(",") if x.strip()]
        except ValueError:
            chosen = []
        if not chosen or any(c not in p["takes"] for c in chosen):
            return emit({"ok": False, "error": f"choose takes from {p['takes']}, e.g. keep 1,3"})
        nn = f"{p['n']:02d}"
        latest = flow(["list", "image", "--limit", str(max(p["takes"]))]).get("tiles") or []
        titles_now = [t["title"] for t in latest]
        titles_then = [t["title"] for t in sorted(p["tiles"], key=lambda t: t["i"])]
        if titles_now[:len(titles_then)] != titles_then:
            return emit({"ok": False, "error": "the Flow grid changed since gen (new tiles?), so take numbers no longer "
                         "match; download by hand with `flow.ps1 download <index>`", "now": titles_now, "then": titles_then})
        saved = []
        for k, take in enumerate(chosen):
            d = flow(["download", str(take - 1), "--quality", a.quality, "--out", str(out), "--name", f"{nn}_{LETTERS[k]}"])
            path = (d.get("download") or d).get("path") if isinstance(d, dict) else None
            if not path:
                return emit({"ok": False, "error": f"download of take {take} failed", "detail": d, "saved": saved})
            saved.append({"take": take, "path": path, "width": (d.get("download") or d).get("width"),
                          "height": (d.get("download") or d).get("height")})
        state["done"][f"{p['set']}:{p['n']}"] = {"kept": chosen, "files": [s["path"] for s in saved]}
        shutil.rmtree(p["preview"], ignore_errors=True)
        state.pop("pending")
        save()
        return emit({"ok": True, "n": p["n"], "saved": saved})
    return 1


if __name__ == "__main__":
    sys.exit(main())
