#include<unistd.h>
#include<stdio.h>
#include<stdlib.h>

main()
{	
   int num = 10;
   int sz  = 1*1024*1024;
   int j;
   char *p,*q;

   for(j=0;j<num;j++)
   {
       int r = fork();
       if(r<0) printf("failed\n");
       if(r==0)
	 while(1)
	 {
	   int i;
	   char *p, *q = malloc( sz );
	   if(q==NULL) {
             fprintf(stderr,"%dMALLOC ",j);
	     exit(-1);
           }
	   for(i=0,p=q;i<sz;i++) *p++=i;
	   r = fork();
	   if(r<0) {
              perror("");
              fprintf(stderr,"%dFORK ",j);
              exit(-2);
           }
	   if(r>0)  { fprintf(stderr, "%dX ",j); exit(0);}
	   fprintf(stderr,"%d ",j);
	   //setpgid(0,0);
           free(q);
	 }
   }       
   fprintf(stderr,"all started\n");
   for(j=0;j<num;j++) wait(NULL);
   fprintf(stderr,"original all finished\n");
}
