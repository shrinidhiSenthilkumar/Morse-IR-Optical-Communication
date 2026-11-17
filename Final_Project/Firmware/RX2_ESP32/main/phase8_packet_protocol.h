#ifndef PHASE8_PACKET_PROTOCOL_H
#define PHASE8_PACKET_PROTOCOL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define PHASE8_CHUNK_SIZE 40U
#define PHASE8_MAX_PACKETS 999U

/* State for one incomplete / completed text file on RX2. */
typedef struct {
    char *text;                /* Allocated storage, contiguous after completion */
    uint8_t *seen;             /* Per-packet reception bitmap */
    uint8_t *lengths;          /* Valid data bytes in each 40-byte slot */
    unsigned int total;
    unsigned int received;
    size_t reconstructed_length;
    bool active;
    bool complete;
} phase8_file_state_t;

typedef enum {
    PHASE8_PACKET_REJECTED = 0,
    PHASE8_PACKET_ACCEPTED,
    PHASE8_PACKET_COMPLETE,
    PHASE8_PACKET_DUPLICATE
} phase8_packet_status_t;

typedef struct {
    phase8_packet_status_t status;
    unsigned int sequence;
    unsigned int total;
    unsigned int received;
    char detail[96];
} phase8_packet_result_t;

/* Distinguishes file headers such as '02F001...' from legacy text '02FILE...'. */
bool phase8_looks_like_file_frame(const char *frame, size_t length);

/* Accepts the FULL frame including destination and three checksum digits.
   Rechecks destination and checksum; stores payload only on success. */
phase8_packet_result_t phase8_accept_frame(phase8_file_state_t *state,
                                          const char *frame,
                                          size_t length,
                                          const char *receiver_address);

/* Release all buffered data, including incomplete transfer state. */
void phase8_reset_file(phase8_file_state_t *state);

#endif
