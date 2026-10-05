import cv2, time
from pyparrot.Bebop import Bebop
from pyparrot.DroneVision import DroneVision

bebop = Bebop()
if bebop.connect(5):
    bebop.set_video_stream_mode('high_reliability')
    vision = DroneVision(bebop, is_bebop=True)
    if vision.open_video():
        cv2.namedWindow("bebop", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("bebop", 856, 480)
        print("video open - press q to quit")
        last = None
        while True:
            img = vision.get_latest_valid_picture()
            if img is not None:
                last = img
            if last is not None:
                cv2.imshow("bebop", last)      # hold last good frame instead of going black
            if cv2.waitKey(30) & 0xFF == ord('q'):
                break
        vision.close_video()
        bebop.disconnect()
        cv2.destroyAllWindows()
        for _ in range(5):
            cv2.waitKey(1)
        import subprocess; subprocess.run(["pkill", "-9", "ffmpeg"])
    bebop.disconnect()
    cv2.destroyAllWindows()


    ### pkill -9 ffmpeg