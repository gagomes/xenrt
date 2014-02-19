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
    unsigned int pattern;

    struct timeval writeStart, writeEnd;
    int hn;
    int BytesPerSector;

    unsigned char *writeBuffer;

    if (!target) {
        target = (char *) malloc(strlen(getenv("DEVICE")) + strlen("/dev/"));
        strcpy(target, "/dev/");
        target = strcat(target, getenv("DEVICE"));
    }

    hn = open(target, O_RDONLY);
    ioctl(hn, BLKSSZGET, &BytesPerSector);
    close(hn);
    if (!BytesPerSector) {
        BytesPerSector = 512;
    }

    writeBuffer = (unsigned char *) memalign(BytesPerSector, BytesPerSector);
    memset(writeBuffer, 0, BytesPerSector);

    srand(time(NULL));
    pattern = rand();
    memcpy(writeBuffer, &pattern, sizeof(pattern));

    hn = open(target, O_WRONLY|O_CREAT|O_SYNC|O_DIRECT); 
    lseek(hn, 32768*BytesPerSector, SEEK_SET);
    gettimeofday(&writeStart, NULL);
    write(hn, writeBuffer, BytesPerSector);
    gettimeofday(&writeEnd, NULL);
    close(hn);

    printf("write: ");
    for (i=0; i<BytesPerSector; i++) {
        printf("%.2x ", (unsigned int) writeBuffer[i]);
    }
    printf("\n");
    printf("start:    %lu.%06lu\n", writeStart.tv_sec, writeStart.tv_usec);
    printf("end:      %lu.%06lu\n", writeEnd.tv_sec, writeEnd.tv_usec);
    printf("duration: %lu.%06lu\n", writeEnd.tv_sec-writeStart.tv_sec, writeEnd.tv_usec-writeStart.tv_usec);

    free(writeBuffer);
    if (!argv[1]) {
        free(target);
    }

    return 0;
}

