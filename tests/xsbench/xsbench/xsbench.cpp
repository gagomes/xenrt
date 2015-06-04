/*
 * xsbench - run various Win32 microbenchmarks.
 */
#include "stdafx.h"

static const unsigned int maxTimePerTest = 30; /* s */

static enum test_result runTest(struct test *test)
{
	enum test_result result;

	printf("%s:\n", test->name);
	result = test->run(maxTimePerTest);
	printf("  status: %s\n", result == TEST_SUCCESS ? "success" : "FAIL");

	return result;
}

int _tmain(int argc, _TCHAR* argv[])
{
	enum test_result result = TEST_SUCCESS;

	result |= runTest(&performanceCounterTest);
	result |= runTest(&semaphoreTest);

	return result;
}

