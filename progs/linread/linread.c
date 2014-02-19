#define _GNU_SOURCE

#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <string.h>
#include <sys/time.h>
#include <linux/fs.h>
#include <sys/ioctl.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <malloc.h>

int main(int argc, char *argv[]) {
    
    char *target = argv[1];
    unsigned int i;

    struct timeval readStart, readEnd;
    int hn;
    int BytesPerSector;

    unsigned char *readBuffer;

    if (!target) {
        target = (char *) malloc(strlen(getenv("DEVICE")) + strlen("/dev/"));
        strcpy(target, "/dev/");
        target = strcat(target, getenv("DEVICE"));
    }

    hn = open(target, O_RDONLY|O_SYNC|O_DIRECT);
    ioctl(hn, BLKSSZGET, &BytesPerSector);
    close(hn);
    if (!BytesPerSector) {
        BytesPerSector = 512;
    }

    readBuffer = (unsigned char *) memalign(BytesPerSector, BytesPerSector);
    memset(readBuffer, 0, BytesPerSector);

    hn = open(target, O_RDONLY|O_SYNC|O_DIRECT); 
    lseek(hn, 32768*BytesPerSector, SEEK_SET);
    gettimeofday(&readStart, NULL);
    read(hn, readBuffer, BytesPerSector);
    gettimeofday(&readEnd, NULL);
    close(hn);

    printf("read: ");
    for (i=0; i<BytesPerSector; i++) {
        printf("%.2x ", (unsigned int) readBuffer[i]);
    }
    printf("\n"); 
    printf("start:     %lu.%06lu\n", readStart.tv_sec, readStart.tv_usec);
    printf("end:       %lu.%06lu\n", readEnd.tv_sec, readEnd.tv_usec);
    printf("duration:  %lu.%06lu\n", readEnd.tv_sec-readStart.tv_sec, readEnd.tv_usec-readStart.tv_usec);

    free(readBuffer);
    if (!argv[1]) {
        free(target);
    }

    return 0;
}

