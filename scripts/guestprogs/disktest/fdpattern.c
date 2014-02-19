/*
 * XenRT: Small disk test utility. We write the sector number to
 * to each successive sector. The verify flag checks for incorrect
 * sector entries.
 *
 * Julian Chesterfield, July 2007
 *
 * Copyright (c) 2007 XenSource, Inc. All use and distribution of this
 * copyrighted material is governed by and subject to terms and
 * conditions as licensed by XenSource, Inc. All other rights reserved.
 *
 */


#ifndef _GNU_SOURCE
  #define _GNU_SOURCE
#endif
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/ioctl.h>
#include <linux/fs.h>
#include <string.h>
#include "atomicio.h"

#define DEFAULT_SECTOR_SIZE 512
#define SECTOR_SHIFT 9

unsigned long long iter = 0;

struct fd_state {
        unsigned long      sector_size;
        unsigned long long size;
	unsigned long long size_sects;
	unsigned long long fullsize;
};

struct sector_hdr {
	unsigned long long sect;
	unsigned long long iter;
};

int usage(char *str) {
	fprintf(stderr, "usage: %s {write|verify} <FILENAME> <ITERATION NO> "
		"[-r random] [-p percent] [-s seed]\n", str);
	exit(1);
}

void fill_buf(char *buf, struct sector_hdr *hdr, int size) {
	int i;
	for(i=0; i<(size/sizeof(struct sector_hdr)); i++)
		memcpy(buf + (sizeof(struct sector_hdr) * i), hdr, sizeof(struct sector_hdr));
}

static int getsize(int fd, struct fd_state *s) {
        struct stat stat;
	int ret;

        ret = fstat(fd, &stat);
        if (ret != 0) {
                fprintf(stderr, "ERROR: fstat failed, Couldn't stat image");
                return -EINVAL;
        }

	if (S_ISBLK(stat.st_mode)) {
                /*Accessing block device directly*/
                s->size = 0;
                if (ioctl(fd,BLKGETSIZE,&s->size)!=0) {
                        fprintf(stderr,"ERR: BLKGETSIZE failed, "
                                 "couldn't stat image");
                        return -EINVAL;
                }
		s->size_sects = s->size;
                /*Get the sector size*/
#if defined(BLKSSZGET)
                {
                        s->sector_size = DEFAULT_SECTOR_SIZE;
                        ioctl(fd, BLKSSZGET, &s->sector_size);
                }
#else
                s->sector_size = DEFAULT_SECTOR_SIZE;
#endif
		if (s->sector_size != DEFAULT_SECTOR_SIZE) {
			if (s->sector_size > DEFAULT_SECTOR_SIZE) {
				s->size_sects = 
					(s->sector_size/DEFAULT_SECTOR_SIZE)*s->size;
			} else {
				s->size_sects = 
					s->size/(DEFAULT_SECTOR_SIZE/s->sector_size);
			}
		}
		s->fullsize = s->sector_size * s->size;

        } else {
                /*Local file? try fstat instead*/
                s->size = (stat.st_size >> SECTOR_SHIFT);
                s->sector_size = DEFAULT_SECTOR_SIZE;
		s->size_sects = s->size;
		s->fullsize = stat.st_size;
        }
        return 0;
}

int verify_testpattern(int fd, struct fd_state *state, int sparse) {
	int running = 1, len, ret, j;
	unsigned long long sects, i;
	struct sector_hdr *test, zero_hdr;
	char *buf;

	memset(&zero_hdr, 0, sizeof(struct sector_hdr));

	buf = malloc(DEFAULT_SECTOR_SIZE);
	if (!buf) {
		fprintf(stderr, "Malloc failed\n");
		return -1;
	}
	sects = state->size_sects;
	ret = i = 0;
        while (running) {

		if (!(i % 1048576)) {
			printf("Verifying sector %llu of %llu\n", i, sects);
		}
		
		/*Attempt to read the data*/
		if (lseek(fd, i * DEFAULT_SECTOR_SIZE, SEEK_SET)==(off_t)-1) {
			fprintf(stderr,"Unable to seek to offset %llu (%d)\n",
				i * DEFAULT_SECTOR_SIZE, errno);
			return -1;
		}
		len = atomicio(read, fd, buf, DEFAULT_SECTOR_SIZE);
		if (len < DEFAULT_SECTOR_SIZE) {
			fprintf(stderr, "Read failed %llu\n",
				 (long long unsigned) i);
			return -1;
		}
		for(j=0; j<DEFAULT_SECTOR_SIZE/sizeof(struct sector_hdr); j++) {
			test = (struct sector_hdr *)(buf + (sizeof(struct sector_hdr) * j));

			if (sparse &&
			    !memcmp(test, &zero_hdr, sizeof(struct sector_hdr)))
				continue;

			if (test->sect != i) {
				printf("Val is %llu\n",test->sect);
				fprintf(stderr, "Sector %llu, off %d:\n"
					"Sector number does not match\n",
					(long long unsigned) i, (sizeof(struct sector_hdr) * j));
				return 1;
			}
			if (test->iter != iter) {
				fprintf(stderr, "Sector %llu, off %d:\n"
					"Iteration number does not match\n",
					(long long unsigned) i, (sizeof(struct sector_hdr) * j));
				return 2;				
			}
		}

		i++;
		if (i >= sects)
			running = 0;
	}
	free(buf);
	return ret;
}

