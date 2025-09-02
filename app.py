import os
import csv
import time
import threading
import subprocess
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from PIL import Image

from flask import (
    Flask, send_from_directory, send_file, render_template, request,
    redirect, url_for, flash, Response, jsonify
)

CONFIG_FOLDER = Path("config")
CONFIG_PATH = CONFIG_FOLDER / "config.csv"
CONFIG_FOLDER.mkdir(parents=True, exist_ok=True)

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

DEFAULT_CONFIG = {
    "parallax_perc": "0.5",
    "layers_count": "10",
    "zero_parallax_layer_num": "5",
    "output_mode": "both",  # both|pair|split
    "resize_mode": "none",  # none|fit|exact
    "target_width": "0",
    "target_height": "0",
    "jpeg_quality": "95",
    "auto_snap_enabled": "false",
    "auto_snap_interval": "5",
    "auto_snap_convert": "true",
    "auto_snap_max_files": "50"
}

auto_snap_thread = None
auto_snap_stop = threading.Event()

last_auto_filename = None
last_auto_time = None
last_auto_error = None


def auto_snap_worker():
    global last_auto_filename, last_auto_time, last_auto_error
    while not auto_snap_stop.is_set():
        cfg = read_config()
        if cfg.get("auto_snap_enabled", "false").lower() == "true":
            try:
                interval = max(1, int(float(cfg.get("auto_snap_interval") or 5)))
            except Exception:
                interval = 5
            want_convert = (cfg.get("auto_snap_convert") or "true").lower() == "true"
            max_files = max(1, int(float(cfg.get("auto_snap_max_files") or 50)))

            ok, msg = camera.start()
            if not ok:
                last_auto_error = f"Камера: {msg}"
                time.sleep(interval)
                continue

            if cv2 is None:
                last_auto_error = "OpenCV не установлен"
                time.sleep(interval)
                continue

            frame = camera.get_frame()
            if frame is None:
                last_auto_error = "Нет кадра"
                time.sleep(interval)
                continue

            filename = f"auto_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            save_path = IMAGES_FOLDER / filename
            success = cv2.imwrite(str(save_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
            if not success:
                last_auto_error = f"Сохранение не удалось: {filename}"
                time.sleep(interval)
                continue

            last_auto_filename = filename
            last_auto_time = datetime.now()
            last_auto_error = None

            prune_autosnap_files(max_files)

            if want_convert:
                ok_conv, msg_conv = run_conversion(save_path)
                if not ok_conv:
                    last_auto_error = f"Конвертация: {msg_conv}"

            time.sleep(interval)
        else:
            time.sleep(2)


def start_auto_snap_thread():
    global auto_snap_thread
    if auto_snap_thread and auto_snap_thread.is_alive():
        return
    auto_snap_stop.clear()
    auto_snap_thread = threading.Thread(target=auto_snap_worker, daemon=True)
    auto_snap_thread.start()


def read_config() -> dict:
    cfg = DEFAULT_CONFIG.copy()
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open(newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                k, v = row.get("key"), row.get("value")
                if k in cfg:
                    cfg[k] = v
    else:
        write_config(cfg)
    return cfg


def write_config(cfg: dict):
    with CONFIG_PATH.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(["key", "value"])
        for k, v in cfg.items():
            w.writerow([k, str(v)])


def maybe_resize_image(input_path: Path, cfg: dict) -> Path:
    mode = (cfg.get("resize_mode") or "none").lower()
    tw = int(float(cfg.get("target_width") or 0))
    th = int(float(cfg.get("target_height") or 0))
    if mode == "none" or (tw <= 0 and th <= 0):
        return input_path

    with Image.open(input_path) as im:
        im = im.convert("RGB")
        if mode == "fit":
            if tw <= 0 or th <= 0:
                return input_path
            im.thumbnail((tw, th))
        elif mode == "exact":
            if tw <= 0 or th <= 0:
                return input_path
            im = im.resize((tw, th), Image.LANCZOS)
        else:
            return input_path

        tmpf = NamedTemporaryFile(prefix="resized_", suffix=".jpg", delete=False, dir=str(IMAGES_FOLDER))
        tmp_path = Path(tmpf.name)
        quality = max(1, min(100, int(float(cfg.get("jpeg_quality") or 95))))
        im.save(tmp_path, "JPEG", quality=quality, optimize=True)
        return tmp_path


def run_conversion(input_path: Path) -> tuple[bool, str]:
    cfg = read_config()
    resized_path = maybe_resize_image(input_path, cfg)
    try:
        parallax = str(float(cfg.get("parallax_perc", 0.5)))
        layers = str(int(float(cfg.get("layers_count", 10))))
        zlayer = str(int(float(cfg.get("zero_parallax_layer_num", 5))))
        out_mode = (cfg.get("output_mode") or "both").lower()
        mode_code = {"both": "0", "pair": "1", "split": "2"}.get(out_mode, "0")

        cmd = [STEREO_EXECUTABLE, str(resized_path), parallax, layers, zlayer, mode_code]
        subprocess.run(cmd, check=True)
        return True, f"Конвертация ок (parallax={parallax}, layers={layers}, zpl={zlayer}, mode={out_mode})."
    except FileNotFoundError:
        return False, "Не найден исполняемый файл конвертера (STEREO_EXECUTABLE)."
    except subprocess.CalledProcessError:
        return False, "Ошибка при запуске конвертера."
    finally:
        if resized_path != input_path and resized_path.exists():
            try: resized_path.unlink()
            except Exception: pass



def prune_autosnap_files(max_files: int):
    """Держим только последние N файлов с префиксом auto_*.jpg в images/"""
    files = []
    for p in IMAGES_FOLDER.glob("auto_*.jpg"):
        try:
            stat = p.stat()
            files.append((stat.st_mtime, p))
        except FileNotFoundError:
            pass
    files.sort(reverse=True)  # новые сверху
    for _, p in files[max_files:]:
        try:
            p.unlink()
        except Exception:
            pass


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


@app.route('/config.json', methods=['GET'])
def get_config():
    return jsonify(read_config())


@app.route('/save-config', methods=['POST'])
def save_config():
    data = request.get_json(silent=True) or {}
    cfg = read_config()

    def clamp_float(s, lo, hi, dv):
        try:
            v = float(s); return str(max(lo, min(hi, v)))
        except Exception:
            return str(dv)
    def clamp_int(s, lo, hi, dv):
        try:
            v = int(float(s)); return str(max(lo, min(hi, v)))
        except Exception:
            return str(dv)

    cfg["parallax_perc"] = clamp_float(data.get("parallax_perc", cfg["parallax_perc"]), 0.0, 100.0, 0.5)
    cfg["layers_count"] = clamp_int(data.get("layers_count", cfg["layers_count"]), 1, 255, 10)
    cfg["zero_parallax_layer_num"] = clamp_int(data.get("zero_parallax_layer_num", cfg["zero_parallax_layer_num"]), 1, 255, 5)

    out_mode = (data.get("output_mode", cfg["output_mode"]) or "both").lower()
    if out_mode not in ("both", "pair", "split"): out_mode = "both"
    cfg["output_mode"] = out_mode

    resize_mode = (data.get("resize_mode", cfg["resize_mode"]) or "none").lower()
    if resize_mode not in ("none", "fit", "exact"): resize_mode = "none"
    cfg["resize_mode"] = resize_mode

    cfg["target_width"]  = clamp_int(data.get("target_width",  cfg["target_width"]),  0, 10000, 0)
    cfg["target_height"] = clamp_int(data.get("target_height", cfg["target_height"]), 0, 10000, 0)
    cfg["jpeg_quality"]  = clamp_int(data.get("jpeg_quality",  cfg["jpeg_quality"]),  1, 100, 95)

    cfg["auto_snap_enabled"] = "true" if str(data.get("auto_snap_enabled", cfg["auto_snap_enabled"])).lower() in ("1","true","yes","on") else "false"
    cfg["auto_snap_interval"] = clamp_int(data.get("auto_snap_interval", cfg["auto_snap_interval"]), 1, 3600, 5)
    cfg["auto_snap_convert"] = "true" if str(data.get("auto_snap_convert", cfg["auto_snap_convert"])).lower() in ("1","true","yes","on") else "false"
    cfg["auto_snap_max_files"] = clamp_int(data.get("auto_snap_max_files", cfg["auto_snap_max_files"]), 1, 10000, 50)

    write_config(cfg)
    return jsonify({"ok": True, "message": "Конфигурация сохранена.", "config": cfg})


@app.route('/image-file')
def image_file():
    name = request.args.get('name', '')
    # простая защита от обхода путей
    if not name or any(x in name for x in ('..', '/', '\\')):
        return "bad name", 400
    path = IMAGES_FOLDER / name
    if not path.exists():
        return "not found", 404
    return send_file(path)


@app.route('/auto-snap-status')
def auto_snap_status():
    cfg = read_config()
    return jsonify({
        "enabled": cfg.get("auto_snap_enabled") == "true",
        "interval": int(cfg.get("auto_snap_interval") or 5),
        "convert": cfg.get("auto_snap_convert") == "true",
        "max_files": int(float(cfg.get("auto_snap_max_files") or 50)),
        "running": auto_snap_thread.is_alive() if 'auto_snap_thread' in globals() and auto_snap_thread else False,
        "last_filename": last_auto_filename,
        "last_time": last_auto_time.isoformat() if last_auto_time else None,
        "last_error": last_auto_error
    })



if __name__ == '__main__':
    start_auto_snap_thread()
    app.run(host='0.0.0.0', port=8000, threaded=True)
