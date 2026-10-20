#!/usr/bin/env python3
"""
live_parser.py - Bebop video reassembly to H.264 (Annex-B): offline OR live.

LIVE (watch in real time; interface must already be in monitor mode + locked
to the drone's channel -- watch_bebop.sh does that):
  sudo python3 live_parser.py --live wlx00c0cabe245c --mode v1 --ffplay \\
      --bssid A0:14:3D:A6:F1:D5

OFFLINE (from a saved capture):
  python3 live_parser.py -r bebop_cap-01.cap --autoport --mode v1 -o bebop.h264
  ffplay bebop.h264

Modes:  v1 = Bebop 1 (ARStream)   v2 = Bebop 2 (RTP H.264)

Passive only: never associates, never transmits. The Bebop AP is open, so the
video is already in the clear. Dropped packets => on-screen artifacts; that is
capture loss, not a bug. The offline path is the reliable one; --live is
best-effort and may stutter because Python scapy can't always keep up with a
full-rate video stream.

KEY PROTOCOL NOTES (Bebop 1):
  - In 802.11 monitor mode we see BOTH directions of every UDP conversation.
  - Video flows drone->phone (sport=5004, dport=55004) carry the H.264.
  - Reverse direction (phone->drone ACKs, sport=55004, dport=5004) carries
    tiny control packets with DIFFERENT frame numbers.
  - If we reassemble both directions together, ffplay sees interleaved frame
    numbers and never gets SPS/PPS + IDR in the same pass.
  - Fix: pass --bssid <drone MAC> so we only process 802.11 frames transmitted
    BY the drone (SA == drone BSSID).  Without --bssid we fall back to the
    UDP-bytes heuristic, which often locks onto the wrong direction first.

ARStream v1 UDP payload (5-byte header, little-endian):
  uint16 frameNumber
  uint8  frameFlags   (bit0 = last fragment of frame)
  uint8  fragmentNumber
  uint8  fragmentsPerFrame
  [H.264 NAL unit data ...]
"""

import argparse
import struct
import sys
import shutil
import subprocess
import glob as _glob
from collections import defaultdict

try:
    from scapy.all import rdpcap, sniff, UDP, Dot11
except ImportError:
    sys.exit("scapy not found:  pip install scapy")

START = b"\x00\x00\x00\x01"  # H.264 Annex-B start code

# Bebop 1 (ARStream2 / RTP) H.264 parameter sets, captured off the air at
# 856x480 Constrained Baseline L4.0.  The drone only transmits SPS/PPS at
# stream (re)start, so a passive sniffer that joins mid-stream never sees
# them and the decoder can't start ("non-existing PPS referenced").  With
# --prime we inject these once at startup so ffplay can begin decoding the
# P/intra-refresh slices immediately, regardless of when we joined.
# If the drone streams a different resolution these will be wrong -- in that
# case drop --prime and (re)start the phone video while sniffing instead.
BEBOP1_SPS = bytes.fromhex("6742e0288d680d83de5f01100008256001e84809f1422a")
BEBOP1_PPS = bytes.fromhex("68ce0d2480")
PRIMER = START + BEBOP1_SPS + START + BEBOP1_PPS


# ---------- RTP / H.264 depacketization (Bebop 2) ----------

def rtp_parse(pl):
    """Return (seq, payload_after_rtp_header) or None."""
    if len(pl) < 13 or (pl[0] >> 6) != 2:
        return None
    cc = pl[0] & 0x0F
    ext = (pl[0] >> 4) & 1
    seq = struct.unpack("!H", pl[2:4])[0]
    h = 12 + cc * 4
    if ext:
        if len(pl) < h + 4:
            return None
        h += 4 + struct.unpack("!H", pl[h + 2:h + 4])[0] * 4
    return seq, pl[h:]


class V2Depacketizer:
    """Feed RTP payloads in sequence order; writes NAL units to `write`."""
    def __init__(self, write):
        self.write = write
        self.fu = bytearray()

    def push(self, p):
        if not p:
            return
        t = p[0] & 0x1F
        if 1 <= t <= 23:                       # single NAL
            self.write(START + p)
        elif t == 24:                          # STAP-A (aggregated)
            i = 1
            while i + 2 <= len(p):
                sz = struct.unpack("!H", p[i:i + 2])[0]
                i += 2
                if i + sz <= len(p):
                    self.write(START + p[i:i + sz])
                i += sz
        elif t == 28:                          # FU-A (fragmented)
            start = p[1] & 0x80
            end = p[1] & 0x40
            otype = p[1] & 0x1F
            if start:
                self.fu = bytearray([(p[0] & 0xE0) | otype])
            if self.fu:
                self.fu += p[2:]
            if end and self.fu:
                self.write(START + bytes(self.fu))
                self.fu = bytearray()


