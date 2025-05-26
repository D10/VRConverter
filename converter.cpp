#define STB_IMAGE_IMPLEMENTATION
#define STB_IMAGE_WRITE_IMPLEMENTATION
#define STBI_FAILURE_USERMSG

#include <vector>
#include <iostream>
#include "stb_image.h"
#include "stb_image_write.h"
#include <thread>



/*
    Для заполнения дырок
*/
void fill_rows(uint8_t* image, int width, int height, int start_y, int end_y) {
    int imgBpp = 4;
    int stride = width * imgBpp;

    for (int y = start_y; y < end_y; y++) {
        uint8_t* row = image + y*stride;
        
        int x = 0;
        while (x < width) {
            // начало дырки
            while(x < width && row[x*imgBpp + 3] == 255) x++;
            int start = x;

            // конец дырки
            while (x < width && row[x*imgBpp + 3] == 0) x++;
            int end = x;

            if (start == 0 && end == width) continue;

            int left = (start > 0) ? start - 1: end;
            int right = (end < width) ? end : left;

            for (int i = start; i < end; i++) {
                uint8_t* dst = row + i*imgBpp;

                if (left == right) memcpy(dst, row + left*imgBpp, 3);
                else {
                    // Градиент между left и right
                    uint8_t* left_pix = row + left * imgBpp;
                    uint8_t* right_pix = row + right * imgBpp;
                    float t = (float)(i - left) / (right - left);

                    for (int c = 0; c < 3; c++) {
                        dst[c] = static_cast<uint8_t>(
                            left_pix[c] * (1 - t) + right_pix[c] * t + 0.5f
                        );
                    }
                }

                dst[3] = 255;
            }

        }
    }
}

void fill_holes(uint8_t* image, int width, int height) {
    std::vector<std::thread> threads;
    int num_threads = std::thread::hardware_concurrency();
    if (num_threads == 0) num_threads = 1;
    int rows_per_thread = height / num_threads;


    for (int i = 0; i < num_threads; i++) {
        int start_y = i * rows_per_thread;
        int end_y = (i == num_threads - 1) ? height : start_y + rows_per_thread;

        threads.emplace_back(fill_rows, image, width, height, start_y, end_y);
    }

    for (auto& t : threads) {
        t.join();
    }
}




// Вырезка слоев и создание стереопары
void process_rows(
    uint8_t* image, uint8_t* left, uint8_t* right,
    uint8_t* left_depths, uint8_t* right_depths,
    int width, int height, int start_y, int end_y,
    int layers_count, int zero_parallax_layer_num,
    double max_shift
) {
    int imgBpp = 3;
    int leftBpp = 4;

    int imgStride = width*imgBpp;
    int leftStride = width*leftBpp;


    // если нужно 2 изображения 
    if (left != right) {
        for (int y = start_y; y < end_y; y++) {
            for (int x = 0; x < width; x++) {
                int image_pix_index = y*imgStride + x*imgBpp;

                uint8_t depth = (uint8_t)(
                    (77 * image[image_pix_index + 0] +
                    150 * image[image_pix_index + 1] +
                    29 * image[image_pix_index + 2]) >> 8
                );


                int layer_num = depth * layers_count / 255;
                double shift = max_shift*(1 - (double) layer_num / zero_parallax_layer_num);


                int left_x = x + (int)(shift + 0.5);
                int right_x = x - (int)(shift + 0.5);

                if ((left_x >= 0) && (left_x < width) && (depth > left_depths[y*width + left_x])) {
                    left_depths[y*width + left_x] = depth;

                    int left_pix_index = y*leftStride + left_x*leftBpp;
                    memcpy(left + left_pix_index, image + image_pix_index, imgBpp);
                    left[left_pix_index + 3] = 255;
                }

                if ((right_x >= 0) && (right_x < width) && (depth > right_depths[y*width + right_x])) {
                    right_depths[y*width + right_x] = depth;

                    int right_pix_index = y*leftStride + right_x*leftBpp;
                    memcpy(right + right_pix_index, image + image_pix_index, imgBpp);
                    right[right_pix_index + 3] = 255;
                }
            }
        }
        // если в одно изображение
    } else {
        int half_width = width / 2;

        for (int y = start_y; y < end_y; y++) {
            for (int x = 0; x < width; x++) {
                int image_pix_index = y*imgStride + x*imgBpp;

                uint8_t depth = (uint8_t)(
                    (77 * image[image_pix_index + 0] +
                    150 * image[image_pix_index + 1] +
                    29 * image[image_pix_index + 2]) >> 8
                );


                int layer_num = depth * layers_count / 255;
                double shift = max_shift*(1 - (double) layer_num / zero_parallax_layer_num);


                int left_x = (x + (int)(shift + 0.5)) / 2;
                int right_x = (x - (int)(shift + 0.5)) / 2 + half_width;

                if ((left_x >= 0) && (left_x < half_width) && (depth > left_depths[y*half_width + left_x])) {
                    left_depths[y*half_width + left_x] = depth;

                    int left_pix_index = y*leftStride + left_x*leftBpp;
                    memcpy(left + left_pix_index, image + image_pix_index, imgBpp);
                    left[left_pix_index + 3] = 255;
                }

                if ((right_x >= half_width) && (right_x < width) && (depth > right_depths[y*half_width + right_x - half_width])) {
                    right_depths[y*half_width + right_x - half_width] = depth;

                    int right_pix_index = y*leftStride + right_x*leftBpp;
                    memcpy(right + right_pix_index, image + image_pix_index, imgBpp);
                    right[right_pix_index + 3] = 255;
                }
            }
        }
    }
}


