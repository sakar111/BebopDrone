#!/bin/bash
# launcher.sh - tiny GUI picker for the Bebop intercept tools.
# Shows a zenity window; the chosen script runs in its own terminal (so you see
# the live output and can Ctrl-C). No sudo needed to launch this; each script
# asks for the sudo password in its terminal. Double-click SkyJack.desktop, or
# run ./launcher.sh.

DIR="$(cd "$(dirname "$0")" && pwd)"

# Pick a terminal emulator.
if command -v gnome-terminal >/dev/null; then
    run_term() { gnome-terminal --title="$1" -- bash -c "$2"; }
elif command -v x-terminal-emulator >/dev/null; then
    run_term() { x-terminal-emulator -T "$1" -e bash -c "$2"; }
elif command -v xterm >/dev/null; then
    run_term() { xterm -T "$1" -e bash -c "$2"; }
else
    zenity --error --text="No terminal emulator found (gnome-terminal/xterm)."
    exit 1
fi

CHOICE="$(zenity --list --radiolist \
    --title="SkyJack — Bebop Intercept" \
    --width=520 --height=300 \
    --text="Pick what to run (it opens in a terminal):" \
    --print-column=2 \
    --column="" --column="Action" --column="What it does" \
    TRUE  "Watch (Passive)" "Decode the video. Never transmits." \
    FALSE "Watch (Active)"  "Deauth-kick the phone for clean keyframes." \
    FALSE "Takeover"        "Deauth phone + fly/stream from the laptop." \
    2>/dev/null)"

[ -z "$CHOICE" ] && exit 0

case "$CHOICE" in
    "Watch (Passive)") SCRIPT="watch_passive.sh" ;;
    "Watch (Active)")  SCRIPT="watch_active.sh" ;;
    "Takeover")        SCRIPT="wifi_attack.sh" ;;
    *) exit 0 ;;
esac

# Run the script in its own terminal, kept open afterwards so you can read it.
run_term "SkyJack: $CHOICE" \
    "cd '$DIR'; sudo ./$SCRIPT; echo; echo '--- finished; press Enter to close ---'; read _"
