#include "phase8_packet_protocol.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static bool ascii_digit(char c)
{
    return c >= '0' && c <= '9';
}

static bool parse_decimal(const char *s, unsigned int count, unsigned int *out)
{
    unsigned int value = 0;
    for (unsigned int i = 0; i < count; ++i) {
        if (!ascii_digit(s[i])) return false;
        value = value * 10U + (unsigned int)(s[i] - '0');
    }
    *out = value;
    return true;
}

static phase8_packet_result_t result_error(const char *message)
{
    phase8_packet_result_t r = {0};
    r.status = PHASE8_PACKET_REJECTED;
    (void)snprintf(r.detail, sizeof(r.detail), "%s", message);
    return r;
}

bool phase8_looks_like_file_frame(const char *frame, size_t length)
{
    return frame && length >= 6 && frame[2] == 'F' &&
           ascii_digit(frame[3]) && ascii_digit(frame[4]) &&
           ascii_digit(frame[5]);
}

void phase8_reset_file(phase8_file_state_t *state)
{
    if (!state) return;
    free(state->text);
    free(state->seen);
    free(state->lengths);
    memset(state, 0, sizeof(*state));
}

static bool start_file(phase8_file_state_t *state, unsigned int total)
{
    /* Call only after all packet validation has succeeded. */
    phase8_reset_file(state);
    const size_t capacity = (size_t)total * PHASE8_CHUNK_SIZE + 1U;
    state->text = (char *)calloc(capacity, 1U);
    state->seen = (uint8_t *)calloc(total, sizeof(uint8_t));
    state->lengths = (uint8_t *)calloc(total, sizeof(uint8_t));
    if (!state->text || !state->seen || !state->lengths) {
        phase8_reset_file(state);
        return false;
    }
    state->total = total;
    state->active = true;
    return true;
}

phase8_packet_result_t phase8_accept_frame(phase8_file_state_t *state,
                                          const char *frame,
                                          size_t length,
                                          const char *receiver_address)
{
    if (!state || !frame || !receiver_address || strlen(receiver_address) != 2)
        return result_error("INVALID ARGUMENT");
    if (length < 14 || length > (14U + PHASE8_CHUNK_SIZE))
        return result_error("INVALID FILE FRAME LENGTH");
    if (!phase8_looks_like_file_frame(frame, length))
        return result_error("NOT A FILE FRAME");
    if (frame[0] != receiver_address[0] || frame[1] != receiver_address[1])
        return result_error("WRONG ADDRESS");

    unsigned int seq = 0, total = 0, chunk_length = 0, supplied_checksum = 0;
    if (!parse_decimal(frame + 3, 3, &seq) ||
        !parse_decimal(frame + 6, 3, &total) ||
        !parse_decimal(frame + 9, 2, &chunk_length) ||
        !parse_decimal(frame + length - 3, 3, &supplied_checksum))
        return result_error("INVALID FILE HEADER OR CHECKSUM");
    if (total == 0 || total > PHASE8_MAX_PACKETS || seq == 0 || seq > total)
        return result_error("INVALID FILE SEQUENCE");
    if (chunk_length == 0 || chunk_length > PHASE8_CHUNK_SIZE ||
        length != 14U + chunk_length)
        return result_error("INVALID FILE DATA LENGTH");
    /* All chunks except the final chunk must be 40 bytes for this format. */
    if (seq < total && chunk_length != PHASE8_CHUNK_SIZE)
        return result_error("NON-FINAL CHUNK MUST BE 40 CHARS");

    for (unsigned int i = 0; i < chunk_length; ++i) {
        const unsigned char c = (unsigned char)frame[11 + i];
        if (!(c == ' ' || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9')))
            return result_error("UNSUPPORTED FILE CHARACTER");
    }

    unsigned int actual_checksum = 0;
    for (size_t i = 0; i < length - 3; ++i)
        actual_checksum += (unsigned char)frame[i];
    actual_checksum %= 256U;
    if (supplied_checksum != actual_checksum)
        return result_error("CHECKSUM MISMATCH");

    if (!state->active || state->complete) {
        if (seq != 1)
            return result_error("EXPECTED FIRST PACKET 001");
        if (!start_file(state, total))
            return result_error("NOT ENOUGH MEMORY");
    } else if (state->total != total) {
        if (seq != 1) return result_error("INCONSISTENT TOTAL COUNT");
        if (!start_file(state, total)) return result_error("NOT ENOUGH MEMORY");
    }

    phase8_packet_result_t out = {0};
    out.sequence = seq;
    out.total = total;
    out.received = state->received;

    const unsigned int idx = seq - 1U;
    char *slot = state->text + (size_t)idx * PHASE8_CHUNK_SIZE;
    if (state->seen[idx]) {
        if (state->lengths[idx] == chunk_length &&
            memcmp(slot, frame + 11, chunk_length) == 0) {
            out.status = PHASE8_PACKET_DUPLICATE;
            (void)snprintf(out.detail, sizeof(out.detail), "DUPLICATE PACKET IGNORED");
            return out;
        }
        /* An inconsistent duplicate must not corrupt a partially saved file. */
        phase8_reset_file(state);
        return result_error("CONFLICTING DUPLICATE - FILE DISCARDED");
    }

    memcpy(slot, frame + 11, chunk_length);
    state->lengths[idx] = (uint8_t)chunk_length;
    state->seen[idx] = 1;
    ++state->received;
    out.received = state->received;

    if (state->received != state->total) {
        out.status = PHASE8_PACKET_ACCEPTED;
        (void)snprintf(out.detail, sizeof(out.detail), "PACKET VERIFIED AND STORED");
        return out;
    }

    /* All numbered packets are present: compact 40-byte slots in sequence. */
    size_t pos = 0;
    for (unsigned int i = 0; i < state->total; ++i) {
        if (!state->seen[i]) return result_error("MISSING FILE PACKET");
        const size_t n = state->lengths[i];
        memmove(state->text + pos, state->text + (size_t)i * PHASE8_CHUNK_SIZE, n);
        pos += n;
    }
    state->text[pos] = '\0';
    state->reconstructed_length = pos;
    state->complete = true;
    out.status = PHASE8_PACKET_COMPLETE;
    (void)snprintf(out.detail, sizeof(out.detail), "FILE RECONSTRUCTED");
    return out;
}
