import socket, struct, json, time, threading, datetime, subprocess
import pygame

DRONE_IP="192.168.42.1"; DISCOVERY_PORT=44444; D2C_PORT=43210
STREAM_PORT=55004; CONTROL_PORT=55005          # video (arstream2) ports
W, H = 856, 480                                 # Bebop stream size

# --- handshake now also asks the drone for the video stream ---
tcp=socket.socket(socket.AF_INET,socket.SOCK_STREAM); tcp.settimeout(10)
tcp.connect((DRONE_IP,DISCOVERY_PORT))
tcp.sendall(json.dumps({
    "controller_type":"computer","controller_name":"laptop-control",
    "d2c_port":D2C_PORT,
    "arstream2_client_stream_port":STREAM_PORT,
    "arstream2_client_control_port":CONTROL_PORT,
}).encode()+b"\x00")
resp=json.loads(tcp.recv(4096).rstrip(b"\x00").decode()); tcp.close()
C2D_PORT=resp["c2d_port"]; print("connected, c2d_port =",C2D_PORT)

send_sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
recv_sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
recv_sock.bind(("0.0.0.0",D2C_PORT)); recv_sock.settimeout(0.5)

seq={}
def nseq(b): seq[b]=(seq.get(b,0)+1)%256; return seq[b]
def send_frame(dt,buf,payload):
    send_sock.sendto(struct.pack("<BBBI",dt,buf,nseq(buf),7+len(payload))+payload,(DRONE_IP,C2D_PORT))
def cmd(p,c,cc,args=b""): return struct.pack("<BBH",p,c,cc)+args

running=True
def receiver():
    while running:
        try: data,_=recv_sock.recvfrom(4096)
        except socket.timeout: continue
        if len(data)<7: continue
        dt,buf,s=data[0],data[1],data[2]
        if dt==4: send_frame(1,buf+128,bytes([s]))
threading.Thread(target=receiver,daemon=True).start()

# --- init handshake ---
now=datetime.datetime.now()
send_frame(4,11,cmd(0,4,1, now.strftime("%Y-%m-%d").encode()+b"\x00")); time.sleep(0.1)
send_frame(4,11,cmd(0,4,2, now.strftime("T%H%M%S+0000").encode()+b"\x00")); time.sleep(0.1)
send_frame(4,11,cmd(0,2,0)); time.sleep(0.1)
send_frame(4,11,cmd(0,4,0)); time.sleep(0.1)
send_frame(4,11,cmd(1,0,0)); time.sleep(0.2)   # flat trim
print("init handshake sent")

# --- start ffmpeg (binds the video port) then enable the stream ---
SDP="/tmp/bebop.sdp"
open(SDP,"w").write("v=0\no=- 0 0 IN IP4 0.0.0.0\ns=Bebop\nc=IN IP4 0.0.0.0\nt=0 0\n"
                    "m=video %d RTP/AVP 96\na=rtpmap:96 H264/90000\n" % STREAM_PORT)
ff=subprocess.Popen(
    ["ffmpeg","-protocol_whitelist","file,rtp,udp","-fflags","nobuffer","-flags","low_delay",
     "-i",SDP,"-f","rawvideo","-pix_fmt","rgb24","-"],
    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
time.sleep(0.5)
send_frame(4,11,cmd(1,21,0,struct.pack("<B",1))); print("video enable sent")   # MediaStreaming.VideoEnable(1)

frame={"buf":None}
def read_exact(n):
    b=b""
    while len(b)<n:
        c=ff.stdout.read(n-len(b))
        if not c: return None
        b+=c
    return b
def video_reader():
    size=W*H*3
    while running:
        buf=read_exact(size)
        if buf is None: break
        frame["buf"]=buf
threading.Thread(target=video_reader,daemon=True).start()

# --- control state + pcmd loop (unchanged) ---
st={"flag":0,"roll":0,"pitch":0,"yaw":0,"gaz":0}
def pcmd_loop():
    while running:
        send_frame(2,10,cmd(1,0,2,struct.pack("<BbbbbI",st["flag"],st["roll"],st["pitch"],st["yaw"],st["gaz"],0)))
        time.sleep(0.04)
threading.Thread(target=pcmd_loop,daemon=True).start()

def takeoff(): send_frame(4,11,cmd(1,0,1)); print(">> takeoff")
def land():    send_frame(4,11,cmd(1,0,3)); print(">> land")
def emergency(): send_frame(4,11,cmd(1,0,4)); print(">> EMERGENCY")

pygame.init()
screen=pygame.display.set_mode((W,H))
pygame.display.set_caption("Bebop - click here, then keys")
font=pygame.font.SysFont(None,22)
S=40; clock=pygame.time.Clock()
def upflag(): st["flag"]=1 if (st["roll"] or st["pitch"] or st["yaw"] or st["gaz"]) else 0

go=True
while go:
    for e in pygame.event.get():
        if e.type==pygame.QUIT: go=False
        elif e.type==pygame.KEYDOWN:
            k=e.key
            if k==pygame.K_SPACE: takeoff()
            elif k==pygame.K_l: land()
            elif k==pygame.K_e: emergency()
            elif k==pygame.K_ESCAPE: land(); go=False
            elif k==pygame.K_w: st["pitch"]=S
            elif k==pygame.K_s: st["pitch"]=-S
            elif k==pygame.K_a: st["roll"]=-S
            elif k==pygame.K_d: st["roll"]=S
            elif k==pygame.K_UP: st["gaz"]=S
            elif k==pygame.K_DOWN: st["gaz"]=-S
            elif k==pygame.K_LEFT: st["yaw"]=-S
            elif k==pygame.K_RIGHT: st["yaw"]=S
            upflag()
        elif e.type==pygame.KEYUP:
            k=e.key
            if k in (pygame.K_w,pygame.K_s): st["pitch"]=0
            if k in (pygame.K_a,pygame.K_d): st["roll"]=0
            if k in (pygame.K_UP,pygame.K_DOWN): st["gaz"]=0
            if k in (pygame.K_LEFT,pygame.K_RIGHT): st["yaw"]=0
            upflag()

    buf=frame["buf"]
    if buf is not None:
        screen.blit(pygame.image.frombuffer(buf,(W,H),"RGB"),(0,0))
    else:
        screen.fill((20,20,25))
    pygame.draw.rect(screen,(0,0,0),(0,0,W,58))
    for i,t in enumerate(["SPACE takeoff  L land  E emergency  ESC quit",
        "W/S fwd/back  A/D left/right  arrows up/down/turn",
        f"r{st['roll']:+d} p{st['pitch']:+d} y{st['yaw']:+d} g{st['gaz']:+d} flag{st['flag']}"]):
        screen.blit(font.render(t,True,(230,230,230)),(10,6+i*18))
    pygame.display.flip(); clock.tick(60)

running=False; time.sleep(0.2); land()
ff.kill(); pygame.quit()
subprocess.run(["pkill","-9","ffmpeg"])
print("landed / exited")