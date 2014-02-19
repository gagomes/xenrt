// playing with libext2fs

// % gcc -g -o ext2fs_test $(pkg-config --cflags ext2fs) ext2fs_test.c $(pkg-config --libs ext2fs)
// % gcc -g -o ext2fs_test -I/usr/include/ext2fs ext2fs_test.c $(pkg-config --libs ext2fs)

#include <stdio.h>
#include <ext2fs.h>
#include <com_err.h>

int
main(int argc, char *argv[])
{
    ext2_filsys fils=0;

    errcode_t res = ext2fs_open(argv[1], 0, 0, 0, unix_io_manager, &fils);
    if(res) {
        printf("%u : %s\n", res, error_message(res));
        return 1;
    }

    return 0;
}
