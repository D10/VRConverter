// converter.cpp
// Генерация стереопары из моно-изображения по яркости (как "глубине").
// Пишет результаты в converted_images/{left.jpg,right.jpg,pair.jpg}.
// Аргументы см. в комментарии в начале файла.

#define STB_IMAGE_IMPLEMENTATION
#define STB_IMAGE_WRITE_IMPLEMENTATION
#define STBI_FAILURE_USERMSG

#include <cstdint>
#include <cstring>
#include <vector>
#include <thread>
#include <algorithm>
#include <iostream>

#include "stb_image.h"
#include "stb_image_write.h"

// ------------------------------------------------------------
// Заполнение "дырок" (прозрачных пикселей по альфа-каналу) построчно
// ------------------------------------------------------------
void fill_rows(uint8_t* image, int width, int height, int start_y, int end_y) {
    const int imgBpp = 4;
    const int stride = width * imgBpp;

    for (int y = start_y; y < end_y; y++) {
        uint8_t* row = image + y * stride;

        int x = 0;
        while (x < width) {
            // пропустить непрозрачные
            while (x < width && row[x * imgBpp + 3] == 255) x++;
            int start = x;

            // найти прозрачный сегмент
            while (x < width && row[x * imgBpp + 3] == 0) x++;
            int end = x;

            if (start == end) continue; // нет дырки
            if (start == 0 && end == width) {
                // строка полностью прозрачная — нечем интерполировать
                continue;
            }

            int left = (start > 0) ? start - 1 : end;          // ближайший слева непрозрачный
            int right = (end < width) ? end : left;            // ближайший справа непрозрачный

            for (int i = start; i < end; i++) {
                uint8_t* dst = row + i * imgBpp;

                if (left == right) {
                    // копировать единственный доступный цвет
                    std::memcpy(dst, row + left * imgBpp, 3);
                } else {
                    // линейная интерполяция между левым и правым пикселями
                    uint8_t* left_pix = row + left * imgBpp;
                    uint8_t* right_pix = row + right * imgBpp;
                    float t = (float)(i - left) / (float)(right - left);
                    for (int c = 0; c < 3; c++) {
                        dst[c] = static_cast<uint8_t>(
                            left_pix[c] * (1.0f - t) + right_pix[c] * t + 0.5f
                        );
                    }
                }
                dst[3] = 255; // сделать непрозрачным
            }
        }
    }
}

void fill_holes(uint8_t* image, int width, int height) {
    std::vector<std::thread> threads;
    int num_threads = (int)std::thread::hardware_concurrency();
    if (num_threads <= 0) num_threads = 1;

    int rows_per_thread = std::max(1, height / num_threads);
    for (int i = 0; i < num_threads; i++) {
        int start_y = i * rows_per_thread;
        int end_y = (i == num_threads - 1) ? height : start_y + rows_per_thread;
        threads.emplace_back(fill_rows, image, width, height, start_y, end_y);
    }
    for (auto& t : threads) t.join();
}

