#!/usr/bin/env python3
"""Auto-detect the Bebop's AP with no hardcoded MAC: channel-hop in monitor
mode and look for a beacon/probe-response whose SSID starts with the given
prefix (default "BebopDrone"), or whose BSSID is in Parrot's MAC OUI range.
Prints "<bssid> <channel>" on stdout for the shell scripts to read.
Needs sudo + the interface already in monitor mode.

Usage: find_drone.py <iface> [ssid_prefix]
"""
import subprocess
import sys
from scapy.all import sniff, Dot11, Dot11Beacon, Dot11ProbeResp, Dot11Elt

IFACE = sys.argv[1] if len(sys.argv) > 1 else "wlx00c0cabe245c"
PREFIX = (sys.argv[2] if len(sys.argv) > 2 else "BebopDrone").lower()

# Known Parrot OUIs (first 3 MAC octets) — fallback when the SSID is hidden.
PARROT_OUIS = ("a0:14:3d", "00:12:1c", "00:26:7e", "90:03:b7", "90:3a:e6")

# 2.4 GHz first (Bebop defaults there), then common non-DFS 5 GHz channels.
CHANNELS = list(range(1, 14)) + [36, 40, 44, 48, 149, 153, 157, 161, 165]
DWELL = 0.6  # seconds per channel (a beacon every ~100 ms, so this catches a few)


def set_channel(ch):
    return subprocess.run(
        ["iw", "dev", IFACE, "set", "channel", str(ch)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def ssid_of(p):
    elt = p.getlayer(Dot11Elt)
    while elt is not None:
        if elt.ID == 0:  # SSID element
            try:
                return elt.info.decode(errors="ignore")
            except Exception:
                return ""
        elt = elt.payload.getlayer(Dot11Elt)
    return ""


for ch in CHANNELS:
    if not set_channel(ch):
        continue
    hit = {"bssid": None}

    def seen(p):
        if not (p.haslayer(Dot11Beacon) or p.haslayer(Dot11ProbeResp)):
            return
        bssid = (getattr(p[Dot11], "addr3", None) or "").lower()
        if not bssid:
            return
        ssid = ssid_of(p).lower()
        if ssid.startswith(PREFIX) or bssid[:8] in PARROT_OUIS:
            hit["bssid"] = bssid

    sys.stderr.write("[drone] probing ch %d...\n" % ch)
    sniff(iface=IFACE, prn=seen, store=False, timeout=DWELL,
          stop_filter=lambda _p: hit["bssid"] is not None)
    if hit["bssid"]:
        sys.stderr.write("[drone] found %s on channel %d\n" % (hit["bssid"], ch))
        print("%s %d" % (hit["bssid"], ch))
        sys.exit(0)

sys.stderr.write("[drone] no Bebop AP found on any scanned channel\n")
sys.exit(1)
