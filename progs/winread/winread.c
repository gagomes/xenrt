#include <stdio.h>
#include <malloc.h>
#include <windows.h>
#include <wincrypt.h>

double sinceEpoch(SYSTEMTIME *time) {

    FILETIME ft, et;
    ULARGE_INTEGER i, j, e;
    SYSTEMTIME epoch;
    
    epoch.wYear = 1970;
    epoch.wMonth = 1;
    epoch.wDayOfWeek = 4;
    epoch.wDay = 1;
    epoch.wHour = 0;
    epoch.wMinute = 0;
    epoch.wSecond = 0;
    epoch.wMilliseconds = 0;                       
    

    SystemTimeToFileTime(&epoch, &et);
    j.LowPart = et.dwLowDateTime;
    j.HighPart = et.dwHighDateTime;

    SystemTimeToFileTime(time, &ft);
    i.LowPart = ft.dwLowDateTime;
    i.HighPart = ft.dwHighDateTime;

    e.QuadPart = i.QuadPart-j.QuadPart;
    
    return (double) e.QuadPart / 10000000;

}

int __cdecl main(int argc, char *argv[]) {

    char *target = argv[1];
    unsigned int n, i;
    
    SYSTEMTIME readStart, readEnd;
    HANDLE hn;
    HCRYPTPROV hCryptProv;
    DWORD SectorsPerCluster, BytesPerSector, 
          NumberOfFreeClusters, TotalNumberOfClusters;

    BYTE *readBuffer;

    GetDiskFreeSpace(NULL, &SectorsPerCluster, &BytesPerSector, 
                     &NumberOfFreeClusters, &TotalNumberOfClusters);
    
    readBuffer = (BYTE *) _aligned_malloc(BytesPerSector, BytesPerSector);
    memset(readBuffer, 0, BytesPerSector);

    hn = CreateFile(target, 
                    GENERIC_READ, 
                    0, 
                    NULL, 
                    OPEN_EXISTING,
                    FILE_FLAG_NO_BUFFERING,
                    NULL);
    GetSystemTime(&readStart);  
    ReadFile(hn, readBuffer, BytesPerSector, &n, NULL);
    GetSystemTime(&readEnd);
    CloseHandle(hn);

    printf("read: ");
    for (i=0; i<BytesPerSector; i++) {
        printf("%.2x ", (unsigned int) readBuffer[i]);
    }
    printf("\n");
    printf("start:    %lf\n", sinceEpoch(&readStart));
    printf("end:      %lf\n", sinceEpoch(&readEnd));
    printf("duration: %lf\n", sinceEpoch(&readEnd)-sinceEpoch(&readStart));

    free(readBuffer);

    return 0;

}
