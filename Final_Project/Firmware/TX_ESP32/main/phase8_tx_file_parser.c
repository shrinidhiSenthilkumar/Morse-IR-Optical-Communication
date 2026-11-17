#include "phase8_tx_file_parser.h"

#include <stdio.h>
#include <string.h>

#define PHASE8_CHUNK_SIZE 40U
#define PHASE8_MAX_PACKETS 999U
#define PHASE8_MIN_FRAME 15U /* 11-char header + 1 payload + 3 checksum */
#define PHASE8_MAX_FRAME 54U /* 11-char header + 40 payload + 3 checksum */

static bool fail(char *reason, size_t n, const char *message)
{
    if (reason && n) (void)snprintf(reason, n, "%s", message);
    return false;
}

static bool decimal(const char *s, size_t digits, unsigned *out)
{
    unsigned value = 0;
    for (size_t i = 0; i < digits; ++i) {
        if (s[i] < '0' || s[i] > '9') return false;
        value = value * 10U + (unsigned)(s[i] - '0');
    }
    *out = value;
    return true;
}

bool phase8_validate_file_packet(const char *frame, char *reason,
                                 size_t reason_capacity)
{
    if (!frame) return fail(reason, reason_capacity, "NO PACKET");
    const size_t length = strlen(frame);
    if (length < PHASE8_MIN_FRAME || length > PHASE8_MAX_FRAME)
        return fail(reason, reason_capacity, "INVALID PACKET LENGTH");

    if (!((frame[0] == '0' && frame[1] == '1') ||
          (frame[0] == '0' && frame[1] == '2')) || frame[2] != 'F')
        return fail(reason, reason_capacity, "INVALID ADDRESS OR FILE TYPE");

    unsigned sequence = 0, total = 0, payload_length = 0, received_checksum = 0;
    if (!decimal(frame + 3, 3, &sequence) ||
        !decimal(frame + 6, 3, &total) ||
        !decimal(frame + 9, 2, &payload_length) ||
        !decimal(frame + length - 3, 3, &received_checksum))
        return fail(reason, reason_capacity, "INVALID FILE HEADER OR CHECKSUM");

    if (total == 0 || total > PHASE8_MAX_PACKETS ||
        sequence == 0 || sequence > total)
        return fail(reason, reason_capacity, "INVALID SEQUENCE NUMBER");

    if (payload_length == 0 || payload_length > PHASE8_CHUNK_SIZE ||
        length != 14U + payload_length)
        return fail(reason, reason_capacity, "INVALID PAYLOAD LENGTH");

    if (sequence < total && payload_length != PHASE8_CHUNK_SIZE)
        return fail(reason, reason_capacity, "NON-FINAL PACKET MUST HAVE 40 CHARS");

    for (size_t i = 0; i < payload_length; ++i) {
        const char c = frame[11 + i];
        if (!(c == ' ' || (c >= 'A' && c <= 'Z') ||
              (c >= '0' && c <= '9')))
            return fail(reason, reason_capacity, "UNSUPPORTED PAYLOAD CHARACTER");
    }

    unsigned checksum = 0;
    for (size_t i = 0; i < length - 3; ++i)
        checksum += (unsigned char)frame[i];
    if (received_checksum > 255U || received_checksum != checksum % 256U)
        return fail(reason, reason_capacity, "CHECKSUM MISMATCH");

    if (reason && reason_capacity) (void)snprintf(reason, reason_capacity, "OK");
    return true;
}
