"""Faster unattended run: overlap Flow's rendering with picking and upscaling — still one generation at a time.

    send prompt N  ->  while N renders: pick + upscale scene N-1  ->  wait until N is finished  ->  N's previews
    ->  short random pause  ->  send prompt N+1 ...

Safety (to stay a normal, light user of Flow):
  * never more than one generation in flight: prompt N+1 is only sent after N has finished rendering;
  * one process, one action at a time on the page (no parallel clicks);
  * a random pause between prompts (--pause 8-20 seconds by default);
  * a daily cap on prompts (--max-per-day, default 60), counted across runs.

Same files and state as batch.py (NN_a.jpg / NN_b.jpg, OUT/_flowscript_state.json); scenes already saved are skipped.
Run through the wrapper so PinchTab is set up:  .\\flow.ps1 -Pipeline PROMPTS.txt --out DIR [--set 2 --offset 17]
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import time
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "vendor" / "google-flow" / "scripts"))
import batch  # noqa: E402  (this repo)
import flow as gf  # noqa: E402  (google-flow, fetched by setup.ps1)

LETTERS = batch.LETTERS


def log(*a):
    print("[pipeline]", *a, file=sys.stderr, flush=True)


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)
    return obj


class Guarded(Exception):
    pass


def guarded(fn, *args, **kw):
    """google-flow's helpers call die() (sys.exit) on errors; turn that into an exception we can report."""
    try:
        return fn(*args, **kw)
    except SystemExit as e:
        raise Guarded(f"google-flow stopped: exit {e.code}") from None


