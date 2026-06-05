/* udp.c — UDP publisher (RPi → PC) */

#include "udp.h"
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <errno.h>

static int                s_sockfd = -1;
static struct sockaddr_in s_dest;

int udp_open(const char* host, uint16_t port, int send_buf_bytes) {
    s_sockfd = socket(AF_INET, SOCK_DGRAM, 0);
    if (s_sockfd < 0) {
        perror("udp_open: socket");
        return -1;
    }

    // Set send buffer (4 MB by default)
    if (setsockopt(s_sockfd, SOL_SOCKET, SO_SNDBUF,
                   &send_buf_bytes, sizeof(send_buf_bytes)) < 0) {
        perror("udp_open: SO_SNDBUF (non-fatal)");
        // Non-fatal — continue
    }

    memset(&s_dest, 0, sizeof(s_dest));
    s_dest.sin_family      = AF_INET;
    s_dest.sin_port        = htons(port);
    if (inet_pton(AF_INET, host, &s_dest.sin_addr) <= 0) {
        fprintf(stderr, "udp_open: invalid host address: %s\n", host);
        close(s_sockfd);
        s_sockfd = -1;
        return -1;
    }

    return 0;
}

ssize_t udp_send(const uint8_t* buf, size_t len) {
    if (s_sockfd < 0) return -1;
    ssize_t sent = sendto(s_sockfd, buf, len, 0,
                          (struct sockaddr*)&s_dest, sizeof(s_dest));
    if (sent < 0) {
        perror("udp_send: sendto");
    }
    return sent;
}

void udp_close(void) {
    if (s_sockfd >= 0) {
        close(s_sockfd);
        s_sockfd = -1;
    }
}
