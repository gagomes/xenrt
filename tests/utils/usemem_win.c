// Program to allocate a specified amount of physical memory
// Adapted by Alex Brett from the MSDN AWE example:
// http://msdn.microsoft.com/en-us/library/aa366531(VS.85).aspx
// alex.brett@eu.citrix.com

// Compiles using MinGW (gcc -o usemem_win usemem_win.c)

#define _WIN32_WINNT 0x0501

#include <windows.h>
#include <stdio.h>
#include <stdlib.h>

int _cdecl main(int argc, char** argv)
{
  BOOL bResult;                   // generic Boolean value
  ULONG_PTR NumberOfPages;        // number of pages to request
  ULONG_PTR NumberOfPagesInitial; // initial number of pages requested
  ULONG_PTR *aPFNs;               // page info; holds opaque data
  PVOID lpMemReserved;            // AWE window
  SYSTEM_INFO sSysInfo;           // useful system information
  int PFNArraySize;               // memory to request for PFN array
  int i;						  // iterator
  int bytes;					  // Number of bytes to request

  if (argc != 2) {
	  printf ("Usage: %s <number_of_bytes_to_allocate>\n", argv[0]);
	  return 1;
  }

  bytes = atoi(argv[1]);

  printf("Attempting to allocate %d bytes.\n", bytes);

  GetSystemInfo(&sSysInfo);  // fill the system information structure

  printf("This computer has page size %d.\n", sSysInfo.dwPageSize);

  // Calculate the number of pages of memory to request.

  NumberOfPages = bytes/sSysInfo.dwPageSize;
  printf ("Requesting %d pages of memory.\n", NumberOfPages);

  // Calculate the size of the user PFN array.

  PFNArraySize = NumberOfPages * sizeof (ULONG_PTR);

  printf ("Requesting a PFN array of %d bytes.\n", PFNArraySize);

  aPFNs = (ULONG_PTR *) HeapAlloc(GetProcessHeap(), 0, PFNArraySize);

  if (aPFNs == NULL)
  {
    printf ("Failed to allocate on heap.\n");
    return 1;
  }

  // Enable the privilege.

  if( ! LoggedSetLockPagesPrivilege( GetCurrentProcess(), TRUE ) )
  {
    return 1;
  }

  // Allocate the physical memory.

  NumberOfPagesInitial = NumberOfPages;
  bResult = AllocateUserPhysicalPages( GetCurrentProcess(),
                                       &NumberOfPages,
                                       aPFNs );

  if( bResult != TRUE )
  {
    printf("Cannot allocate physical pages (%u)\n", GetLastError() );
    return 1;
  }

  if( NumberOfPagesInitial != NumberOfPages )
  {
    printf("Allocated only %p pages.\n", NumberOfPages );
    return 1;
  }

  // Reserve the virtual memory.

  lpMemReserved = VirtualAlloc( NULL,
                                bytes,
                                MEM_RESERVE | MEM_PHYSICAL,
                                PAGE_READWRITE );

  if( lpMemReserved == NULL )
  {
    printf("Cannot reserve memory.\n");
    return 1;
  }

  // Map the physical memory into the window.

  bResult = MapUserPhysicalPages( lpMemReserved,
                                  NumberOfPages,
                                  aPFNs );

  if( bResult != TRUE )
  {
    printf("MapUserPhysicalPages failed (%u)\n", GetLastError() );
    return 1;
  }

  while (1)
	  Sleep(30);

  return 0;

}

/*****************************************************************
   LoggedSetLockPagesPrivilege: a function to obtain or
   release the privilege of locking physical pages.

   Inputs:

       HANDLE hProcess: Handle for the process for which the
       privilege is needed

       BOOL bEnable: Enable (TRUE) or disable?

   Return value: TRUE indicates success, FALSE failure.

*****************************************************************/
BOOL
LoggedSetLockPagesPrivilege ( HANDLE hProcess,
                              BOOL bEnable)
{
  struct {
    DWORD Count;
    LUID_AND_ATTRIBUTES Privilege [1];
  } Info;

  HANDLE Token;
  BOOL Result;

  // Open the token.

  Result = OpenProcessToken ( hProcess,
                              TOKEN_ADJUST_PRIVILEGES,
                              & Token);

  if( Result != TRUE )
  {
    printf( "Cannot open process token.\n" );
    return FALSE;
  }

  // Enable or disable?

  Info.Count = 1;
  if( bEnable )
  {
    Info.Privilege[0].Attributes = SE_PRIVILEGE_ENABLED;
  }
  else
  {
    Info.Privilege[0].Attributes = 0;
  }

  // Get the LUID.

  Result = LookupPrivilegeValue ( NULL,
                                  SE_LOCK_MEMORY_NAME,
                                  &(Info.Privilege[0].Luid));

  if( Result != TRUE )
  {
    printf( "Cannot get privilege for %s.\n", SE_LOCK_MEMORY_NAME );
    return FALSE;
  }

  // Adjust the privilege.

  Result = AdjustTokenPrivileges ( Token, FALSE,
                                   (PTOKEN_PRIVILEGES) &Info,
                                   0, NULL, NULL);

  // Check the result.

  if( Result != TRUE )
  {
    printf ("Cannot adjust token privileges (%u)\n", GetLastError() );
    return FALSE;
  }
  else
  {
    if( GetLastError() != ERROR_SUCCESS )
    {
      printf ("Cannot enable the SE_LOCK_MEMORY_NAME privilege; ");
      printf ("please check the local policy.\n");
      return FALSE;
    }
  }

  CloseHandle( Token );

  return TRUE;
}
