"""Download one Flow tile with a time limit (google-flow's CLI `download` waits up to 15 min with no option).

Usage: python dl.py INDEX QUALITY OUT_DIR NAME [TIMEOUT_MIN] [--reload]   -> one JSON line (google-flow's result)
--reload refreshes the Flow project page first: a stuck upscale usually works again after a page refresh.
Called by batch.py; PinchTab must already be running (flow.ps1 starts it).
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vendor" / "google-flow" / "scripts"))
import flow as gf  # noqa: E402

args = [x for x in sys.argv[1:] if x != "--reload"]
idx, quality, out, name = int(args[0]), args[1], Path(args[2]), args[3]
timeout = float(args[4]) if len(args) > 4 else 3
f = gf.Flow(None).open()
if "--reload" in sys.argv:
    print("[dl] refreshing the Flow page", file=sys.stderr, flush=True)
    f.pt.nav(f.project or gf.FLOW_HOME)
    time.sleep(3)
    f.inject()
    f.wait_signed_in()
print(json.dumps(f.download(idx, quality, out, name, timeout_min=timeout), ensure_ascii=False))
