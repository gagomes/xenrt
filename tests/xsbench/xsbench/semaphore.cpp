#include "stdafx.h"

static HANDLE hSemaphoreA = INVALID_HANDLE_VALUE;
static HANDLE hSemaphoreB = INVALID_HANDLE_VALUE;

static volatile unsigned int currentIteration = 0;
static unsigned int maxIterations;

static DWORD __stdcall threadProcA(LPVOID lpdwThreadParam)
{
	DWORD_PTR nodeMask = 1;

	SetThreadAffinityMask(GetCurrentThread(), nodeMask);
	while (currentIteration != maxIterations)
	{
		WaitForSingleObject(hSemaphoreA, INFINITE);
		ReleaseSemaphore(hSemaphoreB, 1, NULL);
	}

	return 0;
}

static DWORD __stdcall threadProcB(LPVOID lpdwThreadParam)
{
	DWORD_PTR nodeMask = 2;

	SetThreadAffinityMask(GetCurrentThread(), nodeMask);
	while (currentIteration != maxIterations)
	{
		WaitForSingleObject(hSemaphoreB, INFINITE);
		currentIteration++;
		ReleaseSemaphore(hSemaphoreA, 1, NULL);
	}

	return 0;
}

static double run(unsigned int iterations)
{
	HANDLE hThreadA = INVALID_HANDLE_VALUE;
	HANDLE hThreadB = INVALID_HANDLE_VALUE;

	maxIterations = iterations;

	hSemaphoreA = CreateSemaphore(NULL, 1, 1, _T("semaphore A"));
	hSemaphoreB = CreateSemaphore(NULL, 0, 1, _T("semaphore B"));

	LARGE_INTEGER freq, begin, end;

	QueryPerformanceFrequency(&freq);
	QueryPerformanceCounter(&begin);

	hThreadA = CreateThread(NULL, 0, threadProcA, NULL, 0, NULL);
	hThreadB = CreateThread(NULL, 0, threadProcB, NULL, 0, NULL);

	WaitForSingleObject(hThreadA, INFINITE);
	WaitForSingleObject(hThreadB, INFINITE);

	QueryPerformanceCounter(&end);

	CloseHandle(hThreadA);
	CloseHandle(hThreadB);
	CloseHandle(hSemaphoreA);
	CloseHandle(hSemaphoreB);

	return (double)(end.QuadPart - begin.QuadPart) / freq.QuadPart;
}

enum test_result test(unsigned int maxTime)
{
	unsigned int iterations = 1000;
	double elapsed;
	
	// Small number of iterations to estimate time per iteration
	elapsed = run(iterations);

	iterations = maxTime / (elapsed / iterations);

	elapsed = run(iterations);

	printf("  iterations: %d\n", iterations);
	printf("  elapsed: %f s\n", elapsed);
	printf("  mean: %f us/iteration\n", elapsed * 1000000 / iterations);

	return TEST_SUCCESS;
}

struct test semaphoreTest = {
	"semaphore",
	test,
};