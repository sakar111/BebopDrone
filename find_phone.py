#!/usr/bin/env python3
"""Find the phone's (randomized) MAC: the busiest non-drone station inside the
drone's BSS.  We key off 802.11 addressing, NOT UDP ports, because the phone
transmits only control/RTCP (5005/55005, 54321), never the video ports.
Prints just the MAC on stdout for watch_bebop.sh.  Needs sudo + monitor mode
locked to the drone's channel."""
import sys
from collections import Counter
from scapy.all import sniff, Dot11

DRONE = "a0:14:3d:a6:f1:d5"
ALFA = "00:c0:ca:be:24:5c"          # our own adapter — never the phone
IFACE = sys.argv[1] if len(sys.argv) > 1 else "wlx00c0cabe245c"
cnt = Counter()


def h(p):
    if not p.haslayer(Dot11):
        return
    d11 = p[Dot11]
    sa = getattr(d11, "addr2", None)
    if not sa:
        return
    sa = sa.lower()
    if sa in (DRONE, ALFA) or sa.startswith(("ff:", "01:", "33:")):
        return
    # keep only frames within the drone's BSS (BSSID in addr1 or addr3)
    a1 = (getattr(d11, "addr1", None) or "").lower()
    a3 = (getattr(d11, "addr3", None) or "").lower()
    if DRONE not in (a1, a3):
        return
    cnt[sa] += 1


sys.stderr.write("[find] sniffing 6s for the phone's MAC...\n")
sniff(iface=IFACE, prn=h, store=False, timeout=6)
if not cnt:
    sys.stderr.write("[find] no phone station seen in the drone BSS\n")
    sys.exit(1)
mac, n = cnt.most_common(1)[0]
sys.stderr.write("[find] phone MAC = %s (%d frames)\n" % (mac, n))
print(mac)