# ---------- ARStream (Bebop 1) ----------

class V1Reassembler:
    """
    Streaming ARStream v1 reassembler.
    Emits one Annex-B H.264 access unit per video frame.

    The Bebop 1 sends H.264 NAL unit data directly after the 5-byte ARStream
    header.  SPS/PPS/IDR frames already have Annex-B start codes prepended by
    the drone; regular P-frame slices (NAL type 1) do not, so we add one.
    """
    def __init__(self, write):
        self.write = write
        self.cur = None
        self.frags = {}

    def push(self, pl):
        if len(pl) < 5:
            return
        frame_no, flags, frag_no, frags_per = struct.unpack("<HBBB", pl[:5])
        payload = pl[5:]

        if self.cur is None:
            self.cur = frame_no

        if frame_no != self.cur:
            self._flush()
            self.cur = frame_no
            self.frags = {}

        self.frags[frag_no] = payload

        # Eagerly flush when we have the last fragment (frameFlags bit 0 set)
        # OR when we have all expected fragments.
        flush_flag = flags & 0x01
        if flush_flag or (frags_per > 0 and len(self.frags) >= frags_per):
            self._flush()
            self.cur = None
            self.frags = {}

    def _flush(self):
        if not self.frags:
            return
        data = b"".join(self.frags[i] for i in sorted(self.frags))
        if not data:
            return

        # If the reassembled data already begins with an Annex-B start code,
        # don't prepend another one (SPS/PPS/IDR frames from the drone).
        if data[:3] == b"\x00\x00\x01" or data[:4] == b"\x00\x00\x00\x01":
            self.write(data)
        else:
            self.write(START + data)

        sys.stderr.write(
            f"[v1] frame {self.cur}  frags={len(self.frags)}  "
            f"bytes={len(data)}  "
            f"nal_type={data[0] & 0x1F if data else '?'}\n"
        )


# ---------- offline ----------

def load_udp(path, port, autoport):
    flows = defaultdict(list)
    for p in rdpcap(path):
        if p.haslayer(UDP):
            u = p[UDP]
            data = bytes(u.payload)
            if data:
                flows[(u.sport, u.dport)].append(data)
    if not flows:
        return []
    if autoport or port is None:
        # Pick the flow with the most total bytes — that's the video stream.
        best = max(flows, key=lambda k: sum(len(x) for x in flows[k]))
        total = sum(len(x) for x in flows[best])
        sys.stderr.write(
            f"[auto] video flow sport={best[0]} dport={best[1]}, "
            f"{len(flows[best])} pkts, {total} bytes\n"
        )
        return flows[best]
    out = []
    for (sp, dp), lst in flows.items():
        if sp == port or dp == port:
            out.extend(lst)
    return out


def reassemble_v1_offline(payloads):
    """Offline: collect all packets first, then reassemble in order."""
    frames = defaultdict(dict)
    expected = {}
    for pl in payloads:
        if len(pl) < 5:
            continue
        fn, _fl, frag, per = struct.unpack("<HBBB", pl[:5])
        frames[fn][frag] = pl[5:]
        expected[fn] = per

    out = bytearray()
    incomplete = 0
    for fn in sorted(frames):
        frags = frames[fn]
        if expected.get(fn, 0) and len(frags) != expected[fn]:
            incomplete += 1
        data = b"".join(frags[i] for i in sorted(frags))
        if data:
            if data[:3] == b"\x00\x00\x01" or data[:4] == b"\x00\x00\x00\x01":
                out += data
            else:
                out += START + data

    sys.stderr.write(f"[v1] {len(frames)} frames, {incomplete} incomplete\n")
    return bytes(out)


def reassemble_v2(payloads):
    pkts = [r for r in (rtp_parse(pl) for pl in payloads) if r]
    pkts.sort(key=lambda x: x[0])
    out = bytearray()
    d = V2Depacketizer(out.extend)
    for _seq, body in pkts:
        d.push(body)
    sys.stderr.write(f"[v2] {len(pkts)} RTP packets\n")
    return bytes(out)


