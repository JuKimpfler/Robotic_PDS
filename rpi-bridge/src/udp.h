/* udp.h — UDP publisher for RPi bridge */
#pragma once

#include <stdint.h>
#include <stddef.h>

/**
 * Open a UDP socket configured to send to a specific host:port.
 * Sets SO_SNDBUF to send_buf_bytes (4 MB recommended).
 * @param host          Destination IP string (e.g. "192.168.137.1")
 * @param port          Destination UDP port (e.g. 9000)
 * @param send_buf_bytes Socket send buffer size in bytes
 * @return              0 on success, -1 on error
 */
int udp_open(const char* host, uint16_t port, int send_buf_bytes);

/**
 * Send a UDP datagram to the configured destination.
 * @param buf  Data buffer
 * @param len  Data length in bytes
 * @return     bytes sent, or -1 on error
 */
ssize_t udp_send(const uint8_t* buf, size_t len);

/** Close the UDP socket. */
void udp_close(void);
