#include <stdlib.h>
#include <string.h>
#include <stdio.h>
int main()
{
while(1)
{
void *m = malloc(1024*1024); memset(m,0,1024*1024);
system("free -m | grep Swap | awk '{print $3}'>swap.txt");
}
return 0;
}
