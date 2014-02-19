#define WIN32_LEAN_AND_MEAN		// Exclude rarely-used stuff from Windows headers
#include<windows.h>
#include<winbase.h>
#include<stdlib.h>
#include<stdio.h>
#include<tchar.h>
#include<time.h>

#define _1MB (1 << 20)	

int _tmain(int argc, _TCHAR* argv[])
{
	UCHAR d;
    PUCHAR data;
    HANDLE file;
	ULONG i;
    HANDLE mappingHandle;
	bool read;
    ULONG size;
	ULONG status;
	bool write;

	if (argc < 3) {
		_ftprintf(stderr, TEXT("Invalid number (%d) of arguments specified.\n"), argc);
		_ftprintf(stderr, TEXT("Usage: mappedfile READ|WRITE [read filename] [write size].\n"), argc);
		return 1;
	}

	if (_tcsicmp(argv[1], TEXT("READ")) == 0) {
		read = true;
		write = false;

	} else if (_tcsicmp(argv[1], TEXT("WRITE")) == 0) {
		read = false;
		write = true;

	} else {
		_ftprintf(stderr, TEXT("Specify READ|WRITE instead of %s.\n"), argv[1]);
		return 2;
	}

	if (read != false) {
		file = CreateFile(argv[2],
						  GENERIC_READ,
						  FILE_SHARE_READ,
						  NULL,
						  OPEN_EXISTING,
						  FILE_FLAG_SEQUENTIAL_SCAN,
						  NULL);
		if (file == INVALID_HANDLE_VALUE) {
			status = GetLastError();
			_ftprintf(stderr, TEXT("Failed (0x%08X) to create file %s.\n"), status, argv[2]);
			return status;
		}

	} else {
		file = INVALID_HANDLE_VALUE;
	}

	if (read != false) {
		size = GetFileSize(file, NULL);
		if (size == INVALID_FILE_SIZE) {
			status = GetLastError();
			_ftprintf(stderr, TEXT("Failed (0x%08X) to get file size of %s.\n"), status, argv[2]);
			return status;
		}

	} else {
		if (argc > 2) {
			size = _tstol(argv[2]) * _1MB;
			if (size != 0) {
				_ftprintf(stdout, TEXT("Using caller specified file size of %d bytes.\n"), size);
			}

		} 

		if (size == 0) {
			srand((unsigned)time(NULL));
			size = (rand() % 10) * _1MB; 
			_ftprintf(stdout, TEXT("Using random file size of %d bytes.\n"), size);
		}
	}

	mappingHandle = CreateFileMapping(file,
                                      NULL,
									  (read == true)? PAGE_READONLY : (PAGE_READWRITE | SEC_COMMIT),
                                      0,
                                      size,     
                                      NULL);

    if (mappingHandle == NULL) {
		status = GetLastError();
		_ftprintf(stderr, TEXT("Failed (0x%08X) to create file mapping of %s.\n"), status, argv[2]);
		return status;
	}

    data = (PUCHAR)MapViewOfFile(mappingHandle,
								(read == true)? FILE_MAP_READ : FILE_MAP_WRITE,
                                 0,
                                 0,
                                 size);

    if (data == NULL) {
		status = GetLastError();
		_ftprintf(stderr, TEXT("Failed (0x%08X) to map view of %s.\n"), status, argv[2]);
		return status;
	}

	_ftprintf(stdout, TEXT("%s file...\n"), (read != false)? TEXT("Reading") : TEXT("Writing"));
	for (i = 0; i < size; i++) {
		if (read != false) {
			d = data[i];
		} else {
			data[i] = rand() % 128;
		}
	}

	FlushViewOfFile(data, size);
	_ftprintf(stdout, TEXT("Done %s file.\n"), (read != false)? TEXT("reading") : TEXT("writing"));
	if (file != INVALID_HANDLE_VALUE) {
		CloseHandle(file);
	}

	if (mappingHandle != INVALID_HANDLE_VALUE) {
		CloseHandle(mappingHandle);
	}
	return 0;
}
