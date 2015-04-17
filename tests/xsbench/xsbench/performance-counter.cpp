#include "stdafx.h"

static enum test_result run(unsigned int maxTime)
{
	unsigned int iterations = 0;
	LARGE_INTEGER freq, target, begin, end;
	double elapsed;

	QueryPerformanceFrequency(&freq);

	target.QuadPart = maxTime * freq.QuadPart;

	QueryPerformanceCounter(&begin);

	do {
		QueryPerformanceCounter(&end);
		iterations++;
	} while (end.QuadPart - begin.QuadPart < target.QuadPart);
	
	elapsed = (double)(end.QuadPart - begin.QuadPart) / freq.QuadPart;

	printf("  iterations: %u\n"
		"  elapsed: %f s\n"
		"  mean: %f us/call\n",
		iterations, elapsed, elapsed * 1000000 / iterations);

	return TEST_SUCCESS;
}

struct test performanceCounterTest = {
	"performance_counter",
	run,
};