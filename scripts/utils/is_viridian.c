#include <windows.h>
#include <stdio.h>

VOID
cpuid(ULONG leaf, ULONG *peax, ULONG *pebx, ULONG *pecx,
       ULONG *pedx)
{
    ULONG reax, rebx, recx, redx;
    _asm {
        mov eax, leaf;
        cpuid;
        mov reax, eax;
        mov rebx, ebx;
        mov recx, ecx;
        mov redx, edx;
    };
    *peax = reax;
    *pebx = rebx;
    *pecx = recx;
    *pedx = redx;
}

int
main(int argc, char *argv[])
{
    ULONG eax, ebx, ecx, edx;
    int rc;

    UNREFERENCED_PARAMETER(argv);

    cpuid(0x40000000, &eax, &ebx, &ecx, &edx);

    rc = (ebx == 0x7263694d) && (ecx == 0x666f736f) && (edx == 0x76482074);

    if (argc != 1)
    {
        printf("CPUID reports viridian is %s.\n", rc ? "TRUE" : "FALSE");
    }

    return rc == 0;
}
