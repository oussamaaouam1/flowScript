# flowScript

Batch image generation in **Google Flow** (Nano Banana) on Windows, driven by an AI agent (Claude Code, Antigravity /
Gemini, …) or by hand.

For each prompt in a text file it generates 3 images, waits until they are finished, downloads them upscaled to 2K into a
folder, and then the agent (or you) keeps the best 2 of each 3. It runs in a separate automation browser (PinchTab), so
your own Chrome, mouse and keyboard stay free.

Built on the [`google-flow`](https://github.com/YusufLisawi/bb-plugins/tree/main/skills/google-flow) skill by
YusufLisawi. Its code is **not** copied into this repo: `setup.ps1` downloads it from the original repo at a pinned commit.

## Setup (once)

```powershell
git clone https://github.com/oussamaaouam1/flowScript.git $HOME\Developer\flowScript
cd $HOME\Developer\flowScript
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

`setup.ps1` installs Python 3.12 and PinchTab if missing, fetches google-flow, and — after backing up the PinchTab config —
enables the two PinchTab permissions google-flow needs (`allowEvaluate`, `allowCookies`) for the Google/Flow domains only.

Then sign the automation browser in to Google once:

```powershell
.\flow.ps1 login                                  # open the printed local URL and sign in yourself
# or
.\flow.ps1 setup --cookies C:\path\cookies.json   # Cookie-Editor JSON export from a browser signed in to Flow
.\flow.ps1 setup --project https://flow.google.com/project/<id>   # the Flow project to use
.\flow.ps1 status
```

## Use

```powershell
python scripts\batch.py prompts.txt --list                       # sets and prompt counts
python scripts\batch.py prompts.txt --out "D:\YT\story\1" --set 1  # x3, 2K, one prompt at a time, resumable
.\scripts\pick.ps1 -Out "D:\YT\story\1" -N 3 -Sheet               # contact sheet of scene 3's takes
.\scripts\pick.ps1 -Out "D:\YT\story\1" -N 3 -Keep 1,2            # keep 03_1, 03_2 as 03_a, 03_b
```

Prompts file: lines starting with `Prompt N:`; other lines are ignored. When the numbering restarts at 1, a new set starts.

## Using it from an agent

[`SKILL.md`](SKILL.md) is the agent skill. For Claude Code, copy or link this folder to `~/.claude/skills/flowscript`.
Other agents (Antigravity / Gemini) can be told to read `SKILL.md` first. The repetitive part (run `batch.py`, look at one
contact sheet per scene, call `pick.ps1`) is simple enough for a fast, cheap model.

## Never committed

Cookies, sign-in data, `vendor/`, generated images and per-job folders are in `.gitignore`.
