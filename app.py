import os
import subprocess

from flask import Flask, send_from_directory, send_file, render_template, request

app = Flask(__name__)

IMAGES_FOLDER = "images"
CONVERTED_IMAGES_FOLDER = 'converted_images'
IMAGE_NAME = "pair.jpg"
STEREO_EXECUTABLE = "./stereo"


@app.route('/')
def serve_index():
    return send_from_directory('static', 'index.html')


@app.route('/get-image')
def get_image():
    return send_file(os.path.join(CONVERTED_IMAGES_FOLDER, IMAGE_NAME), mimetype='image/jpeg')


@app.route('/admin', methods=['GET', 'POST'])
def admin():
    message = None
    images = [f for f in os.listdir(IMAGES_FOLDER) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]

    if request.method == 'POST':
        filename = request.form.get('image')
        if filename:
            input_path = os.path.join(IMAGES_FOLDER, filename)
            if os.path.exists(input_path):
                try:
                    subprocess.run([STEREO_EXECUTABLE, input_path], check=True)
                    message = f'Изображение {filename} сконвертировано!'
                except subprocess.CalledProcessError:
                    message = f'Ошибка при запуске конвертации'
        else:
            message = 'Файл не найден'

    return render_template('admin.html', images=images, message=message)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
