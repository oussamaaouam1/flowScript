"""Run a prompts file through Google Flow, one prompt at a time.

For every prompt: generate COUNT images (default 3) with Nano Banana, wait until Flow has finished them, download each
upscaled (default 2K) into OUT as NN_1.jpg, NN_2.jpg, NN_3.jpg, then move on to the next prompt. Progress is kept in
OUT/_flowscript_state.json, so a stopped run resumes where it left off (finished prompts are skipped).

Prompts file format (as written by the story tools): lines starting with "Prompt N:"; "Reference (...)" lines and
anything else are ignored. When the numbering restarts at 1, a new set begins (set 1, set 2, ...).

Usage:
  python batch.py PROMPTS.txt --out DIR [--set 1] [--from 3] [--to 17] [--count 3] [--quality 2k] [--model nano]
  python batch.py PROMPTS.txt --list            # show the sets and prompt counts, generate nothing

Each finished prompt prints one JSON line on stdout: {"n": 3, "files": [...], "failed": [...], "seconds": 41.2}.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLOW_PS1 = ROOT / "flow.ps1"
PROMPT_RE = re.compile(r"^\s*Prompt\s+(\d+)\s*:\s*(.+?)\s*$")


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


def run_flow(args: list[str], timeout_s: int) -> dict:
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(FLOW_PS1), *args]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_s)
    for line in reversed(p.stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                break
    return {"ok": False, "error": "no JSON from flow.py", "stdout": p.stdout[-800:], "stderr": p.stderr[-800:]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompts")
    ap.add_argument("--out", help="output folder")
    ap.add_argument("--set", type=int, default=1, help="which prompt set (1 = first)")
    ap.add_argument("--from", dest="start", type=int, default=1)
    ap.add_argument("--to", dest="end", type=int, default=None)
    ap.add_argument("--count", type=int, default=3)
    ap.add_argument("--quality", default="2k", help="original | 2k | best (passed to flow.py --download)")
    ap.add_argument("--model", default="nano")
    ap.add_argument("--aspect", default="16:9")
    ap.add_argument("--timeout-min", type=int, default=15, help="per prompt")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    sets = parse_sets(Path(a.prompts).read_text(encoding="utf-8-sig"))
    if a.list or not a.out:
        print(json.dumps({"sets": [{"set": i + 1, "prompts": len(s), "first": s[0][1][:80]} for i, s in enumerate(sets)]},
                         ensure_ascii=False, indent=1))
        return 0
    if not 1 <= a.set <= len(sets):
        print(json.dumps({"ok": False, "error": f"set {a.set} not found; the file has {len(sets)} set(s)"}))
        return 1

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    state_file = out / "_flowscript_state.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {"done": {}}

    for n, prompt in sets[a.set - 1]:
        if n < a.start or (a.end and n > a.end):
            continue
        key = f"{a.set}:{n}"
        if key in state["done"]:
            print(f"[batch] prompt {n}: already done, skipping", file=sys.stderr)
            continue
        name = f"{n:02d}"
        print(f"[batch] prompt {n}: generating x{a.count}…", file=sys.stderr, flush=True)
        t0 = time.time()
        r = run_flow(["image", "-p", prompt, "--model", a.model, "--aspect", a.aspect, "--count", str(a.count),
                      "--download", a.quality, "--out", str(out), "--name", name, "--timeout", str(a.timeout_min)],
                     timeout_s=(a.timeout_min + 10) * 60)
        if not r.get("results"):
            print(json.dumps({"n": n, "ok": False, "error": r.get("error"), "detail": {k: v for k, v in r.items() if k != "ok"}},
                             ensure_ascii=False), flush=True)
            print("[batch] stopping: fix the error above, then run the same command again to resume", file=sys.stderr)
            return 1
        files = [x["download"]["path"] for x in r["results"] if x.get("download")]
        failed = [x.get("message", "failed") for x in r["results"] if x.get("failed")]
        rec = {"n": n, "files": files, "failed": failed, "seconds": round(time.time() - t0, 1),
               "credits_spent": r.get("credits_spent")}
        state["done"][key] = rec
        state_file.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(rec, ensure_ascii=False), flush=True)
    print("[batch] all prompts in range are done", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