// Для создания стереопары (создает 2 изображения)
void create_stereo_pair(uint8_t* image, int width, int height, int layers_count, int zero_parallax_layer_num, double parallax_perc) {
    int pcount = width*height;

    uint8_t* left = new uint8_t[pcount*4];
    uint8_t* left_depths = new uint8_t[pcount];
    
    uint8_t* right = new uint8_t[pcount*4];
    uint8_t* right_depths = new uint8_t[pcount];


    if (!left || !right || !left_depths || !right_depths) {
        if (left) delete [] left;
        if (right) delete [] right;
        if (left_depths) delete [] left_depths;
        if (right_depths) delete [] right_depths;

        std::cerr << "Failed to allocate mem" << std::endl;
        return;
    }


    // Заполняем нулями
    memset(left, 0, pcount*4);
    memset(left_depths, 0, pcount);

    memset(right, 0, pcount*4);
    memset(right_depths, 0, pcount);


    double max_shift = width * parallax_perc / 100;
    

    std::vector<std::thread> threads;
    int num_threads = std::thread::hardware_concurrency();
    if (num_threads == 0) num_threads = 1;
    int rows_per_thread = height / num_threads;

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

    for (auto& t : threads) {
        t.join();
    }


    delete [] left_depths;
    delete [] right_depths;


    

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
    

    delete [] left;
    delete [] right;
}





// Для создани стереопары (на выходе 1 изображение)
void create_stereo_pair_H(uint8_t* image, int width, int height, int layers_count, int zero_parallax_layer_num, double parallax_perc) {
    int pcount = width*height;

    uint8_t* pair = new uint8_t[pcount*4];
    uint8_t* pair_depths = new uint8_t[pcount];
    

    if (!pair || !pair_depths) {
        if (pair) delete [] pair;
        if (pair_depths) delete [] pair_depths;

        std::cerr << "Failed to allocate mem" << std::endl;
        return;
    }


    // Заполняем нулями
    memset(pair, 0, pcount*4);
    memset( pair_depths, 0, pcount);



    double max_shift = width * parallax_perc / 100;
    

    std::vector<std::thread> threads;
    int num_threads = std::thread::hardware_concurrency();
    if (num_threads == 0) num_threads = 1;
    int rows_per_thread = height / num_threads;

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

    for (auto& t : threads) {
        t.join();
    }


    delete [] pair_depths;


    

    std::thread pair_write([&](){
        fill_holes(pair, width, height);
        stbi_write_jpg("converted_images/pair.jpg", width, height, 4, pair, 100);
    });
 

    pair_write.join();
    

    delete [] pair;
}





int main(int argc, char **argv) {
    if (argc < 2) {
        std::cerr << "image path required" << std::endl;
        return 1;
    }

    // Загружаем изображение
    int width, height, channels;
    double parallax_perc = 0.5;


    uint8_t* image = stbi_load(argv[1], &width, &height, &channels, 3);
    if (!image) {
        std::cerr << "Failed to load image: " << argv[1] << "\n" <<  stbi_failure_reason() << std::endl;
        return 1;
    }


    if (argc > 2) {
        parallax_perc = std::atof(argv[2]);
    }

    create_stereo_pair(image, width, height, 10, 5, parallax_perc);
    create_stereo_pair_H(image, width, height, 10, 5, parallax_perc);


    stbi_image_free(image);
    return 0;
}