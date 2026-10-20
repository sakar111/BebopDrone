#!/usr/bin/env python3
"""Auto-detect the Bebop's AP with no hardcoded MAC. Channel-hop in monitor
mode and spot the drone by its Parrot MAC OUI on ANY frame (works even when
it's barely beaconing or its SSID is hidden). Prints "<bssid> <channel> <ssid>"
(ssid may be empty). Needs sudo + the interface already in monitor mode.

Picking the channel robustly (a very close, strong drone leaks frames onto
other channels, so first-hit-wins is unreliable):
  1. If we catch a beacon/probe-resp, read the channel straight from its DS
     Parameter Set element -- that's the AP's true channel no matter which
     channel we overheard it on. Authoritative, use it at once.
  2. Otherwise sweep every channel, count drone frames per channel, and pick
     the busiest -- the real channel has far more than any leakage.

Usage: find_drone.py <iface> [ssid_prefix]
"""
import subprocess
import sys
import time
from collections import defaultdict
from scapy.all import sniff, Dot11, Dot11Beacon, Dot11ProbeResp, Dot11Elt

IFACE = sys.argv[1] if len(sys.argv) > 1 else "wlx00c0cabe245c"
PREFIX = (sys.argv[2] if len(sys.argv) > 2 else "BebopDrone").lower()

PARROT_OUIS = ("a0:14:3d", "00:12:1c", "00:26:7e", "90:03:b7", "90:3a:e6")
CH_24 = list(range(1, 14))
CH_5 = [36, 40, 44, 48, 149, 153, 157, 161, 165]
DWELL = 0.5  # seconds per channel

state = {"bssid": None, "ssid": "", "beacon_ch": None}
counts = defaultdict(int)


def set_channel(ch):
    return subprocess.run(
        ["iw", "dev", IFACE, "set", "channel", str(ch)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def is_parrot(a):
    return bool(a) and a.lower()[:8] in PARROT_OUIS


def elt_find(p, eid):
    elt = p.getlayer(Dot11Elt)
    while elt is not None:
        if elt.ID == eid:
            return elt.info
        elt = elt.payload.getlayer(Dot11Elt)
    return None


def make_handler(cur_ch):
    def seen(p):
        if not p.haslayer(Dot11):
            return
        d = p[Dot11]
        addrs = [getattr(d, "addr1", None), getattr(d, "addr2", None),
                 getattr(d, "addr3", None)]
        parrot = next((a for a in addrs if is_parrot(a)), None)
        if not parrot:
            return
        state["bssid"] = state["bssid"] or parrot.lower()
        counts[cur_ch] += 1
        if p.haslayer(Dot11Beacon) or p.haslayer(Dot11ProbeResp):
            ssid = elt_find(p, 0)
            if ssid:
                try:
                    state["ssid"] = ssid.decode(errors="ignore") or state["ssid"]
                except Exception:
                    pass
            ds = elt_find(p, 3)  # DS Parameter Set = the AP's real channel
            if ds:
                state["beacon_ch"] = ds[0]
    return seen


def sweep(channels):
    for ch in channels:
        if not set_channel(ch):
            continue
        time.sleep(0.03)  # let the radio settle after the channel switch
        sys.stderr.write("[drone] probing ch %d...\n" % ch)
        sniff(iface=IFACE, prn=make_handler(ch), store=False, timeout=DWELL,
              stop_filter=lambda _p: state["beacon_ch"] is not None)
        if state["beacon_ch"] is not None:
            return True
    return bool(counts)


found = sweep(CH_24) or sweep(CH_5)
if not state["bssid"]:
    sys.stderr.write("[drone] no Bebop AP found on any scanned channel\n")
    sys.exit(1)

if state["beacon_ch"] is not None:
    channel = state["beacon_ch"]
else:
    channel = max(counts, key=counts.get)  # busiest channel = the real one
    sys.stderr.write("[drone] no beacon; picked busiest channel by frame count "
                     "%s\n" % dict(counts))

sys.stderr.write("[drone] found %s on ch %d (ssid=%r)\n"
                 % (state["bssid"], channel, state["ssid"]))
print("%s %d %s" % (state["bssid"], channel, state["ssid"]))
