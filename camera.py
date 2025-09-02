try:
    import cv2
except Exception:
    cv2 = None

import threading
import time

class Camera:
    def __init__(self, device_index=0, width=1280, height=720, fps=30):
        self.device_index = device_index
        self.width = width
        self.height = height
        self.fps = fps

        self.cap = None
        self.lock = threading.Lock()
        self.last_frame = None
        self.running = False
        self.thread = None

    def _open_once(self, idx, width, height, fps, fourcc_code=None):
        cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
        if not cap or not cap.isOpened():
            cap2 = cv2.VideoCapture(idx)
            if not cap2 or not cap2.isOpened():
                if cap: cap.release()
                return None
            if cap: cap.release()
            cap = cap2

        if fourcc_code is not None:
            cap.set(cv2.CAP_PROP_FOURCC, fourcc_code)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  int(width))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(height))
        cap.set(cv2.CAP_PROP_FPS,          int(fps))

        # прогрев
        for _ in range(10):
            ok, frame = cap.read()
            if ok and frame is not None and frame.size:
                return cap
            cv2.waitKey(1)

        cap.release()
        return None

    def _try_open(self):
        indices = [self.device_index, 1, 0, 2, 3]  # сначала попробуем 1 (часто MJPG)
        fourccs = [cv2.VideoWriter_fourcc(*'MJPG'),
                   cv2.VideoWriter_fourcc(*'YUYV'),
                   None]
        sizes = [(self.width, self.height), (1280,720), (640,480)]
        fps_list = [self.fps, 30, 25, 15]

        for idx in indices:
            for (w,h) in sizes:
                for f in fps_list:
                    for fc in fourccs:
                        cap = self._open_once(idx, w, h, f, fc)
                        if cap:
                            self.device_index, self.width, self.height, self.fps = idx, w, h, f
                            return cap
        return None

    def start(self):
        if cv2 is None:
            return False, "OpenCV (cv2) не установлен."
        with self.lock:
            if self.running:
                return True, "OK"
            cap = self._try_open()
            if not cap:
                return False, "Камера не открывается (проверь индексы/форматы)."
            self.cap = cap
            self.running = True
            self.thread = threading.Thread(target=self._reader, daemon=True)
            self.thread.start()
            return True, "OK"

    def _reader(self):
        while self.running and self.cap:
            ok, frame = self.cap.read()
            if ok and frame is not None and frame.size:
                with self.lock:
                    self.last_frame = frame
            else:
                time.sleep(0.02)

    def get_jpeg(self):
        with self.lock:
            frame = None if self.last_frame is None else self.last_frame.copy()
        if frame is None or cv2 is None:
            return None
        ok, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        return buf.tobytes() if ok else None

    def get_frame(self):
        with self.lock:
            return None if self.last_frame is None else self.last_frame.copy()

    def stop(self):
        with self.lock:
            self.running = False
            cap = self.cap
            self.cap = None
        if cap:
            cap.release()


camera = Camera(device_index=1)
