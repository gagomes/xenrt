// Program to allocate a specified amount of physical memory
// By Alex Brett
// alex.brett@eu.citrix.com

// Compile with gcc -o usemem usemem.c

#include <stdio.h>
#include <stdlib.h>

int main(int argc, char** argv) {
    int *pointer;
    int bytes, i;

    if (argc != 2) {
        fprintf(stderr, "Usage: %s <number_of_bytes_to_allocate>\n", argv[0]);
        return 1;
    }

    bytes = atoi(argv[1]);

    pointer = malloc(bytes);
    mlock(pointer, bytes);
    for (i=0;i<(bytes / sizeof(bytes));i++)
       pointer[i] = 1;    

    while(1)
    	sleep(30);
}
