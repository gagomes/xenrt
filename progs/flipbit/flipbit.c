#include <stdio.h>
#include <stdlib.h>

int main(int argc, char * argv[]) {

    int byte;
    FILE *fp;
    char *name;    
    char c;
   
    byte = atoi(argv[1]);
    name = argv[2];

    printf("Looking for byte %d in %s.\n", byte, name);
    fp = fopen(name, "r+b");
    if (!fp) {
        printf("Failed to open file.\n");
        return 1;
    }
    fseek(fp, byte, SEEK_SET);
    fread(&c, 1, 1, fp);
    printf("Found 0x%X.\n", c); 
    c = c ^ 0x0000001;
    printf("Flipped to 0x%X.\n", c);
    printf("Updating source file.\n");
    fseek(fp, byte, SEEK_SET);
    fwrite(&c, 1, 1, fp);
    fclose(fp);
    
    return 0;

}
