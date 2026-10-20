#!/usr/bin/env python3
"""Find which Wi-Fi channel the drone's AP is on by hopping channels and
listening for any 802.11 frame from the drone's BSSID.  Prints just the channel
number on stdout for watch_bebop.sh / wifi_attack.sh.  Needs sudo + the
interface already in monitor mode."""
import subprocess
import sys
from scapy.all import sniff, Dot11

DRONE = "a0:14:3d:a6:f1:d5"
IFACE = sys.argv[1] if len(sys.argv) > 1 else "wlx00c0cabe245c"

# 2.4 GHz first (Bebop defaults there), then common non-DFS 5 GHz channels.
CHANNELS = list(range(1, 14)) + [36, 40, 44, 48, 149, 153, 157, 161, 165]
DWELL = 0.5  # seconds to listen per channel


def set_channel(ch):
    # Fails harmlessly on 5 GHz channels the regulatory domain disallows.
    return subprocess.run(
        ["iw", "dev", IFACE, "set", "channel", str(ch)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


for ch in CHANNELS:
    if not set_channel(ch):
        continue
    hit = {"found": False}

    def seen(p):
        if not p.haslayer(Dot11):
            return
        d = p[Dot11]
        for a in (getattr(d, "addr2", None), getattr(d, "addr3", None)):
            if a and a.lower() == DRONE:
                hit["found"] = True
                return

    sys.stderr.write("[chan] probing ch %d...\n" % ch)
    sniff(iface=IFACE, prn=seen, store=False, timeout=DWELL,
          stop_filter=lambda _p: hit["found"])
    if hit["found"]:
        sys.stderr.write("[chan] drone is on channel %d\n" % ch)
        print(ch)
        sys.exit(0)

sys.stderr.write("[chan] drone not found on any scanned channel\n")
sys.exit(1)
