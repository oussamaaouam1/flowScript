"""Download one Flow tile with a time limit (google-flow's CLI `download` waits up to 15 min with no option).

Usage: python dl.py INDEX QUALITY OUT_DIR NAME [TIMEOUT_MIN]   -> one JSON line (google-flow's download result)
Called by batch.py; PinchTab must already be running (flow.ps1 starts it).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vendor" / "google-flow" / "scripts"))
import flow as gf  # noqa: E402

idx, quality, out, name = int(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), sys.argv[4]
timeout = float(sys.argv[5]) if len(sys.argv) > 5 else 3
f = gf.Flow(None).open()
print(json.dumps(f.download(idx, quality, out, name, timeout_min=timeout), ensure_ascii=False))