# ---------- live ----------

def _normalise_mac(mac):
    """Normalise a MAC address string to lower-case colon-separated."""
    if mac is None:
        return None
    return mac.strip().lower().replace("-", ":").replace(".", ":")


def run_live(iface, mode, write, flush, bssid=None):
    """
    Sniff the monitor-mode interface and reassemble video.

    bssid: if provided (drone MAC address), only accept 802.11 frames whose
           source address (SA) matches — this reliably filters out the
           phone->drone ACK direction whose frame numbers would corrupt
           the reassembly.  Without it we fall back to a bytes-count
           heuristic which is less reliable.
    """
    depkt = V2Depacketizer(write) if mode == "v2" else V1Reassembler(write)
    state = {"flow": None, "next": None}
    bytes_by_flow = defaultdict(int)
    reorder = {}

    drone_mac = _normalise_mac(bssid)
    if drone_mac:
        sys.stderr.write(f"[live] filtering on drone SA={drone_mac}\n")
    else:
        sys.stderr.write(
            "[live] WARNING: no --bssid given; using bytes-count heuristic. "
            "If video is garbled, re-run with --bssid <drone MAC>.\n"
        )

    def handle(pkt):
        # ----- 802.11 source-MAC filter (most reliable direction filter) -----
        if drone_mac is not None:
            if not pkt.haslayer(Dot11):
                return
            d11 = pkt[Dot11]
            # addr2 is the transmitter/SA in a data frame
            sa = _normalise_mac(getattr(d11, "addr2", None))
            if sa != drone_mac:
                return

        if not pkt.haslayer(UDP):
            return
        u = pkt[UDP]
        data = bytes(u.payload)
        if not data:
            return
        flow = (u.sport, u.dport)

        # If no BSSID filter, fall back to byte-count heuristic:
        # accumulate bytes per flow and lock onto the heaviest one.
        if drone_mac is None:
            if state["flow"] is None:
                bytes_by_flow[flow] += len(data)
                if bytes_by_flow[flow] > 5000:
                    state["flow"] = flow
                    sys.stderr.write(
                        f"[live] locked video flow "
                        f"sport={flow[0]} dport={flow[1]}\n"
                    )
                else:
                    return
            if flow != state["flow"]:
                return

        if mode == "v2":
            r = rtp_parse(data)
            if not r:
                return
            seq, body = r
            reorder[seq] = body
            if state["next"] is None:
                state["next"] = seq
            while True:
                ns = state["next"]
                if ns in reorder:
                    depkt.push(reorder.pop(ns))
                    state["next"] = (ns + 1) & 0xFFFF
                elif len(reorder) > 128:        # gave up waiting; skip the gap
                    state["next"] = min(reorder)
                else:
                    break
        else:
            depkt.push(data)
        flush()

    # Kernel BPF filter: hand Python only the drone->phone video UDP packets
    # (src port 5004).  Without this, scapy's per-packet Python callback must
    # process every 802.11 frame on the air (beacons, the phone's traffic,
    # other networks) and falls behind, dropping video fragments -> corrupt
    # NALs ("Invalid NAL unit 0", bogus PPS ids, missing reference pictures).
    bpf = "udp and src port 5004"
    sys.stderr.write(f"[live] sniffing {iface} (mode {mode}); Ctrl-C to stop\n")
    try:
        sniff(iface=iface, prn=handle, store=False, filter=bpf)
    except Exception as e:
        sys.stderr.write(
            f"[live] BPF filter '{bpf}' failed ({e}); sniffing unfiltered\n")
        sniff(iface=iface, prn=handle, store=False)


# ---------- sink ----------

