#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "phase8_tx_file_parser.h"

static int tests = 0;
static void expect(const char *name, const char *frame, int should_pass)
{
    char reason[96] = {0};
    int passed = phase8_validate_file_packet(frame, reason, sizeof(reason));
    printf("%s: %s (%s)\n", name, passed == should_pass ? "PASS" : "FAIL", reason);
    if (passed != should_pass) exit(1);
    ++tests;
}
int main(void)
{
    const char *first  = "02F00100240HELLO WORLD THIS IS OUR MORSE IR FILE TR220";
    const char *second = "02F00200214ANSFER PROJECT039";
    expect("packet 1 (40 chars)", first, 1);
    expect("packet 2 (14 chars)", second, 1);
    char bad[128];
    strcpy(bad, first); bad[11] = 'X';
    expect("corrupted payload checksum rejected", bad, 0);
    strcpy(bad, first); bad[0] = '0'; bad[1] = '3';
    expect("invalid address rejected", bad, 0);
    strcpy(bad, first); bad[3] = '0'; bad[4] = '0'; bad[5] = '0';
    expect("invalid sequence rejected", bad, 0);
    strcpy(bad, first); bad[9] = '3'; bad[10] = '9';
    expect("incorrect payload length rejected", bad, 0);
    strcpy(bad, second); bad[11] = '?';
    expect("unsupported char rejected", bad, 0);
    strcpy(bad, second); bad[strlen(bad)-1] = 'X';
    expect("invalid checksum digits rejected", bad, 0);
    expect("ordinary frame rejected in FILE mode", "02SOS087", 0);
    printf("ALL %d NATIVE TX FILE-PARSER TESTS PASSED\n", tests);
    return 0;
}
