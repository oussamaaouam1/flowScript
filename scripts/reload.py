"""Refresh the Flow project page in the automation browser (used after Flow reports unusual activity).

Usage: python reload.py   -> one JSON line {"ok": true, "signed_in": ...}
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vendor" / "google-flow" / "scripts"))
import flow as gf  # noqa: E402

f = gf.Flow(None).open()
f.pt.nav(f.project or gf.FLOW_HOME)
time.sleep(4)
f.inject()
f.wait_signed_in()
print(json.dumps({"ok": True, "signed_in": bool(f.account().get("signedIn"))}))
