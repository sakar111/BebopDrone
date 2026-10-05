import socket, struct, json, time, threading, datetime
import pygame

DRONE_IP="192.168.42.1"; DISCOVERY_PORT=44444; D2C_PORT=43210

tcp=socket.socket(socket.AF_INET,socket.SOCK_STREAM); tcp.settimeout(10)
tcp.connect((DRONE_IP,DISCOVERY_PORT))
tcp.sendall(json.dumps({"controller_type":"computer","controller_name":"laptop-takeover","d2c_port":D2C_PORT}).encode()+b"\x00")
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

# --- INIT HANDSHAKE (this is the new part) ---
now=datetime.datetime.now()
send_frame(4,11,cmd(0,4,1, now.strftime("%Y-%m-%d").encode()+b"\x00")); time.sleep(0.1)   # date
send_frame(4,11,cmd(0,4,2, now.strftime("T%H%M%S+0000").encode()+b"\x00")); time.sleep(0.1) # time
send_frame(4,11,cmd(0,2,0)); time.sleep(0.1)   # request AllSettings
send_frame(4,11,cmd(0,4,0)); time.sleep(0.1)   # request AllStates
send_frame(4,11,cmd(1,0,0)); time.sleep(0.2)   # flat trim
print("init handshake sent")

st={"flag":0,"roll":0,"pitch":0,"yaw":0,"gaz":0}
def pcmd_loop():
    while running:
        send_frame(2,10,cmd(1,0,2,struct.pack("<BbbbbI",st["flag"],st["roll"],st["pitch"],st["yaw"],st["gaz"],0)))
        time.sleep(0.04)
threading.Thread(target=pcmd_loop,daemon=True).start()

def takeoff(): send_frame(4,11,cmd(1,0,1)); print(">> takeoff sent")
def land():    send_frame(4,11,cmd(1,0,3)); print(">> land sent")
def emergency(): send_frame(4,11,cmd(1,0,4)); print(">> EMERGENCY")

pygame.init()
screen=pygame.display.set_mode((440,150))
pygame.display.set_caption("Bebop control - CLICK HERE then use keys")
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
    screen.fill((20,20,25))
    for i,t in enumerate(["SPACE takeoff  L land  E emergency  ESC quit",
                          "W/S fwd/back  A/D left/right  arrows up/down/turn",
                          f"r{st['roll']:+d} p{st['pitch']:+d} y{st['yaw']:+d} g{st['gaz']:+d} flag{st['flag']}"]):
        screen.blit(font.render(t,True,(230,230,230)),(12,18+i*34))
    pygame.display.flip(); clock.tick(60)

running=False; time.sleep(0.2); land(); pygame.quit(); print("landed / exited")