// ------------------------------------------------------------
// Основная обработка строк: раскладка по слоям и смещениям
// Если left != right — пишем 2 изображения (split).
// Если left == right — пишем в "парное" изображение (pair) пополам.
// ------------------------------------------------------------
void process_rows(
    uint8_t* image, uint8_t* left, uint8_t* right,
    uint8_t* left_depths, uint8_t* right_depths,
    int width, int height, int start_y, int end_y,
    int layers_count, int zero_parallax_layer_num,
    double max_shift
) {
    const int srcBpp = 3;   // image RGB
    const int dstBpp = 4;   // RGBA у целевых буферов

    const int imgStride = width * srcBpp;
    const int outStride = width * dstBpp;

    if (left != right) {
        // Режим split: отдельные кадры left/right
        for (int y = start_y; y < end_y; y++) {
            for (int x = 0; x < width; x++) {
                int image_pix_index = y * imgStride + x * srcBpp;

                // Серый как "глубина" (Luma: 0.299 R + 0.587 G + 0.114 B)
                uint8_t depth = (uint8_t)(
                    (77 * image[image_pix_index + 0] +
                     150 * image[image_pix_index + 1] +
                      29 * image[image_pix_index + 2]) >> 8
                );

                int layer_num = (layers_count > 1)
                    ? (depth * layers_count) / 255
                    : 0;

                // Смещение: чем ближе (меньше layer_num относительно zero_parallax_layer_num), тем больше сдвиг
                double shift = max_shift * (1.0 - (double)layer_num / (double)zero_parallax_layer_num);

                int left_x  = x + (int)(shift + 0.5);
                int right_x = x - (int)(shift + 0.5);

                if ((left_x >= 0) && (left_x < width) &&
                    (depth > left_depths[y * width + left_x])) {
                    left_depths[y * width + left_x] = depth;
                    int left_pix_index = y * outStride + left_x * dstBpp;
                    std::memcpy(left + left_pix_index, image + image_pix_index, srcBpp);
                    left[left_pix_index + 3] = 255;
                }

                if ((right_x >= 0) && (right_x < width) &&
                    (depth > right_depths[y * width + right_x])) {
                    right_depths[y * width + right_x] = depth;
                    int right_pix_index = y * outStride + right_x * dstBpp;
                    std::memcpy(right + right_pix_index, image + image_pix_index, srcBpp);
                    right[right_pix_index + 3] = 255;
                }
            }
        }
    } else {
        // Режим pair: одно изображение, левый кадр в левой половине, правый — в правой
        int half_width = width / 2;

        for (int y = start_y; y < end_y; y++) {
            for (int x = 0; x < width; x++) {
                int image_pix_index = y * imgStride + x * srcBpp;

                uint8_t depth = (uint8_t)(
                    (77 * image[image_pix_index + 0] +
                     150 * image[image_pix_index + 1] +
                      29 * image[image_pix_index + 2]) >> 8
                );

                int layer_num = (layers_count > 1)
                    ? (depth * layers_count) / 255
                    : 0;

                double shift = max_shift * (1.0 - (double)layer_num / (double)zero_parallax_layer_num);

                int left_x  = (x + (int)(shift + 0.5)) / 2;
                int right_x = (x - (int)(shift + 0.5)) / 2 + half_width;

                if ((left_x >= 0) && (left_x < half_width) &&
                    (depth > left_depths[y * half_width + left_x])) {
                    left_depths[y * half_width + left_x] = depth;
                    int left_pix_index = y * outStride + left_x * dstBpp;
                    std::memcpy(left + left_pix_index, image + image_pix_index, srcBpp);
                    left[left_pix_index + 3] = 255;
                }

                if ((right_x >= half_width) && (right_x < width) &&
                    (depth > right_depths[y * half_width + (right_x - half_width)])) {
                    right_depths[y * half_width + (right_x - half_width)] = depth;
                    int right_pix_index = y * outStride + right_x * dstBpp;
                    std::memcpy(right + right_pix_index, image + image_pix_index, srcBpp);
                    right[right_pix_index + 3] = 255;
                }
            }
        }
    }
}

// ------------------------------------------------------------
// Создать два изображения: left.jpg/right.jpg
// ------------------------------------------------------------
void create_stereo_pair(uint8_t* image, int width, int height,
                        int layers_count, int zero_parallax_layer_num,
                        double parallax_perc) {
    const int pcount = width * height;

    uint8_t* left  = new (std::nothrow) uint8_t[pcount * 4];
    uint8_t* right = new (std::nothrow) uint8_t[pcount * 4];
    uint8_t* left_depths  = new (std::nothrow) uint8_t[pcount];
    uint8_t* right_depths = new (std::nothrow) uint8_t[pcount];

    if (!left || !right || !left_depths || !right_depths) {
        if (left) delete[] left;
        if (right) delete[] right;
        if (left_depths) delete[] left_depths;
        if (right_depths) delete[] right_depths;
        std::cerr << "Failed to allocate memory\n";
        return;
    }

    std::memset(left, 0, pcount * 4);
    std::memset(right, 0, pcount * 4);
    std::memset(left_depths, 0, pcount);
    std::memset(right_depths, 0, pcount);

    double max_shift = (double)width * parallax_perc / 100.0;

    // Многопоточный проход строк
    std::vector<std::thread> threads;
    int num_threads = (int)std::thread::hardware_concurrency();
    if (num_threads <= 0) num_threads = 1;
    int rows_per_thread = std::max(1, height / num_threads);

    for (int i = 0; i < num_threads; i++) {
        int start_y = i * rows_per_thread;
        int end_y = (i == num_threads - 1) ? height : start_y + rows_per_thread;
        threads.emplace_back(process_rows,
            image, left, right,
            left_depths, right_depths,
            width, height, start_y, end_y,
            layers_count, zero_parallax_layer_num, max_shift
        );
    }
    for (auto& t : threads) t.join();

    delete[] left_depths;
    delete[] right_depths;

    // Постпроцесс: заливка дырок и запись
    std::thread left_write([&](){
        fill_holes(left, width, height);
        stbi_write_jpg("converted_images/left.jpg", width, height, 4, left, 100);
    });
    std::thread right_write([&](){
        fill_holes(right, width, height);
        stbi_write_jpg("converted_images/right.jpg", width, height, 4, right, 100);
    });

    left_write.join();
    right_write.join();

    delete[] left;
    delete[] right;
}

