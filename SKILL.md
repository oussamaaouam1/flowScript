---
name: flowscript
description: Batch-generate story images in Google Flow (Nano Banana) on Windows from a prompts text file — x3 per prompt, one prompt at a time — then save only the best 2 of each 3, upscaled to 2K, into a folder. Use when the user gives a prompts file ("Prompt 1: ...", "Prompt 2: ...") and wants Flow images generated, picked and downloaded, or wants to resume such a batch.
---

# flowScript — batch Flow images from a prompts file

Repo: `~/Developer/flowScript` (this file's folder). Windows, PowerShell. It wraps the `google-flow` skill's `flow.py`
(in `vendor/google-flow`, fetched by `setup.ps1`), which drives Flow in a separate PinchTab browser with trusted clicks —
the user's own Chrome, mouse and keyboard are never touched.

## Preflight

```powershell
cd ~/Developer/flowScript
.\flow.ps1 status            # {"ok": true, "account": {"signedIn": true, "credits": ...}, "project_url": ...}
```
- `vendor\google-flow` missing or PinchTab not set up → the user runs `.\setup.ps1` (it changes PinchTab security
  settings, so let the user run it; do not edit the PinchTab config yourself).
- Not signed in → `.\flow.ps1 login` (prints a 127.0.0.1:8790 URL; the user opens it and signs in there; the command
  exits once signed in) or `.\flow.ps1 setup --cookies <export.json>`. Never type or ask for passwords; never print cookies.
- Tell the user which project is used (`project_url` in status). Change it with
  `.\flow.ps1 setup --project https://flow.google.com/project/<id>` or `.\flow.ps1 new-project --save`.

## The job: unattended (default)

```powershell
python scripts\batch.py PROMPTS.txt --list                                   # sets and prompt counts
python scripts\batch.py PROMPTS.txt --out "C:\...\1" run --from 14 --to 17   # gen -> auto-pick -> keep, per prompt
```
Run it in the background. Per prompt it generates x3, a cheap vision model picks the best 2 from a small contact sheet
(Antigravity `agy`, `--picker-model gemini-3.8-flash-low`, ~7 s; it may only read files), and only those 2 are upscaled
to 2K as `NN_a.jpg`, `NN_b.jpg`. One JSON line per prompt with the kept takes and the picker's reason; relay them.
Scenes whose `NN_a` already exists in the folder (made by hand) are skipped, and nothing is ever overwritten. If the
pick fails, `run` stops with the prompt pending: look at the sheet yourself, `keep A,B`, then `run` again.

## The job: manual, per prompt (gen → look → keep)

Only the chosen takes are upscaled and saved; the output folder never gets the rejected take.

```powershell
python scripts\batch.py PROMPTS.txt --out "C:\...\1" status      # done / todo / pending
python scripts\batch.py PROMPTS.txt --out "C:\...\1" gen [--n 9] # x3, waits, 1K previews in %TEMP% + one contact sheet
python scripts\batch.py PROMPTS.txt --out "C:\...\1" keep 1,3    # upscale takes 1 and 3 to 2K -> 09_a.jpg, 09_b.jpg
```

1. `gen` (no `--n` = the next prompt not done) returns `{"sheet": "...\_sheets\09.jpg", "takes": [1,2,3]}`. The next
   prompt is only generated after `keep`, so prompts never overlap.
2. Read the sheet (one small image, takes labelled 1 2 3 left to right) and the prompt text. Judge: right characters and
   clothing, the requested shot/angle and composition, the key action and props, faces and hands without defects
   (extra fingers, merged limbs), no text or watermark, consistent look with earlier scenes.
3. `keep A,B` with the two best. Tell the user one line per scene: which two were kept and why the third was dropped.

Recovery: prompt generated but not downloaded (run stopped) → `gen --n N --adopt` uses the newest 3 tiles in Flow
without generating again. Defaults: Nano Banana 2.1, 16:9, x3, keep at 2K (`--quality` to change).

## Rules

- Images cost 0 credits on the user's plan, but report `credits_spent` from the JSON if it is not 0.
- Never re-run `gen` after an unclear error: `.\flow.ps1 list image --limit 6` first; if the tiles exist, `--adopt`.
- If Flow refuses a prompt (policy), report the message and skip it; don't rewrite story prompts without asking.
- Flow UI changed or a command fails strangely → `.\flow.ps1 shot --out $env:TEMP\flow.jpg`, read it, and see
  `vendor\google-flow\references\internals.md`.
