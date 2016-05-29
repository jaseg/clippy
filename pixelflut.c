
#include <stdlib.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <netdb.h>
#include <string.h>
#include <stdio.h>
#include <unistd.h>
#include <errno.h>

static uint8_t *images[2048] = { 0 };
static int image_count = 0;

int store_image(const uint8_t *img, int w, int h) {
    if (image_count >= sizeof(images)/sizeof(images[0]))
        return -1;
    images[image_count] = malloc(w*h*4);
    memcpy(images[image_count], img, w*h*4);
    return image_count++;
}

int store_image_idx(const uint8_t *img, int w, int h, int idx) {
    if (idx >= sizeof(images)/sizeof(images[0]))
        return -1;
    if (images[idx])
        free(images[idx]);
    images[idx] = malloc(w*h*4);
    memcpy(images[idx], img, w*h*4);
    return 0;
}

void reset_images() {
    for (int i=0; i<image_count; i++) {
        free(images[i]);
        images[i] = NULL;
    }
    image_count = 0;
}

#define PIXEL_FORMAT "PX %zd %zd %02x%02x%02x\n"
int cct(const char *target, int port) {
    printf("Reconnecting %s:%d\n", target, port);
    int sockfd = socket(AF_INET, SOCK_STREAM, 0);
    if (!sockfd) {
        fprintf(stderr, "No sockfd.\n");
        return -1;
    }

    struct sockaddr_in serv_addr; 
    memset(&serv_addr, 0, sizeof(serv_addr)); 
    serv_addr.sin_family = AF_INET;
    serv_addr.sin_port = htons(port); 
    if (inet_pton(AF_INET, target, &serv_addr.sin_addr) != 1) {
        fprintf(stderr, "Address error. \"%s\"\n", target);
        return -2;
    }

    if (connect(sockfd, (struct sockaddr *)&serv_addr, sizeof(serv_addr))) {
        fprintf(stderr, "Connect error.\n");
        return -3;
    }

    return sockfd;
}

int sendframe(int fd, int idx, int w, int h, int ox, int oy) {
    static unsigned long fcnt=0;
//    printf("frame %lu %dx%d @pos %dx%d\n", fcnt++, w, h, ox, oy);
    int fmtlen = snprintf(NULL, 0, PIXEL_FORMAT, (size_t)1000, (size_t)1000, 0xff, 0xff, 0xff);
    char *out = malloc(1400);
    if (!out) {
        fprintf(stderr, "Malloc error.\n");
        return -4;
    }
    char *p = out;
    for (size_t x=0; x<w; x++) {
        for (size_t y=0; y<h; y++) {
            uint8_t *px = images[idx] + (y*w + x)*4;
            uint8_t r = px[0], g = px[1], b = px[2], a = px[3];
            if (a != 255)
                continue;
            size_t cx = ox+x, cy = oy+y;
            p += snprintf(p, fmtlen+1, PIXEL_FORMAT, cx, cy, r, g, b);
            if (p-out > 1400-fmtlen-1) {
                if (send(fd, out, p-out, 0) < 0) {
                    fprintf(stderr, "Send error. %d %s\n", errno, strerror(errno));
                    return -5;
                }
                p = out;
            }
        }
    }
    free(out);
    return 0;
}

void discct(int fd) {
    close(fd);
}
