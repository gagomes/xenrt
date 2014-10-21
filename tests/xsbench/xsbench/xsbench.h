#ifndef XSBENCH_H
#define XSBENCH_H

enum test_result {
	TEST_SUCCESS = 0,
	TEST_FAILED = 1,
};

static inline enum test_result operator |= (enum test_result& a, enum test_result b)
{
	return static_cast<enum test_result>((unsigned int&)a |= (unsigned int)b);
}

struct test {
	const char *name;
	enum test_result (*run)(unsigned int maxTime);
};

extern struct test performanceCounterTest;
extern struct test semaphoreTest;

#endif /* #ifndef XSBENCH_H */