def open_sink(use_ffplay, outfile):
    if use_ffplay:
        if not shutil.which("ffplay"):
            sys.exit("ffplay not found - install ffmpeg")
        import os
        import pwd

        env = os.environ.copy()

        # Restore display environment that sudo strips.
        if "DISPLAY" not in env or not env["DISPLAY"]:
            env["DISPLAY"] = ":0"

        if "XAUTHORITY" not in env or not env["XAUTHORITY"]:
            sudo_user = os.environ.get("SUDO_USER", "")
            uid_to_check = ""
            if sudo_user:
                try:
                    uid_to_check = str(pwd.getpwnam(sudo_user).pw_uid)
                except Exception:
                    pass
            if not uid_to_check:
                uid_to_check = "1000"

            candidates = _glob.glob(
                f"/run/user/{uid_to_check}/.mutter-Xwaylandauth.*"
            )
            if candidates:
                env["XAUTHORITY"] = candidates[0]
            else:
                home = os.path.expanduser(
                    f"~{sudo_user}" if sudo_user else "~"
                )
                env["XAUTHORITY"] = os.path.join(home, ".Xauthority")

        sys.stderr.write(
            f"[sink] DISPLAY={env['DISPLAY']}  "
            f"XAUTHORITY={env.get('XAUTHORITY', '')}\n"
        )

        # Drop privileges to the real user so ffplay can open the display.
        preexec = None
        sudo_user = os.environ.get("SUDO_USER", "")
        if sudo_user:
            try:
                pw = pwd.getpwnam(sudo_user)
                uid, gid = pw.pw_uid, pw.pw_gid
                def drop_privs():
                    os.setgid(gid)
                    os.setuid(uid)
                preexec = drop_privs
            except Exception:
                pass

        proc = subprocess.Popen(
            [
                "ffplay",
                "-hide_banner",
                "-loglevel", "warning",
                "-fflags", "nobuffer+discardcorrupt",
                "-flags", "low_delay",
                "-strict", "experimental",
                "-f", "h264",
                "-i", "-",
            ],
            stdin=subprocess.PIPE,
            env=env,
            preexec_fn=preexec,
        )
        return proc.stdin.write, proc.stdin.flush, proc

    f = open(outfile, "wb")
    return f.write, f.flush, f


def main():
    ap = argparse.ArgumentParser(description="Bebop video reassembly (offline/live)")
    ap.add_argument("-r", metavar="CAP", help="offline: capture file to read")
    ap.add_argument("--live", metavar="IFACE", help="live: monitor interface to sniff")
    ap.add_argument("--bssid", metavar="MAC",
                    help="live: drone BSSID / MAC (e.g. A0:14:3D:A6:F1:D5); "
                         "highly recommended for Bebop 1 -- filters out the "
                         "phone->drone ACK direction so only drone->phone video "
                         "packets are reassembled")
    ap.add_argument("--port", type=int, help="offline: video UDP port")
    ap.add_argument("--autoport", action="store_true",
                    help="offline: auto-pick video flow")
    ap.add_argument("--mode", choices=["v1", "v2"], required=True)
    ap.add_argument("--ffplay", action="store_true",
                    help="pipe/play with ffplay")
    ap.add_argument("--prime", action="store_true",
                    help="live v2: inject known Bebop 1 SPS/PPS (856x480) at "
                         "startup so decoding can begin without catching the "
                         "drone's stream-start parameter sets")
    ap.add_argument("-o", default="bebop.h264",
                    help="output file (offline, or live w/o --ffplay)")
    a = ap.parse_args()

    if bool(a.r) == bool(a.live):
        ap.error(
            "give exactly one of: -r <cap> (offline)  OR  --live <iface> (live)"
        )

    if a.live:
        write, flush, closable = open_sink(a.ffplay, a.o)
        if a.prime:
            if a.mode != "v2":
                sys.stderr.write("[prime] ignored (only applies to --mode v2)\n")
            else:
                sys.stderr.write(
                    "[prime] injecting known SPS/PPS (856x480) at startup\n")
                write(PRIMER)
                flush()
        try:
            run_live(a.live, a.mode, write, flush, bssid=a.bssid)
        except KeyboardInterrupt:
            pass
        finally:
            try:
                flush()
            except Exception:
                pass
            if hasattr(closable, "stdin"):          # ffplay process
                closable.stdin.close()
                closable.wait()
            else:
                closable.close()
        return

    payloads = load_udp(a.r, a.port, a.autoport)
    if not payloads:
        sys.exit("No UDP payloads matched. Check --port / --autoport / the capture.")

    data = (reassemble_v1_offline(payloads)
            if a.mode == "v1"
            else reassemble_v2(payloads))
    if not data:
        sys.exit("Reassembled 0 bytes - wrong --mode, or no video in capture.")

    with open(a.o, "wb") as f:
        f.write(data)
    sys.stderr.write(f"wrote {len(data)} bytes -> {a.o}\n")
    if a.ffplay:
        if shutil.which("ffplay"):
            subprocess.run(["ffplay", "-hide_banner", a.o])
        else:
            sys.stderr.write("ffplay not found - install ffmpeg\n")


if __name__ == "__main__":
    main()