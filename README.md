# Bebop Drone — Python Control + Live Video

Fly a **Parrot Bebop 1** from your laptop with the keyboard while watching its
camera feed live, all from a single Python script. Built on
[pyparrot](https://pyparrot.readthedocs.io).

## Requirements

- Parrot **Bebop 1** drone
- Ubuntu (tested on 22.04)
- **Python 3.7** — required. pyparrot and the `zeroconf` version it needs don't
  work on newer Python. 3.7 installs *alongside* your system Python; it doesn't
  replace it.

## Setup

Installs need internet, so do all of this **before** connecting to the drone's
Wi-Fi.

**1. Install Python 3.7 and the system packages**

```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install python3.7 python3.7-venv python3.7-dev ffmpeg libxcb-cursor0 libxcb-xinerama0
```

**2. Create a virtual environment and install the Python dependencies**

```bash
python3.7 -m venv .venv37
source .venv37/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

**3. Patch pyparrot for the Bebop 1**

pyparrot targets the Bebop 2's network name by default. This one command points
it at the Bebop 1's instead:

```bash
PYPARROT_DIR=$(python3.7 -c "import pyparrot, os; print(os.path.dirname(pyparrot.__file__))")
sed -i 's/_arsdk-090c/_arsdk-0901/g' "$PYPARROT_DIR/networking/wifiConnection.py"
```

(Skip this step if you have a Bebop 2.)

## Running

This repo has a few scripts. Some use the **pyparrot** library — simpler, but the
video runs a second or two behind. The **raw-socket** scripts talk to the drone
directly, so control and video are noticeably faster.

### Controls

| Key | Action |
|-----|--------|
| `SPACE` | take off |
| `W` / `S` | forward / back |
| `A` / `D` | left / right |
| `↑` / `↓` | up / down |
| `←` / `→` | turn left / right |
| *(release key)* | hover |
| `L` | land |
| `E` | stop & land |
| `Q` / `ESC` | quit |

## Notes & troubleshooting

- **One controller at a time.** The Bebop allows only a single connection, so
  you can't run two scripts against it at once — the second gets
  `Connection refused`. Exit one cleanly (press `Q`) before starting another.
- **After a crash or Ctrl-C**, a stray ffmpeg process can hold the video port
  and block the next run. Clear it first:
  ```bash
  pkill -9 ffmpeg
  ```
  If the drone itself still refuses to connect, power-cycle it.
- **Video latency:** this uses pyparrot's ffmpeg-to-disk video path, which runs
  roughly 1–2 seconds behind real time. Fine for watching; keep that delay in
  mind if you fly by the feed rather than line of sight.
- **First flight:** clear the propellers, use open space, keep the `SPEED` value
  low, and keep a finger on `L`.

## Files

- `video_fly.py` — main script: keyboard flight control + live video
- `requirements.txt` — Python dependencies (Python 3.7 only)

## Running the WiFi Attack
```bash
chmod +x wifi_attack.sh
```
```bash
./wifi_attack.sh
```
