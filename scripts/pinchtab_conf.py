"""Turn on the PinchTab permissions google-flow needs, for the Google/Flow domains only.

Usage: python pinchtab_conf.py <path to PinchTab config.json>
Called by setup.ps1 after it has made a backup of the file.
"""
import json
import sys

NEED_DOMAINS = ["flow.google.com", "*.flow.google.com", "google.com", "*.google.com", "labs.google", "*.labs.google",
                "*.gstatic.com", "*.googleusercontent.com", "*.googleapis.com"]

path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    conf = json.load(f)
sec = conf.setdefault("security", {})
changed = []
for key in ("allowEvaluate", "allowCookies"):
    if not sec.get(key):
        sec[key] = True
        changed.append(key)
domains = sec.setdefault("allowedDomains", [])
for d in NEED_DOMAINS:
    if d not in domains:
        domains.append(d)
        changed.append(d)
if changed:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(conf, f, indent=2)
print("PinchTab config:", "updated " + ", ".join(changed) if changed else "already set")
