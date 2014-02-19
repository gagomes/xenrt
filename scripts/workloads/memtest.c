/*
 * Very simple (yet, for some reason, very effective) memory tester.
 *
 * This program will run on an active machine, but will test only the
 * memory that the kernel maps to the process.  Make sure you specify
 * at least enough memory (in 2^20 MB) to cross all of your memory
 * chips, unless you want to keep a larger amount of memory
 * available.  Note that the amount of time required to complete one
 * test run is proportional to the amount of memory being tested.
 *
 * This program does not take in to account cache issues or anything
 * similar, but it still seems to do the trick, and thus I have
 * decided not cleaned up the cut-and-paste coding technique I used
 * to create it very quickly several years ago, fearing that I may
 * break its strange powers. :)
 *
 * I hope others can find this as useful as I have.
 *
 * The algorithm is simple:
 *   1. Fill two byte arrays of equal size (half of the memory size
 *      specified) with equal pseudo-random data.
 *   2. Walk through each element of both arrays and do a simple
 *      operation with another random byte on each element.
 *   3. Compare each array to make sure both are equal (if not,
 *      bomb out with a failure message).
 *
 * Compilation:
 *   gcc -o memtest memtest.c
 *
 * Usage:
 *   memtest <megabytes of memory to test>
 *
 * Simon Kirby <sim@stormix.com> <sim@neato.org>, 1999/10/21
 */

#include <sys/types.h>
#include <unistd.h>
#include <errno.h>
#include <string.h>
#include <stdio.h>

void usage(char *me){
   fprintf(stderr,"Usage: %s <megabytes of memory to test>\n",me);
}

int main(int argc,char *argv[]){
   char *buf,*bp1,*bp2,*p1,*p2;
   unsigned long mem,chunksize,i,testrun;
   char q;
   if (argc <= 1){
      usage(argv[0]);
      exit(-1);
   }
   mem = ((unsigned long)atol(argv[1])) * 1048576;
   if (!mem){
      usage(argv[0]);
      exit(-1);
   }
   buf = (char *)malloc(mem);
   if (!buf){
      fprintf(stderr,"%s: Unable to malloc(%u): %s\n",argv[0],mem,strerror(errno));
      exit(-1);
   }
   fprintf(stderr,"Allocation successful.  Proceeding.\n");
   chunksize = mem >> 1;
   bp1 = buf;
   bp2 = buf + (chunksize);
   for (testrun = 0;;){
      fprintf(stderr,"Run %u: Randomize and MOV comparison test: Setting...",testrun++);
      p1 = bp1; p2 = bp2;
      for (i = 0;i < chunksize;i++){
         *p1++ = *p2++ = rand();
      }
      fprintf(stderr,"Testing...");
      p1 = bp1; p2 = bp2;
      for (i = 0;i < chunksize;i++,p1++,p2++){
         if (*p1 != *p2){
            printf("FAILURE: 0x%x != 0x%x at offset 0x%x.\n",*p1,*p2,i);
            exit(-1);
         }
      }
      fprintf(stderr,"Passed.\n");

      fprintf(stderr,"Run %u:               XOR comparison test: Setting...",testrun++);
      p1 = bp1; p2 = bp2;
      q = rand();
      for (i = 0;i < chunksize;i++){
         *p1++ ^= q;
         *p2++ ^= q;
      }
      fprintf(stderr,"Testing...");
      p1 = bp1; p2 = bp2;
      for (i = 0;i < chunksize;i++,p1++,p2++){
         if (*p1 != *p2){
            printf("FAILURE: 0x%x != 0x%x at offset 0x%x.\n",*p1,*p2,i);
            exit(-1);
         }
      }
      fprintf(stderr,"Passed.\n");

      fprintf(stderr,"Run %u:               SUB comparison test: Setting...",testrun++);
      p1 = bp1; p2 = bp2;
      q = rand();
      for (i = 0;i < chunksize;i++){
         *p1++ -= q;
         *p2++ -= q;
      }
      fprintf(stderr,"Testing...");
      p1 = bp1; p2 = bp2;
      for (i = 0;i < chunksize;i++,p1++,p2++){
         if (*p1 != *p2){
            printf("FAILURE: 0x%x != 0x%x at offset 0x%x.\n",*p1,*p2,i);
            exit(-1);
         }
      }
      fprintf(stderr,"Passed.\n");

      fprintf(stderr,"Run %u:               MUL comparison test: Setting...",testrun++);
      p1 = bp1; p2 = bp2;
      q = rand();
      for (i = 0;i < chunksize;i++){
         *p1++ *= q;
         *p2++ *= q;
      }
      fprintf(stderr,"Testing...");
      p1 = bp1; p2 = bp2;
      for (i = 0;i < chunksize;i++,p1++,p2++){
         if (*p1 != *p2){
            printf("FAILURE: 0x%x != 0x%x at offset 0x%x.\n",*p1,*p2,i);
            exit(-1);
         }
      }
      fprintf(stderr,"Passed.\n");

      fprintf(stderr,"Run %u:               DIV comparison test: Setting...",testrun++);
      p1 = bp1; p2 = bp2;
      q = rand();
      for (i = 0;i < chunksize;i++){
         if (!q) q++;
         *p1++ /= q;
         *p2++ /= q;
      }
      fprintf(stderr,"Testing...");
      p1 = bp1; p2 = bp2;
      for (i = 0;i < chunksize;i++,p1++,p2++){
         if (*p1 != *p2){
            printf("FAILURE: 0x%x != 0x%x at offset 0x%x.\n",*p1,*p2,i);
            exit(-1);
         }
      }
      fprintf(stderr,"Passed.\n");

      fprintf(stderr,"Run %u:                OR comparison test: Setting...",testrun++);
      p1 = bp1; p2 = bp2;
      q = rand();
      for (i = 0;i < chunksize;i++){
         *p1++ |= q;
         *p2++ |= q;
      }
      fprintf(stderr,"Testing...");
      p1 = bp1; p2 = bp2;
      for (i = 0;i < chunksize;i++,p1++,p2++){
         if (*p1 != *p2){
            printf("FAILURE: 0x%x != 0x%x at offset 0x%x.\n",*p1,*p2,i);
            exit(-1);
         }
      }
      fprintf(stderr,"Passed.\n");

      fprintf(stderr,"Run %u:               AND comparison test: Setting...",testrun++);
      p1 = bp1; p2 = bp2;
      q = rand();
      for (i = 0;i < chunksize;i++){
         *p1++ &= q;
         *p2++ &= q;
      }
      fprintf(stderr,"Testing...");
      p1 = bp1; p2 = bp2;
      for (i = 0;i < chunksize;i++,p1++,p2++){
         if (*p1 != *p2){
            printf("FAILURE: 0x%x != 0x%x at offset 0x%x.\n",*p1,*p2,i);
            exit(-1);
         }
      }
      fprintf(stderr,"Passed.\n");
   }
   exit(0);
}
