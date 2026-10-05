import cv2, time, threading, subprocess
import numpy as np, pygame
from pyparrot.Bebop import Bebop
from pyparrot.DroneVision import DroneVision

W, H = 856, 480
SPEED = 30                       # movement power, -100..100; raise once comfortable
cmd_lock = threading.Lock()
move = {"roll": 0, "pitch": 0, "yaw": 0, "vert": 0}
running = True

bebop = Bebop()
if not bebop.connect(5):
    print("connect failed"); raise SystemExit

bebop.set_video_stream_mode('high_reliability')
bebop.set_max_tilt(10)           # gentle indoor speed cap; remove/raise outdoors
vision = DroneVision(bebop, is_bebop=True)

def fly_loop():                  # push held movement continuously; drone hovers when idle
    while running:
        r, p, y, v = move["roll"], move["pitch"], move["yaw"], move["vert"]
        if r or p or y or v:
            with cmd_lock:
                bebop.fly_direct(roll=r, pitch=p, yaw=y, vertical_movement=v, duration=0.1)
        else:
            time.sleep(0.05)

def do(fn):                      # discrete command: stop motion first, then send
    move.update(roll=0, pitch=0, yaw=0, vert=0)
    time.sleep(0.15)
    with cmd_lock:
        fn()

if vision.open_video():
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Bebop | SPACE takeoff  L land  E stop  Q quit")
    threading.Thread(target=fly_loop, daemon=True).start()
    last, go = None, True
    while go:
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                go = False
            elif e.type == pygame.KEYDOWN:
                k = e.key
                if   k == pygame.K_SPACE: threading.Thread(target=do, args=(lambda: bebop.safe_takeoff(5),), daemon=True).start()
                elif k == pygame.K_l:     threading.Thread(target=do, args=(lambda: bebop.safe_land(5),), daemon=True).start()
                elif k == pygame.K_e:     threading.Thread(target=do, args=(lambda: bebop.safe_land(5),), daemon=True).start()
                elif k in (pygame.K_q, pygame.K_ESCAPE): go = False
                elif k == pygame.K_w: move["pitch"] =  SPEED
                elif k == pygame.K_s: move["pitch"] = -SPEED
                elif k == pygame.K_a: move["roll"]  = -SPEED
                elif k == pygame.K_d: move["roll"]  =  SPEED
                elif k == pygame.K_UP:    move["vert"] =  SPEED
                elif k == pygame.K_DOWN:  move["vert"] = -SPEED
                elif k == pygame.K_LEFT:  move["yaw"]  = -SPEED
                elif k == pygame.K_RIGHT: move["yaw"]  =  SPEED
            elif e.type == pygame.KEYUP:
                k = e.key
                if k in (pygame.K_w, pygame.K_s): move["pitch"] = 0
                if k in (pygame.K_a, pygame.K_d): move["roll"]  = 0
                if k in (pygame.K_UP, pygame.K_DOWN): move["vert"] = 0
                if k in (pygame.K_LEFT, pygame.K_RIGHT): move["yaw"] = 0

        img = vision.get_latest_valid_picture()
        if img is not None:
            last = img
        if last is not None:
            rgb = np.ascontiguousarray(cv2.cvtColor(last, cv2.COLOR_BGR2RGB))
            screen.blit(pygame.image.frombuffer(rgb.tobytes(), (W, H), "RGB"), (0, 0))
            pygame.display.flip()
        time.sleep(0.01)

    running = False
    do(lambda: bebop.safe_land(5))
    time.sleep(1)
    vision.close_video()
    bebop.disconnect()
    pygame.quit()
    subprocess.run(["pkill", "-9", "ffmpeg"])