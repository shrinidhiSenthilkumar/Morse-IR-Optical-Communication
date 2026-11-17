#ifndef PHASE8_TX_FILE_PARSER_H
#define PHASE8_TX_FILE_PARSER_H

#include <stdbool.h>
#include <stddef.h>

/* Validate a complete [addr:2][F][seq:3][total:3][len:2]
 * [payload:1..40][checksum:3] packet. Does not change the frame.
 * No extra checksum or receiver address may be added by the transmitter.
 */
bool phase8_validate_file_packet(const char *frame, char *reason,
                                 size_t reason_capacity);

#endif
