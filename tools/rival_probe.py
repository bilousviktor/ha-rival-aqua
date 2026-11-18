#!/usr/bin/env python3
"""Read-only probe for a Rival Aqua controller (stdlib only).

    python3 rival_probe.py 192.168.5.200

Prints the controller's configuration and current levels without changing anything.
"""
import sys
import urllib.request

host = sys.argv[1] if len(sys.argv) > 1 else "192.168.5.200"
for path in ("/chnumb", "/curlevelrange", "/handmodestate", "/blockrange",
             "/curver", "/curip", "/namechannellist.js"):
    try:
        with urllib.request.urlopen(f"http://{host}{path}", timeout=5) as r:
            print(f"{path:22} {r.read().decode(errors='replace').strip()}")
    except Exception as e:  # noqa: BLE001
        print(f"{path:22} ERROR {e}")
