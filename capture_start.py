#!/usr/bin/env python3
"""Capture drone video for 25s while you RESTART the phone's video stream,
to catch the SPS/PPS/IDR the drone sends at stream start.
Run: sudo ./.venv37/bin/python3 capture_start.py
Then, during the countdown, background+reopen FreeFlight (or toggle the camera
view) so the phone re-requests video."""
import struct
import sys
from collections import Counter
from scapy.all import sniff, UDP, Dot11, wrpcap

DRONE = "a0:14:3d:a6:f1:d5"
IFACE = "wlx00c0cabe245c"
OUT = "/tmp/bebop_start.pcap"
pkts = []
seen = Counter()


def rtp_body(pl):
    if len(pl) < 12 or (pl[0] >> 6) != 2:
        return None
    cc = pl[0] & 0x0F
    ext = (pl[0] >> 4) & 1
    h = 12 + cc * 4
    if ext:
        if len(pl) < h + 4:
            return None
        h += 4 + struct.unpack("!H", pl[h + 2:h + 4])[0] * 4
    return pl[h:]


def h(p):
    if not p.haslayer(Dot11) or not p.haslayer(UDP):
        return
    sa = getattr(p[Dot11], "addr2", None)
    if not sa or sa.lower() != DRONE:
        return
    u = p[UDP]
    if not (u.sport == 5004 and u.dport == 55004):
        return
    pl = bytes(u.payload)
    if not pl:
        return
    pkts.append(p)
    body = rtp_body(pl)
    if not body:
        return
    t = body[0] & 0x1F
    if t == 24:  # STAP-A
        i = 1
        while i + 2 <= len(body):
            sz = struct.unpack("!H", body[i:i + 2])[0]
            i += 2
            if sz == 0 or i + sz > len(body):
                break
            nt = body[i] & 0x1F
            seen[nt] += 1
            if nt in (7, 8, 5):
                sys.stderr.write("  >>> caught NAL type %d !\n" % nt)
            i += sz
    else:
        seen[t] += 1
        if t in (7, 8, 5):
            sys.stderr.write("  >>> caught NAL type %d (non-STAP)!\n" % t)


sys.stderr.write("[cap] 25s capture — RESTART the phone video NOW "
                 "(background+reopen FreeFlight / toggle camera view)\n")
sniff(iface=IFACE, prn=h, store=False, timeout=25)
wrpcap(OUT, pkts)
import os
try:
    os.chmod(OUT, 0o644)
except Exception:
    pass
sys.stderr.write("[cap] wrote %d pkts -> %s\n" % (len(pkts), OUT))
print("NAL types seen:", dict(seen))
print("GOT PARAM SETS:", {k: seen[k] for k in (7, 8, 5) if k in seen} or "NONE")
