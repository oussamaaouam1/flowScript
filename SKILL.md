---
name: flowscript
description: Batch-generate story images in Google Flow (Nano Banana) on Windows from a prompts text file — x3 per prompt, one prompt at a time, upscaled 2K downloads into a folder — then keep the best 2 of each 3. Use when the user gives a prompts file ("Prompt 1: ...", "Prompt 2: ...") and wants Flow images generated, downloaded and picked, or wants to resume such a batch.
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
- Not signed in → `.\flow.ps1 login` (serves a live view of the automation browser at 127.0.0.1:8790; the user signs in
  there) or `.\flow.ps1 setup --cookies <Cookie-Editor export.json>`. Never type or ask for passwords; never print cookies.
- No project yet → `.\flow.ps1 new-project --save`, or `.\flow.ps1 setup --project https://flow.google.com/project/<id>`.

## The job

1. Look at the file: `python scripts\batch.py PROMPTS.txt --list` → sets and counts. Confirm with the user which set goes
   to which folder if it is not obvious.
2. Generate, one prompt at a time (the next prompt is only sent after the previous one finished and downloaded):
   ```powershell
   python scripts\batch.py PROMPTS.txt --out "C:\...\1" --set 1 [--from 4] [--to 17]
   ```
   Defaults: Nano Banana 2.1, 16:9, x3, 2K upscale. Output `NN_1.jpg NN_2.jpg NN_3.jpg` per prompt, one JSON line per
   prompt on stdout. Run it in the background for long sets; it resumes from `OUT\_flowscript_state.json` if stopped.
3. Pick the best 2 of 3 for each prompt:
   ```powershell
   .\scripts\pick.ps1 -Out "C:\...\1" -N 4 -Sheet      # -> OUT\_sheets\04.jpg (takes side by side, labelled 1 2 3)
   ```
   Read the sheet image (one small read, not three 2K files). Judge against the prompt: right characters and clothing,
   the requested camera angle and composition, faces and hands without defects (extra fingers, merged limbs), no text
   or watermark, consistent look with earlier scenes. Then:
   ```powershell
   .\scripts\pick.ps1 -Out "C:\...\1" -N 4 -Keep 2,3    # 04_2 -> 04_a, 04_3 -> 04_b, 04_1 -> OUT\_rejected\
   ```
   Tell the user one line per scene: which two were kept and why the third was dropped.

## Rules

- Images cost 0 credits on the user's plan, but always report `credits_spent` from the JSON if it is not 0.
- Never loop or re-run a prompt after an unclear error: `.\flow.ps1 list image --limit 6` first to see whether the
  tiles exist; `.\flow.ps1 download <index> --quality 2k --out DIR --name NN_1` recovers a missed download.
- If Flow refuses a prompt (policy), report the message and skip it; don't rewrite story prompts without asking.
- Flow UI changed or a command fails strangely → `.\flow.ps1 shot --out $env:TEMP\flow.jpg`, read it, and see
  `vendor\google-flow\references\internals.md`.