class Pipeline:
    def __init__(self, a, prompts):
        self.a = a
        self.job = batch.Job(a, prompts)
        self.f = gf.Flow(None).open()
        self.cfg = {"mode": "Image", "model": gf.norm_model(a.model), "aspect": a.aspect, "count": gf.norm_count(a.count)}
        self.day_file = gf.CONF_DIR / "flowscript_daily.json"

    # -- daily cap ------------------------------------------------------------------------------
    def used_today(self) -> int:
        d = gf.load_json(self.day_file, {})
        return d.get("count", 0) if d.get("day") == date.today().isoformat() else 0

    def count_one(self):
        self.day_file.parent.mkdir(parents=True, exist_ok=True)
        self.day_file.write_text(json.dumps({"day": date.today().isoformat(), "count": self.used_today() + 1}))

    # -- steps ----------------------------------------------------------------------------------
    def submit(self, n: int) -> set:
        f = self.f
        f.call("clearPromptBar")
        guarded(gf.configure, f, self.cfg)
        p = f.call("setPrompt", self.job.prompts[n])
        if not p.get("ok"):
            raise Guarded(f"could not type prompt {n}: {p}")
        before = f.keys()
        if not guarded(f.submit, before):
            raise Guarded(f"Flow did not accept prompt {n} (nothing submitted)")
        self.count_one()
        return before

    def locate(self, keys: list) -> list[int] | None:
        """Current grid indices of the tiles with these identities (new tiles push old ones down)."""
        ts = self.f.tiles()
        idx = {tuple(gf.Flow.tkey(t)): t["i"] for t in ts}
        found = [idx.get(tuple(k)) for k in keys]
        return None if any(i is None for i in found) else found

    def previews(self, n: int, tiles: list) -> dict:
        nn = self.job.nn(n)
        prev = batch.PREVIEW_ROOT / f"set{self.a.set}_{nn}"
        shutil.rmtree(prev, ignore_errors=True)
        prev.mkdir(parents=True)
        tiles = sorted(tiles, key=lambda t: t["i"])
        for k, t in enumerate(tiles, start=1):
            if not t.get("failed"):
                guarded(self.f.download, t["i"], "original", prev, f"{nn}_{k}")
        takes = [k for k, t in enumerate(tiles, start=1) if not t.get("failed")]
        sheet = batch.ps(batch.PICK_PS1, ["-Out", str(prev), "-N", str(int(nn)), "-Sheet"], 120).stdout.strip().splitlines()
        pending = {"set": self.a.set, "n": n, "nn": nn, "takes": takes, "preview": str(prev),
                   "sheet": sheet[-1] if sheet else None, "keys": [list(gf.Flow.tkey(t)) for t in tiles],
                   "tiles": [{"i": t["i"], "title": t["title"], "failed": t.get("failed")} for t in tiles]}
        self.job.state["pending"] = pending
        self.job.state["last_titles"] = [t["title"] for t in tiles]
        self.job.save()
        return pending

    def reload(self):
        """Refresh the Flow project page: a stuck upscale usually works again afterwards."""
        log("refreshing the Flow page")
        self.f.pt.nav(self.f.project or gf.FLOW_HOME)
        time.sleep(3)
        self.f.inject()
        self.f.wait_signed_in()

    def download(self, p: dict, take: int, quality: str, name: str, timeout_min: float, reload: bool) -> dict:
        """Download take `take` (1-based) of scene p; after a refresh the grid is rebuilt, so find the tile again."""
        if reload:
            self.reload()
        idx = self.locate(p["keys"])
        if idx is None:
            return {"ok": False, "error": f"scene {p['nn']}'s tiles are no longer in the Flow grid"}
        return guarded(self.f.download, idx[take - 1], quality, self.job.out, name, timeout_min=timeout_min)

    def finish(self, p: dict) -> dict:
        """Pick the best takes of a previewed scene and upscale only those."""
        nn = p["nn"]
        clash = [x.name for x in self.job.out.glob(f"{nn}_[a-j].*")]
        if clash:
            raise Guarded(f"{', '.join(clash)} already exist; not overwriting")
        takes, why = batch.autopick(p["sheet"], self.job.prompts[p["n"]], self.a.keep, self.a.picker_model, p["takes"])
        if not takes or len(set(takes)) != self.a.keep or any(t not in p["takes"] for t in takes):
            raise Guarded(f"pick failed for scene {nn}: {why} (sheet: {p['sheet']}; choose with batch.py keep A,B)")
        saved = []
        for k, take in enumerate(takes):
            name = f"{nn}_{LETTERS[k]}"
            d = batch.robust_download(lambda q, t, r, take=take, name=name: self.download(p, take, q, name, t, r),
                                      self.a.quality)
            if not d.get("path"):
                raise Guarded(f"download of scene {nn} take {take} failed: {d}")
            if d.get("fallback"):
                log(f"scene {nn} take {take}: {d['fallback_reason']} -> saved the 1K original")
            saved.append(d["path"])
        self.job.state["done"][f"{p['set']}:{p['n']}"] = {"kept": takes, "files": saved, "reason": why}
        self.job.state.pop("pending", None)
        shutil.rmtree(p["preview"], ignore_errors=True)
        self.job.save()
        return emit({"ok": True, "scene": nn, "kept": takes, "reason": why})

    # -- main loop ------------------------------------------------------------------------------
    def run(self) -> int:
        a = self.a
        todo = [n for n in self.job.prompts if (a.start is None or n >= a.start) and (a.end is None or n <= a.end)
                and not self.job.already_saved(n)]
        pending = self.job.state.get("pending")
        if pending and pending.get("keys"):
            todo = [n for n in todo if n != pending["n"]]
        elif pending:
            raise Guarded(f"scene {pending['nn'] if 'nn' in pending else pending['n']} is pending from batch.py; "
                          "finish it with `batch.py keep A,B` first")
        for i, n in enumerate(todo):
            if self.used_today() >= a.max_per_day:
                log(f"daily cap of {a.max_per_day} prompts reached; stopping (run again tomorrow to continue)")
                break
            if i:
                pause = random.uniform(*a.pause)
                log(f"pause {pause:.0f}s")
                time.sleep(pause)
            log(f"prompt {n} -> scene {self.job.nn(n)}: sending")
            t0 = time.time()
            before = self.submit(n)
            if pending:                       # overlap: finish the previous scene while this one renders
                self.finish(pending)
                pending = None
            new = guarded(self.f.wait_tiles, before, a.count, a.timeout_min)
            log(f"scene {self.job.nn(n)} rendered in {time.time() - t0:.0f}s")
            pending = self.previews(n, new)
        if pending:
            self.finish(pending)
        emit({"ok": True, "message": "range finished", "used_today": self.used_today()})
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompts")
    ap.add_argument("--out", required=True)
    ap.add_argument("--set", type=int, default=1)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--from", dest="start", type=int)
    ap.add_argument("--to", dest="end", type=int)
    ap.add_argument("--count", type=int, default=3)
    ap.add_argument("--keep", type=int, default=2)
    ap.add_argument("--quality", default="2k")
    ap.add_argument("--model", default="nano")
    ap.add_argument("--aspect", default="16:9")
    ap.add_argument("--picker-model", default="gemini-3.8-flash-low")
    ap.add_argument("--timeout-min", type=int, default=15)
    ap.add_argument("--pause", type=float, nargs=2, default=[8, 20], metavar=("MIN", "MAX"), help="seconds between prompts")
    ap.add_argument("--max-per-day", type=int, default=60, help="prompts per day, counted across runs")
    a = ap.parse_args()
    sets = batch.parse_sets(Path(a.prompts).read_text(encoding="utf-8-sig"))
    if not 1 <= a.set <= len(sets):
        emit({"ok": False, "error": f"set {a.set} not found"})
        return 1
    try:
        return Pipeline(a, dict(sets[a.set - 1])).run()
    except Guarded as e:
        emit({"ok": False, "error": str(e), "hint": "run the same command again to resume"})
        return 1


if __name__ == "__main__":
    sys.exit(main())
