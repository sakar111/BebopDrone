#!/bin/bash
# watch_passive.sh - PURE PASSIVE intercept: never transmits a single frame.
# The drone operator has no way to tell anyone is listening. Trade-off: the
# decoder only locks on when a keyframe naturally passes, so start this BEFORE
# the operator opens video (or expect a glitchy, slowly-refreshing picture).
HERE="$(cd "$(dirname "$0")" && pwd)"
DO_DEAUTH=0 exec "$HERE/watch_bebop.sh"