// ------------------------------------------------------------
// Создать одно изображение pair.jpg (левая и правая половины)
// ------------------------------------------------------------
void create_stereo_pair_H(uint8_t* image, int width, int height,
                          int layers_count, int zero_parallax_layer_num,
                          double parallax_perc) {
    const int pcount = width * height;

    uint8_t* pair        = new (std::nothrow) uint8_t[pcount * 4];
    uint8_t* pair_depths = new (std::nothrow) uint8_t[pcount];

    if (!pair || !pair_depths) {
        if (pair) delete[] pair;
        if (pair_depths) delete[] pair_depths;
        std::cerr << "Failed to allocate memory\n";
        return;
    }

    std::memset(pair, 0, pcount * 4);
    std::memset(pair_depths, 0, pcount);

    double max_shift = (double)width * parallax_perc / 100.0;

    // Многопоточный проход строк (left==right => pair)
    std::vector<std::thread> threads;
    int num_threads = (int)std::thread::hardware_concurrency();
    if (num_threads <= 0) num_threads = 1;
    int rows_per_thread = std::max(1, height / num_threads);

    for (int i = 0; i < num_threads; i++) {
        int start_y = i * rows_per_thread;
        int end_y = (i == num_threads - 1) ? height : start_y + rows_per_thread;
        threads.emplace_back(process_rows,
            image, pair, pair,
            pair_depths, pair_depths,
            width, height, start_y, end_y,
            layers_count, zero_parallax_layer_num, max_shift
        );
    }
    for (auto& t : threads) t.join();

    delete[] pair_depths;

    std::thread pair_write([&](){
        fill_holes(pair, width, height);
        stbi_write_jpg("converted_images/pair.jpg", width, height, 4, pair, 100);
    });

    pair_write.join();
    delete[] pair;
}

// ------------------------------------------------------------
// main: парсинг аргументов и запуск нужных режимов
// ------------------------------------------------------------
int main(int argc, char **argv) {
    if (argc < 2) {
        std::cerr << "image path required\n";
        std::cerr << "usage: ./stereo <input_path> [parallax_perc] [layers_count] [zero_parallax_layer_num] [output_mode]\n";
        return 1;
    }

    // Значения по умолчанию
    double parallax_perc = 0.5;
    int layers_count = 10;
    int zero_parallax_layer_num = 5;
    int output_mode = 0; // 0=both, 1=pair only, 2=split only

    if (argc > 2) parallax_perc = std::atof(argv[2]);
    if (argc > 3) layers_count = std::max(1, std::atoi(argv[3]));
    if (argc > 4) zero_parallax_layer_num = std::max(1, std::atoi(argv[4]));
    if (argc > 5) output_mode = std::atoi(argv[5]);

    // Загрузка входного изображения (приводим к 3 каналам RGB)
    int width = 0, height = 0, channels = 0;
    uint8_t* image = stbi_load(argv[1], &width, &height, &channels, 3);
    if (!image) {
        std::cerr << "Failed to load image: " << argv[1] << "\n"
                  << stbi_failure_reason() << std::endl;
        return 1;
    }

    // Создание выходов в зависимости от режима
    if (output_mode == 0 || output_mode == 2) {
        create_stereo_pair(image, width, height, layers_count, zero_parallax_layer_num, parallax_perc);
    }
    if (output_mode == 0 || output_mode == 1) {
        create_stereo_pair_H(image, width, height, layers_count, zero_parallax_layer_num, parallax_perc);
    }

    stbi_image_free(image);
    return 0;
}
