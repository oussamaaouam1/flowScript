"""Run a prompts file through Google Flow, one prompt at a time, keeping only the best takes.

Per prompt:
  gen   generate COUNT takes (default 3), wait until Flow has finished them, download small 1K previews to a temp
        folder and build one labelled contact sheet. Nothing is written to the output folder.
  keep  upscale only the chosen takes (default 2K) into the output folder as NN_a.jpg, NN_b.jpg; previews deleted.
  run   gen -> auto-pick with a cheap vision model (Antigravity `agy`, Gemini Flash Low) -> keep, for every prompt
        in --from..--to that is not done yet. Unattended; stops (leaving the prompt pending) if the pick fails.

Usage:
  python batch.py PROMPTS.txt --list
  python batch.py PROMPTS.txt --out DIR run   [--set 1] [--from 14] [--to 17]
  python batch.py PROMPTS.txt --out DIR gen   [--set 1] [--n 10] [--adopt]
  python batch.py PROMPTS.txt --out DIR keep 1,3
  python batch.py PROMPTS.txt --out DIR status

Common options: --offset 0 --count 3 --keep 2 --quality 2k --model nano --aspect 16:9 --picker-model gemini-3.8-flash-low
`gen` without --n takes the first prompt of the set that is not done. --adopt uses the newest COUNT tiles already in
Flow instead of generating (a prompt that was generated but not downloaded). Takes are numbered 1..COUNT in Flow's
tile order (newest first), as on the contact sheet. Progress lives in DIR/_flowscript_state.json.

Prompts file: lines starting with "Prompt N:"; other lines are ignored. When the numbering restarts at 1, a new set
begins. Every command prints JSON lines on stdout.
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


PICKER_FALLBACK = ["gemini-3.8-flash-high", "claude-sonnet-4-6"]   # tried in order when the cheap picker fails
UPSCALE_TIMEOUT_MIN = 2     # a Flow upscale normally takes ~15 s; one that hangs longer is retried after a page refresh
UPSCALE_ATTEMPTS = 3


def download_once(index: int, quality: str, out: Path, name: str, timeout_min: float, reload: bool = False) -> dict:
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    env.setdefault("PINCHTAB_CONFIG", str(Path(os.environ.get("APPDATA", "")) / "pinchtab" / "config.json"))
    try:
        p = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "dl.py"), str(index), quality, str(out),
                            name, str(timeout_min), *(["--reload"] if reload else [])], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=env, timeout=timeout_min * 60 + 120)
        return json.loads(p.stdout.strip().splitlines()[-1])
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"download helper failed: {e}"}


def robust_download(attempt, quality: str) -> dict:
    """attempt(quality, timeout_min, reload) -> google-flow download dict. A hung upscale is retried after refreshing
    the Flow page (that usually unsticks it). After UPSCALE_ATTEMPTS failures it gives up and the run stops with the
    reason: it never saves a lower quality instead."""
    last = {}
    for i in range(UPSCALE_ATTEMPTS):
        last = attempt(quality, UPSCALE_TIMEOUT_MIN, i > 0)
        if last.get("path"):
            return last
        print(f"[batch] {quality} download attempt {i + 1}/{UPSCALE_ATTEMPTS} failed: {str(last.get('error'))[:120]}"
              + ("; refreshing the Flow page and retrying" if i + 1 < UPSCALE_ATTEMPTS else ""), file=sys.stderr, flush=True)
    return last


PAUSE_FILE = Path.home() / ".config" / "google-flow" / "flowscript_paused.json"
PAUSE_HOURS = 24
DETECTION_RE = re.compile(r"unusual activity|automated|suspicious|verify (that )?you|captcha", re.I)


def paused() -> str | None:
    """Safety stop: after Flow reported unusual activity, refuse to generate for PAUSE_HOURS (or until --force-resume)."""
    try:
        d = json.loads(PAUSE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    left = d.get("until", 0) - time.time()
    if left <= 0:
        return None
    return f"paused for {left / 3600:.1f} more h: Flow reported \"{d.get('message', '')[:120]}\" on {d.get('at')}"


def pause(message: str):
    PAUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PAUSE_FILE.write_text(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M"), "until": time.time() + PAUSE_HOURS * 3600,
                                      "message": message}), encoding="utf-8")


def emit(obj: dict) -> dict:
    print(json.dumps(obj, ensure_ascii=False), flush=True)
    return obj


class Job:
    def __init__(self, a, prompts: dict[int, str]):
        self.a = a
        self.prompts = prompts
        self.out = Path(a.out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.state_file = self.out / "_flowscript_state.json"
        self.state = json.loads(self.state_file.read_text(encoding="utf-8")) if self.state_file.exists() else {}
        self.state.setdefault("done", {})

    def save(self):
        self.state_file.write_text(json.dumps(self.state, indent=1, ensure_ascii=False), encoding="utf-8")

    def key(self, n):
        return f"{self.a.set}:{n}"

    def nn(self, n) -> str:
        """File number of prompt n: n + --offset (e.g. --offset 17 names set 2's prompt 1 as 18), zero-padded to
        --pad digits (default 2: 09_a; --pad 1: 9_a)."""
        return f"{n + self.a.offset:0{self.a.pad}d}"

    def pnn(self, n) -> str:
        """Preview/sheet name (always 2 digits, as pick.ps1 expects)."""
        return f"{n + self.a.offset:02d}"

    def already_saved(self, n) -> bool:
        """True when the scene is done here or its NN_a file already exists (e.g. the user made it by hand)."""
        return self.key(n) in self.state["done"] or any(self.out.glob(f"{self.nn(n)}_a.*"))

    # -- gen ------------------------------------------------------------------------------------
    def gen(self, n: int | None, adopt: bool) -> dict:
        a = self.a
        if (why := paused()) and not a.force_resume:
            return {"ok": False, "error": why, "hint": "let the account rest; --force-resume overrides (not recommended)"}
        if self.state.get("pending"):
            p = self.state["pending"]
            return {"ok": False, "error": f"prompt {p['n']} is waiting for `keep` (sheet: {p['sheet']})", "pending": p}
        if n is None:
            n = next((k for k in self.prompts if not self.already_saved(k)), None)
            if n is None:
                return {"ok": True, "message": f"all prompts of set {a.set} are done"}
        if n not in self.prompts:
            return {"ok": False, "error": f"prompt {n} is not in set {a.set}"}
        nn, pnn = self.nn(n), self.pnn(n)
        prev = PREVIEW_ROOT / f"set{a.set}_{pnn}"
        shutil.rmtree(prev, ignore_errors=True)
        prev.mkdir(parents=True)
        t0 = time.time()
        if adopt:
            tiles = flow(["list", "image", "--limit", str(a.count)]).get("tiles") or []
            if len(tiles) < a.count or any(t.get("failed") or t.get("progress") not in (None, 100) for t in tiles):
                return {"ok": False, "error": "the newest tiles are not finished images", "tiles": tiles}
            for t in tiles:
                d = flow(["download", str(t["i"]), "--quality", "original", "--out", str(prev), "--name", f"{pnn}_{t['i'] + 1}"])
                if d.get("ok") is False:
                    return {"ok": False, "error": f"preview download failed: {d.get('error')}"}
            spent = 0
        else:
            print(f"[batch] prompt {n}: generating x{a.count}…", file=sys.stderr, flush=True)
            r = flow(["image", "-p", self.prompts[n], "--model", a.model, "--aspect", a.aspect, "--count", str(a.count),
                      "--download", "original", "--out", str(prev), "--name", pnn, "--timeout", str(a.timeout_min)],
                     timeout_s=(a.timeout_min + 10) * 60)
            if not r.get("results"):
                return {"ok": False, "n": n, "error": r.get("error"), "flow_stderr": (r.get("stderr") or "")[-600:] or None,
                        "hint": "run `flow.ps1 list image --limit 6` before retrying; use gen --adopt if the tiles exist"}
            tiles = [{"i": x["index"], "title": x["title"], "failed": x["failed"], "message": x.get("message")}
                     for x in r["results"]]
            hit = next((t["message"] for t in tiles if t.get("message") and DETECTION_RE.search(t["message"])), None)
            if hit:
                pause(hit)
                return {"ok": False, "n": n, "error": "Flow reported unusual activity: automation paused for "
                        f"{PAUSE_HOURS} h to protect the account", "flow_message": hit[:300]}
            spent = r.get("credits_spent")
        takes = sorted(int(m.group(1)) for f in prev.iterdir() if (m := re.match(rf"^{pnn}_(\d+)\.", f.name)))
        if not takes:
            return {"ok": False, "n": n, "error": "no take was downloaded", "tiles": tiles}
        sheet = ps(PICK_PS1, ["-Out", str(prev), "-N", str(int(pnn)), "-Sheet"], 120).stdout.strip().splitlines()
        self.state["pending"] = {"set": a.set, "n": n, "nn": nn, "takes": takes, "tiles": tiles, "preview": str(prev),
                                 "sheet": sheet[-1] if sheet else None}
        self.save()
        return {"ok": True, "n": n, "takes": takes, "sheet": self.state["pending"]["sheet"],
                "failed": [t for t in tiles if t.get("failed")], "credits_spent": spent,
                "seconds": round(time.time() - t0, 1), "next": f"keep <{a.keep} of {takes}>"}

    # -- keep -----------------------------------------------------------------------------------
    def keep(self, takes_arg: str | None, reason: str | None = None) -> dict:
        p = self.state.get("pending")
        if not p:
            return {"ok": False, "error": "nothing is waiting: run gen first"}
        try:
            chosen = [int(x) for x in (takes_arg or "").split(",") if x.strip()]
        except ValueError:
            chosen = []
        if not chosen or len(set(chosen)) != len(chosen) or any(c not in p["takes"] for c in chosen):
            return {"ok": False, "error": f"choose distinct takes from {p['takes']}, e.g. keep 1,3"}
        nn = p.get("nn") or self.nn(p["n"])
        clash = [f.name for f in self.out.glob(f"{nn}_[a-j].*")]
        if clash:
            return {"ok": False, "error": f"{', '.join(clash)} already exist in the output folder; not overwriting"}
        latest = flow(["list", "image", "--limit", str(max(p["takes"]))]).get("tiles") or []
        then = [t["title"] for t in sorted(p["tiles"], key=lambda t: t["i"])]
        if [t["title"] for t in latest][:len(then)] != then:
            return {"ok": False, "error": "the Flow grid changed since gen (new tiles?), so take numbers no longer match; "
                    "download by hand with `flow.ps1 download <index>`", "now": [t["title"] for t in latest], "then": then}
        saved = []
        for k, take in enumerate(chosen):
            d = robust_download(lambda q, t, r, take=take, k=k: download_once(take - 1, q, self.out, f"{nn}_{LETTERS[k]}", t, r),
                                self.a.quality)
            if not d.get("path"):
                return {"ok": False, "error": f"download of take {take} failed", "detail": d, "saved": saved}
            title = sorted(p["tiles"], key=lambda t: t["i"])[take - 1]["title"]
            saved.append({"take": take, "path": d["path"], "quality": d.get("quality"), "title": title,
                          **({"fallback": d["fallback_reason"]} if d.get("fallback") else {})})
        low = [{"file": Path(x["path"]).name, "title": x["title"]} for x in saved
               if "upscal" not in str(x.get("quality", "")).lower()]      # saved below 2K: upscale later
        self.state["done"][f"{p['set']}:{p['n']}"] = {"kept": chosen, "files": [s["path"] for s in saved],
                                                       **({"reason": reason} if reason else {}),
                                                       **({"needs_2k": low} if low else {})}
        shutil.rmtree(p["preview"], ignore_errors=True)
        self.state.pop("pending")
        self.save()
        return {"ok": True, "n": p["n"], "saved": saved}

    # -- run ------------------------------------------------------------------------------------
    def run(self) -> dict:
        a = self.a
        todo = [n for n in self.prompts if (a.start is None or n >= a.start) and (a.end is None or n <= a.end)
                and not self.already_saved(n)]
        done = []
        p = self.state.get("pending")
        if p and not p.get("keys"):          # a scene left between gen and keep (stopped run, failed upscale)
            print(f"[batch] finishing pending prompt {p['n']} first", file=sys.stderr, flush=True)
            takes, why = autopick(p["sheet"], self.prompts[p["n"]], a.keep, a.picker_model, p["takes"])
            if not takes:
                return emit({"ok": False, "n": p["n"], "stage": "pick", "error": why, "sheet": p["sheet"]})
            k = self.keep(",".join(map(str, takes)), reason=why)
            if not k.get("ok"):
                return emit({"stage": "keep", **k})
            emit({"ok": True, "n": p["n"], "kept": takes, "reason": why, "files": k["saved"]})
            todo = [n for n in todo if n != p["n"]]
        for n in todo:
            g = self.gen(n, adopt=False)
            if not g.get("ok"):
                return emit({"stage": "gen", **g})
            takes, why = autopick(g["sheet"], self.prompts[n], a.keep, a.picker_model, g["takes"])
            if not takes or len(set(takes)) != a.keep or any(t not in g["takes"] for t in takes):
                return emit({"ok": False, "n": n, "stage": "pick", "error": why, "sheet": g["sheet"],
                             "hint": "look at the sheet, then `keep A,B`, then `run` again to continue"})
            k = self.keep(",".join(map(str, takes)), reason=why)
            if not k.get("ok"):
                return emit({"stage": "keep", **k})
            done.append(n)
            emit({"ok": True, "n": n, "kept": takes, "reason": why, "gen_seconds": g.get("seconds"),
                  **({"fallback": [x["fallback"] for x in k["saved"] if x.get("fallback")]}
                     if any(x.get("fallback") for x in k["saved"]) else {})})
        return emit({"ok": True, "done": done, "message": "range finished"})


def autopick(sheet: str, prompt: str, keep: int, model: str, takes: list[int] | None = None) -> tuple[list[int] | None, str]:
    """Pick with the cheap model; if its answer is missing or invalid, retry with better models (PICKER_FALLBACK)."""
    why = ""
    for m in [model] + [x for x in PICKER_FALLBACK if x != model]:
        nums, why = _autopick_once(sheet, prompt, keep, m)
        valid = nums and len(set(nums)) == keep and (takes is None or all(n in takes for n in nums))
        if valid:
            return nums, why if m == model else f"[{m}] {why}"
        print(f"[batch] picker {m} gave no valid answer ({why[:100]}); trying a better model", file=sys.stderr, flush=True)
    return None, why


def _autopick_once(sheet: str, prompt: str, keep: int, model: str) -> tuple[list[int] | None, str]:
    """Ask a cheap vision model (Antigravity `agy`) which takes to keep. It may only read files: shell commands and
    writes are denied, and it runs in the contact sheet's folder."""
    agy = shutil.which("agy")
    if not agy:
        return None, "agy (Antigravity CLI) not found on PATH"
    folder, name = os.path.split(sheet)
    ask = (f"Use the view_file tool to open the image {name} (do not run commands). It shows candidate takes labelled "
           f"1, 2, 3... left to right for this storyboard prompt:\n\n{prompt}\n\nChoose the {keep} takes that best "
           "match the prompt (right characters and clothing, action, shot and angle, props) with no visual defects "
           "(hands, faces, extra limbs, text, watermark). Answer with exactly one line: KEEP a,b - short reason")
    settings = json.dumps({"permissions": {"allow": ["read(*)"], "deny": ["command(*)", "write(*)"]}})
    try:
        p = subprocess.run([agy, f"-p={ask}", "--model", model, "--settings", settings, "--output-format", "json",
                            "--print-timeout", "180s"], cwd=folder, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=240)
        resp = json.loads(p.stdout.strip().splitlines()[-1]).get("response", "")
    except Exception as e:  # noqa: BLE001 - any failure means: fall back to a manual pick
        return None, f"agy failed: {e}"
    m = re.search(r"KEEP\s*([\d,\s]+)", resp, re.I)
    if not m:
        return None, f"no KEEP line in: {resp[:200]}"
    nums = [int(x) for x in re.findall(r"\d+", m.group(1))][:keep]
    return nums, resp[m.end():].strip(" -:\n")[:300]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompts")
    ap.add_argument("--out", help="output folder")
    ap.add_argument("--list", action="store_true", help="show the sets and prompt counts")
    ap.add_argument("action", nargs="?", choices=["gen", "keep", "run", "status"])
    ap.add_argument("takes", nargs="?", help="for keep: the take numbers to keep, e.g. 1,3")
    ap.add_argument("--set", type=int, default=1, help="which prompt set (1 = first)")
    ap.add_argument("--n", type=int, help="gen: prompt number (default: the next one not done)")
    ap.add_argument("--from", dest="start", type=int, help="run: first prompt")
    ap.add_argument("--to", dest="end", type=int, help="run: last prompt")
    ap.add_argument("--adopt", action="store_true", help="gen: use the newest tiles already in Flow")
    ap.add_argument("--pad", type=int, default=2, help="digits in file names: 2 -> 09_a (default), 1 -> 9_a")
    ap.add_argument("--offset", type=int, default=0, help="add to the prompt number for file names (e.g. 17: set 2 prompt 1 -> 18_a)")
    ap.add_argument("--count", type=int, default=3, help="takes per prompt")
    ap.add_argument("--keep", type=int, default=2, help="run: takes kept per prompt")
    ap.add_argument("--quality", default="2k", help="2k | 1080p | original | best")
    ap.add_argument("--model", default="nano")
    ap.add_argument("--aspect", default="16:9")
    ap.add_argument("--picker-model", default="gemini-3.8-flash-low", help="agy model used by run to pick takes")
    ap.add_argument("--timeout-min", type=int, default=15)
    ap.add_argument("--force-resume", action="store_true", help="ignore the 24 h safety pause (not recommended)")
    a = ap.parse_args()

    sets = parse_sets(Path(a.prompts).read_text(encoding="utf-8-sig"))
    if a.list or not a.action:
        emit({"sets": [{"set": i + 1, "prompts": len(s), "first": s[0][1][:80]} for i, s in enumerate(sets)]})
        return 0
    if not a.out:
        emit({"ok": False, "error": "--out is required"})
        return 1
    if not 1 <= a.set <= len(sets):
        emit({"ok": False, "error": f"set {a.set} not found; the file has {len(sets)} set(s)"})
        return 1
    job = Job(a, dict(sets[a.set - 1]))
    if a.action == "status":
        done = [n for n in job.prompts if job.already_saved(n)]
        needs = [x for v in job.state["done"].values() for x in v.get("needs_2k", [])]
        r = emit({"ok": True, "set": a.set, "done": done, "todo": [n for n in job.prompts if n not in done],
                  "pending": job.state.get("pending"), "needs_2k": needs})
    elif a.action == "gen":
        r = emit(job.gen(a.n, a.adopt))
    elif a.action == "keep":
        r = emit(job.keep(a.takes))
    else:
        r = job.run()
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
