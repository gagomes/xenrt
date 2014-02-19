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
    
    SYSTEMTIME writeStart, writeEnd;
    HANDLE hn;
    HCRYPTPROV hCryptProv;
    DWORD SectorsPerCluster, BytesPerSector, 
          NumberOfFreeClusters, TotalNumberOfClusters;

    BYTE *writeBuffer;

    GetDiskFreeSpace(NULL, &SectorsPerCluster, &BytesPerSector, 
                     &NumberOfFreeClusters, &TotalNumberOfClusters);
    
    writeBuffer = (BYTE *) _aligned_malloc(BytesPerSector, BytesPerSector);
    memset(writeBuffer, 0, BytesPerSector);

    CryptAcquireContext(&hCryptProv, NULL, NULL, PROV_RSA_FULL, CRYPT_VERIFYCONTEXT | CRYPT_SILENT);
    CryptGenRandom(hCryptProv, BytesPerSector, writeBuffer);

    hn = CreateFile(target, 
                    GENERIC_WRITE, 
                    0, 
                    NULL, 
                    CREATE_ALWAYS,
                    FILE_FLAG_WRITE_THROUGH|FILE_FLAG_NO_BUFFERING,
                    NULL);
    GetSystemTime(&writeStart);   
    WriteFile(hn, writeBuffer, BytesPerSector, &n, NULL);    
    GetSystemTime(&writeEnd);
    CloseHandle(hn);

    printf("write: ");
    for (i=0; i<BytesPerSector; i++) {
        printf("%.2x ", (unsigned int) writeBuffer[i]);
    }
    printf("\n");
    printf("start:    %lf\n", sinceEpoch(&writeStart));
    printf("end:      %lf\n", sinceEpoch(&writeEnd));
    printf("duration: %lf\n", sinceEpoch(&writeEnd)-sinceEpoch(&writeStart));

    free(writeBuffer);

    return 0;

}
