# flowScript

Batch image generation in **Google Flow** (Nano Banana) on Windows, driven by an AI agent (Claude Code, Antigravity / Gemini, …).

For each prompt in a text file it generates N images, waits for them to finish, downloads them upscaled (2K) into a folder,
and lets the agent (or you) keep the best ones.

Built on top of the [`google-flow`](https://github.com/YusufLisawi/bb-plugins/tree/main/skills/google-flow) skill by
YusufLisawi, which is **not** copied here: `setup.ps1` downloads it from its repo at a pinned commit.

Work in progress — see the commit history.