int write_testpattern(int fd, struct fd_state *state, int random, int percent) {
	int running = 1, len;
	unsigned long long sects, sec, i;
	struct sector_hdr hdr;
	char *buf;
	void *vbuf;

	if (posix_memalign(&vbuf, DEFAULT_SECTOR_SIZE, DEFAULT_SECTOR_SIZE)) {
		fprintf(stderr, "Malloc failed\n");
		return -1;
	}

	buf   = (char *)vbuf;
	sects = state->size_sects;
	if (random)
		sects *= ((float)percent / 100);

	i = 0;
        while (running) {
	
		if (!(i % 1048576)) {
			printf("Writing sector %llu of %llu\n", i, sects);
		}

		if (random)
			sec = lrand48() % state->size_sects;
		else
			sec = i;

		/*Attempt to write the data*/
		if (lseek(fd, sec * DEFAULT_SECTOR_SIZE, SEEK_SET)==(off_t)-1) {
			fprintf(stderr,"Unable to seek to offset %llu\n",
				sec * DEFAULT_SECTOR_SIZE);
			return -1;
		}
		hdr.sect = sec;
		hdr.iter = iter;
		fill_buf(buf, &hdr, DEFAULT_SECTOR_SIZE);
		len = atomicio(vwrite, fd, buf, DEFAULT_SECTOR_SIZE);
		if (len < DEFAULT_SECTOR_SIZE) {
			fprintf(stderr, "Write failed %llu\n", sec);
			return -1;
		}

		i++;
		if (i >= sects)
			running = 0;
	}
	free(buf);
	return 0;
}

int main(int argc, char *argv[])
{
	struct fd_state state;
	char *target, *mode, *tag, *app;
	int c, fd, retval, o_flags, random, percent, seed;

	if (argc < 4)
		usage(argv[0]);

	app     = argv[0];
	mode    = argv[1];
	target  = argv[2];
	tag     = argv[3];

	fd      = -1;
	retval  = 0;
	random  = 0;
	percent = 10;
	seed    = 0;
	o_flags = O_LARGEFILE;

	memset(&state, 0, sizeof(struct fd_state));

	while ((c = getopt(argc, argv, "rp:s:h")) != -1) {
		switch (c) {
		case 'r':
			random  = 1;
			break;
		case 'p':
			percent = atoi(optarg);
			break;
		case 's':
			seed    = atoi(optarg);
			break;
		case 'h':
		default:
			usage(app);
		}
	}

	if (optind != argc - 3)
		usage(app);

	srand48(seed);

	iter = strtoull(tag, NULL, 10);

	if (!strcmp(mode, "write")) {
		if (random)
			o_flags |= O_DIRECT;
		fd = open(target, O_RDWR | o_flags);
		if (fd == -1) {
			fprintf(stderr, "Unable to open [%s], (err %d)!\n",
				target, -errno);
			return 1;
		}
		if (getsize(fd, &state) != 0)
			return -1;
		retval = write_testpattern(fd, &state, random, percent);
	} else if (!strcmp(mode, "verify")) {
		fd = open(target, O_RDONLY | o_flags);
		if (fd == -1) {
			fprintf(stderr, "Unable to open [%s], (err %d)!\n",
				target, -errno);
			return 1;
		}
		if (getsize(fd, &state) != 0)
			return -1;
		retval = verify_testpattern(fd, &state, random);
	} else 
		usage(app);


	close(fd);
	return retval;
}
