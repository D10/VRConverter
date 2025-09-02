# Подготовка к запуску
Необходимы установленные Python3.12 и выше, а также C++ 11 и выше

### 1. Переходим в корень проекта

### 2. Компилируем C++ скрипт командой
```bash
g++ converter.cpp -o stereo -O3 -march=native -ffast-math -pthread
```

### 3. Создаем и активируем виртуальное окружение для python
```bash
python -m venv venv
. ./venv/bin activate
```

### 4. Установка python библиотек
```bash
pip3 install -r requirements.txt
```

# Запуск

```bash
python3 app.py
```

# Использование приложения

В корне проекта есть папка "images". В нее складываем исходные изображения, необходимые для конвертации в стереопару

После запуска узнаем адрес устройства внутри локальной сети

```bash
ifconfig | grep 192.
```

Данный адрес позволит открывать страницу приложения с любого устройства, 
которое подключено к той же wi-fi сети, что и хост

Далее открываем админ панель
```bash
http://<адрес хоста>:8000/admin
```

В ней выбираем изображения для вывода изображения и жмем на кнопку "Конвертировать"

После конвертации мы можем открыть страницу с нашим изображением по адресу

```bash
http://<адрес хоста>:8000
```

# Параметризация C++ скрипта

```
./stereo <input_path> [parallax_perc] [layers_count] [zero_parallax_layer_num] [output_mode]
  input_path               путь к входному изображению (jpg/png и т.п.)
  parallax_perc            процент смещения по ширине (double, по умолчанию 0.5)
  layers_count             число слоёв (int, по умолчанию 10)
  zero_parallax_layer_num  слой нулевого параллакса (int, по умолчанию 5)
  output_mode              0=both (по умолчанию), 1=pair только, 2=split только
```

# Параметризация конфигов преобразования изображения (config/config.csv)

```csv
key,value
parallax_perc,0.5
layers_count,10
zero_parallax_layer_num,5
output_mode,both    # both | pair | split
resize_mode,none    # none | fit | exact
target_width,0
target_height,0
jpeg_quality,95     # для ресайза/снимков (Pillow/OpenCV)
auto_snap_enabled,true  # Автоснимок - включить/выключить
auto_snap_interval,5    # Периодичность автоснимка в секундах
auto_snap_convert,true  # Автоматическая конвертация в стереопару после автоснимка - включить/выключить
```
