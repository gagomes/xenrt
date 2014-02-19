#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/types.h>

#define DEVICE "/dev/zero"
#define REGION_SIZE 16*1024*1024

int main(void)
{
	int fd;
	void *mem, *lastmem = NULL;

	fd = open(DEVICE, O_RDONLY);
	if ( fd == -1 )
	{
		fprintf(stderr, "failed to open " DEVICE ": %s\n", strerror(errno));
		return 1;
	}

	while (1)
	{
		mem = mmap(0, REGION_SIZE, PROT_READ, MAP_PRIVATE, fd, 0);
		if ( mem == MAP_FAILED )
		{
			fprintf(stderr, "failed to mmap region: %s\n", strerror(errno));
			return 1;
		}

		if ( mprotect(mem, REGION_SIZE, PROT_NONE) < 0 )
		{
			fprintf(stderr, "failed to mprotect region: %s\n", strerror(errno));
			return 1;
		}
		printf("mapped PROT_NONE region at %p.\n", mem);

		/*
                 * Unmap previous region after mapping the next so
                 * there is always at least one PROT_NONE region
                 * mapped.
                 *
                 * If the kernel does not correctly handle non-present
                 * PTEs then it will crash on unmap.
                 */
		if ( lastmem != NULL )
		{
			if ( munmap(lastmem, REGION_SIZE) < 0 )
			{
				fprintf(stderr, "failed to unmap region: %s\n", strerror(errno));
				return 1;
			}

			printf("unmapped PROT_NONE region at %p.\n", lastmem);
		}

		lastmem = mem;

		sleep(1);
	}

	return 0;
}
