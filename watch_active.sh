#!/bin/bash
# watch_active.sh - ACTIVE intercept: deauth the phone to force fresh keyframes.
# This TRANSMITS (deauth), so the drone operator WILL notice brief video drops.
# Run only against your own drone, on the ground.
#
# Re-kicks every 20s so the laptop feed keeps resyncing to a clean keyframe.
HERE="$(cd "$(dirname "$0")" && pwd)"
DO_DEAUTH=1 KICK_EVERY=300 exec "$HERE/watch_bebop.sh"
