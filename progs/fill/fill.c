/*

fill.c

A utility for writing and reading a pattern to a file.

Author: Karl Spalding

*/

#include <stdio.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <stdlib.h>
#include <linux/fs.h>
#include <sys/ioctl.h>

#define TRUE 1 
#define FALSE 0

#define FILL_READ 0
#define FILL_WRITE 1

/* Interval in number of blocks between reporting status messages. */
#define REPORT_INTERVAL 32768 

int main(int argc, char *argv[]) 
{

    char *filename;
    unsigned int pattern;
    int operation;
   
    int fd;
    int blks, blksz;
    
    void *block;

    unsigned int cell = 0;
    long found = 0;
    float proportion = 0;

    int iteration = 0;

    int i, j;

    /*
    Check arguments. Expected usage is:

    fill <file> <pattern> [read|write]

    <file>          A block device to use.
    <pattern>       A four byte hexadecimal pattern.
    [read|write]    Write loops writing the pattern to <file>.
                    Read loops checking <file> for the pattern.

    */

    if ( argc != 4 )
    {
        printf("Usage: %s <file> <pattern> [read|write]\n", argv[0]);
        return EXIT_FAILURE;
    }

    filename = argv[1];
    if ( access(filename, F_OK) )
    {
        printf("Access to %s denied: %s\n", filename, strerror(errno));
        return EXIT_FAILURE;
    }

    if ( !sscanf(argv[2], "%x", &pattern) ) 
    {
        printf("Pattern must be an unsigned hexadecimal integer.\n");
        return EXIT_FAILURE;        
    }
    
    if ( !strcmp(argv[3], "read") )
    {
        operation = FILL_READ;    
    }
    else 
    {
        if ( !strcmp(argv[3], "write") ) 
        {
            operation = FILL_WRITE;
        }
        else
        {
            printf("Only 'read' and 'write' are supported operations.\n");
            return EXIT_FAILURE;
        }
    }
        
    fd = open(filename, O_RDONLY);
    if (!fd) 
    {
        printf("Failed to open %s: %s\n", filename, strerror(errno));
        return EXIT_FAILURE;
    }   
 
    if ( ioctl(fd, BLKGETSIZE, &blks) < 0  )
    {
        printf("BLKGETSIZE on %s failed: %s\n", filename, strerror(errno));
        return EXIT_FAILURE;
    }

    if ( ioctl(fd, BLKSSZGET, &blksz) < 0 )
    {
        printf("BLKSSZGET on %s failed: %s\n", filename, strerror(errno));
        return EXIT_FAILURE;
    }

    if ( close(fd) < 0 )
    {
        printf("Failed to close %s: %s\n", filename, strerror(errno));
        return EXIT_FAILURE;
    }

    /* If a pattern given on the command line doesn't fit in an int then
       we'll get an overflow. This is OK but it might not be what we want
       so warn the user.*/
    if ( pattern == 0xFFFFFFFF )
    {
        printf("Warning: Detected possible pattern overflow.\n");
    }

    printf("Device: %s\nPattern: %x\nOperation: %d\nBlocks: %d\nBlock Size: %d\n", 
            filename, pattern, operation, blks, blksz);

    /*Initialise a block with the pattern.*/
    block = malloc(blksz);
    if ( !block )
    {
        printf("Failed to allocate %d bytes for pattern: %s\n", blksz, strerror(errno));
        return EXIT_FAILURE;
    }

    for (i = 0; i < blksz / sizeof(pattern); i++) 
    {
        memcpy(block + i*sizeof(pattern), &pattern, sizeof(pattern));
    }

    if ( operation == FILL_READ ) 
    {
        printf("Looking for %x in %s...\n", pattern, filename);

        while (TRUE)
        {
            fd = open(filename, O_RDONLY);
            if ( !fd )
            {
                printf("Failed to open %s: %s\n", filename, strerror(errno));
                return EXIT_FAILURE;
            }

            for(i = 0, found = 0; i < blks; i++)
            {
                for (j = 0; j < blksz/sizeof(pattern); j++) 
                {
                    if ( read(fd, &cell, sizeof(pattern)) < 0 )
                    {
                        printf("Error reading from %s: %s\n", filename, strerror(errno));
                        return EXIT_FAILURE;
                    }
                    if ( cell == pattern ) found++;
                }
                if ( !(i % REPORT_INTERVAL) )
                {
                    proportion = (100.0 * (float) found * (float) sizeof(pattern)) / 
                                 ((float) (i + 1) * (float) blksz);
                    printf("Iteration %d %d/%d %.1f%%\n", iteration, i + 1, blks, proportion);
                    if ( fflush(stdout) ) 
                    {
                        printf("Flushing STDOUT failed: %s", strerror(errno));
                    }
                }
            }

            if ( close(fd) < 0 ) 
            {
                printf("Failed to close %s: %s\n", filename, strerror(errno));
                return EXIT_FAILURE;
            }
            iteration++;
        }
    }
    else
    {
        printf("Writing %x to %s...\n", pattern, filename);
    
        while (TRUE) 
        {
            fd = open(filename, O_WRONLY);
            if ( !fd )
            {
                printf("Failed to open %s: %s\n", filename, strerror(errno));
                return EXIT_FAILURE;
            }

            for (i = 0; i < blks; i++)
            {
                if ( write(fd, block, blksz) < 0 ) 
                {
                    printf("Error writing to %s: %s\n", filename, strerror(errno));
                    return EXIT_FAILURE;
                }
                if ( !(i % REPORT_INTERVAL) )
                {                
                    printf("Iteration %d %d/%d\n", iteration, i + 1, blks);
                    if ( fflush(stdout) ) 
                    {
                        printf("Flushing STDOUT failed: %s", strerror(errno));
                    }
                } 
            }
    
            if ( close(fd) < 0 ) 
            {
                printf("Failed to close %s: %s\n", filename, strerror(errno));
                return EXIT_FAILURE;
            }
            iteration++;
        }
    }

    free(block);
    if ( close(fd) < 0 ) 
    {
        printf("Failed to close %s: %s\n", filename, strerror(errno));
        return EXIT_FAILURE;
    }
    return EXIT_SUCCESS;

}
