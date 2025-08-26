import os
import io
import time
import threading
import subprocess
from datetime import datetime
from pathlib import Path

from flask import (
    Flask, send_from_directory, send_file, render_template, request,
    redirect, url_for, flash, Response, jsonify
)

IMAGES_FOLDER = Path("images")
CONVERTED_IMAGES_FOLDER = Path("converted_images")
STATIC_FOLDER = Path("static")
TEMPLATES_FOLDER = Path("templates")

IMAGE_NAME = "pair.jpg"
STEREO_EXECUTABLE = "./stereo"

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png'}
MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20MB

IMAGES_FOLDER.mkdir(parents=True, exist_ok=True)
CONVERTED_IMAGES_FOLDER.mkdir(parents=True, exist_ok=True)
STATIC_FOLDER.mkdir(parents=True, exist_ok=True)
TEMPLATES_FOLDER.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, static_folder=str(STATIC_FOLDER), template_folder=str(TEMPLATES_FOLDER))
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret")
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH


def list_images():
    return sorted([f for f in os.listdir(IMAGES_FOLDER) if Path(f).suffix.lower() in ALLOWED_EXTENSIONS])

def is_allowed(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS

def secure_unique_filename(original_name: str) -> str:
    stem = Path(original_name).stem
    ext = Path(original_name).suffix.lower()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_stem = "".join(c for c in stem if c.isalnum() or c in ('-', '_'))[:40] or "image"
    return f"{safe_stem}_{ts}{ext}"

def run_conversion(input_path: Path) -> tuple[bool, str]:
    try:
        subprocess.run([STEREO_EXECUTABLE, str(input_path)], check=True)
        return True, f"Изображение «{input_path.name}» сконвертировано."
    except FileNotFoundError:
        return False, "Не найден исполняемый файл конвертера (STEREO_EXECUTABLE)."
    except subprocess.CalledProcessError:
        return False, "Ошибка при запуске конвертации."


@app.route('/')
def serve_index():
    return send_from_directory(str(STATIC_FOLDER), 'index.html')

@app.route('/get-image')
def get_image():
    return send_file(CONVERTED_IMAGES_FOLDER / IMAGE_NAME, mimetype='image/jpeg')


@app.route('/admin', methods=['GET', 'POST'])
def admin():
    """
    POST (старый режим): принять имя уже существующей картинки и сконвертировать.
    GET: показать страницу админки.
    """
    if request.method == 'POST':
        filename = request.form.get('image')
        if filename:
            input_path = IMAGES_FOLDER / filename
            if input_path.exists():
                ok, msg = run_conversion(input_path)
                if ok:
                    flash(msg, "success")
                    return redirect(url_for('admin'))
                else:
                    flash(msg, "error")
                    return redirect(url_for('admin'))
        flash('Файл не найден', 'error')
        return redirect(url_for('admin'))

    images = list_images()
    return render_template('admin.html', images=images)


@app.route('/upload', methods=['POST'])
def upload():
    file = request.files.get('file')
    if not file or file.filename == '':
        return jsonify({'ok': False, 'message': 'Файл не выбран.'}), 400

    if not is_allowed(file.filename):
        return jsonify({'ok': False, 'message': 'Допустимы только JPG/PNG.'}), 400

    filename = secure_unique_filename(file.filename)
    save_path = IMAGES_FOLDER / filename
    file.save(save_path)

    return jsonify({'ok': True, 'message': f'Файл загружен: {filename}', 'filename': filename})


@app.route('/convert', methods=['POST'])
def convert():
    data = request.get_json(silent=True) or {}
    filename = data.get('filename')
    if not filename:
        return jsonify({'ok': False, 'message': 'Не указано имя файла.'}), 400

    input_path = IMAGES_FOLDER / filename
    if not input_path.exists():
        return jsonify({'ok': False, 'message': 'Файл не найден.'}), 404

    ok, msg = run_conversion(input_path)
    return jsonify({'ok': ok, 'message': msg})


try:
    import cv2
except Exception:
    cv2 = None

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

    def start(self):
        if cv2 is None:
            return False, "OpenCV (cv2) не установлен."
        with self.lock:
            if self.running:
                return True, "OK"
            self.cap = cv2.VideoCapture(self.device_index)
            if not self.cap.isOpened():
                return False, "Не удаётся открыть USB-камеру."
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self.cap.set(cv2.CAP_PROP_FPS, self.fps)
            self.running = True
            self.thread = threading.Thread(target=self._reader, daemon=True)
            self.thread.start()
            return True, "OK"

    def _reader(self):
        while self.running and self.cap:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.05)
                continue
            with self.lock:
                self.last_frame = frame
            time.sleep(0.001)

    def get_jpeg(self) -> bytes | None:
        with self.lock:
            frame = None if self.last_frame is None else self.last_frame.copy()
        if frame is None or cv2 is None:
            return None
        ok, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            return None
        return buf.tobytes()

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

camera = Camera(device_index=0)

@app.route('/camera-feed')
def camera_feed():
    ok, msg = camera.start()
    if not ok:
        return Response(f"<h3 style='font-family:sans-serif'>Ошибка камеры: {msg}</h3>", mimetype='text/html')

    def gen():
        while True:
            frame = camera.get_jpeg()
            if frame is None:
                time.sleep(0.05)
                continue
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

    return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/capture', methods=['POST'])
def capture():
    want_convert = request.args.get('convert', 'false').lower() == 'true'
    ok, msg = camera.start()
    if not ok:
        return jsonify({'ok': False, 'message': msg}), 500

    if cv2 is None:
        return jsonify({'ok': False, 'message': 'OpenCV не установлен.'}), 500

    frame = camera.get_frame()
    if frame is None:
        return jsonify({'ok': False, 'message': 'Нет кадра с камеры.'}), 500

    filename = f"camera_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    save_path = IMAGES_FOLDER / filename
    success = cv2.imwrite(str(save_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not success:
        return jsonify({'ok': False, 'message': 'Не удалось сохранить файл.'}), 500

    if want_convert:
        ok_conv, msg_conv = run_conversion(save_path)
        return jsonify({'ok': ok_conv, 'message': msg_conv, 'filename': filename})

    return jsonify({'ok': True, 'message': f'Снимок сохранён: {filename}', 'filename': filename})


@app.route('/images', methods=['GET'])
def images_api():
    return jsonify({'images': list_images()})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, threaded=True)
