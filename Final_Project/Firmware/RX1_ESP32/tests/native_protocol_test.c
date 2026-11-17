#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "phase8_packet_protocol.h"
static unsigned checksum(const char *s) { unsigned sum=0; for(;*s;s++) sum+=(unsigned char)*s; return sum%256; }
static void make_frame(char *dst, const char *address, unsigned seq, unsigned total, const char *payload){
    char base[100];
    snprintf(base,sizeof base,"%sF%03u%03u%02u%s",address,seq,total,(unsigned)strlen(payload),payload);
    snprintf(dst,120,"%s%03u",base,checksum(base));
}
int main(void){
    phase8_file_state_t s={0}; char a[120],b[120];
    make_frame(a,"01",1,2,"HELLO WORLD THIS IS OUR MORSE IR FILE TR");
    make_frame(b,"01",2,2,"ANSFER PROJECT");
    printf("FRAME 1: %s\nFRAME 2: %s\n",a,b);
    assert(strcmp(a,"01F00100240HELLO WORLD THIS IS OUR MORSE IR FILE TR219")==0);
    assert(strcmp(b,"01F00200214ANSFER PROJECT038")==0);
    assert(!phase8_looks_like_file_frame("01FILE100",9));
    assert(phase8_looks_like_file_frame(a,strlen(a)));
    phase8_packet_result_t r=phase8_accept_frame(&s,a,strlen(a),"01");
    assert(r.status==PHASE8_PACKET_ACCEPTED && s.received==1);
    r=phase8_accept_frame(&s,a,strlen(a),"01");
    assert(r.status==PHASE8_PACKET_DUPLICATE && s.received==1);
    r=phase8_accept_frame(&s,b,strlen(b),"01");
    assert(r.status==PHASE8_PACKET_COMPLETE);
    assert(strcmp(s.text,"HELLO WORLD THIS IS OUR MORSE IR FILE TRANSFER PROJECT")==0);
    phase8_reset_file(&s);
    r=phase8_accept_frame(&s,b,strlen(b),"01");
    assert(r.status==PHASE8_PACKET_REJECTED && !s.active);
    r=phase8_accept_frame(&s,a,strlen(a),"02");
    assert(r.status==PHASE8_PACKET_REJECTED && !s.active);
    a[15]=(a[15]=='X')?'Y':'X';
    r=phase8_accept_frame(&s,a,strlen(a),"02");
    assert(r.status==PHASE8_PACKET_REJECTED && !s.active);
    puts("ALL NATIVE FILE-PROTOCOL TESTS PASSED");
    return 0;
}
