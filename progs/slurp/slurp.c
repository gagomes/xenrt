/******************************************************************************
 * slurp.c
 * 
 * Slurps spare CPU cycles and prints a percentage estimate every second.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define US_INTERVAL 1000000ULL /* time between estimates, in microseconds. */

/* rpcc: get full 64-bit Pentium TSC value */
static __inline__ unsigned long long int rpcc(void) 
{
    unsigned int __h, __l;
    __asm__ __volatile__ ("rdtsc" :"=a" (__l), "=d" (__h));
    return (((unsigned long long)__h) << 32) + __l;
}


/*
 * find_cpu_speed:
 *   Interrogates /proc/cpuinfo for the processor clock speed.
 * 
 *   Returns: speed of processor in MHz, rounded down to nearest whole MHz.
 */
#define MAX_LINE_LEN 50
int find_cpu_speed(void)
{
    FILE *f;
    char s[MAX_LINE_LEN], *a, *b;

    if ( (f = fopen("/proc/cpuinfo", "r")) == NULL ) goto out;

    while ( fgets(s, MAX_LINE_LEN, f) )
    {
        if ( strstr(s, "cpu MHz") )
        {
            /* Find the start of the speed value, and stop at the dec point. */
            if ( !(a=strpbrk(s,"0123456789")) || !(b=strpbrk(a,".")) ) break;
            *b = '\0';
            fclose(f);
            return(atoi(a));
        }
    }

 out:
    fprintf(stderr, "find_cpu_speed: error parsing /proc/cpuinfo for cpu MHz");
    exit(1);
}


int main(void)
{
    int mhz, i;

    /*
     * no_preempt_estimate is our estimate, in clock cycles, of how long it
     * takes to execute one iteration of the main loop when we aren't
     * preempted. 50000 cycles is an overestimate, which we want because:
     *  (a) On the first pass through the loop, diff will be almost 0,
     *      which will knock the estimate down to <40000 immediately.
     *  (b) It's safer to approach real value from above than from below --
     *      note that this algorithm is unstable if n_p_e gets too small!
     */
    unsigned int no_preempt_estimate = 50000;

    /*
     * prev     = timestamp on previous iteration;
     * this     = timestamp on this iteration;
     * diff     = difference between the above two stamps;
     * start    = timestamp when we last printed CPU % estimate;
     * next_est = next time at which we print estimate
     */
    unsigned long long int prev, this, diff, start, next_est;

    /*
     * preempt_time = approx. cycles we've been preempted for since last stats
     *                display.
     */
    unsigned long long int preempt_time = 0;

    /*
     * preempt_count = approximate number of times we were preempted.
     */
    unsigned long preempt_count = 0;

    /* Required in order to print intermediate results at fixed period. */
    mhz = find_cpu_speed();
    printf("CPU speed = %d MHz\n", mhz);

    start = prev = rpcc();
    next_est = start + US_INTERVAL * mhz;

    for ( ; ; )
    {
        /*
         * By looping for a while here we hope to reduce affect of getting
         * preempted in critical "timestamp swapping" section of the loop.
         * In addition, it should ensure that 'no_preempt_estimate' stays
         * reasonably large which helps keep this algorithm stable.
         */
        for ( i = 0; i < 100; i++ ) __asm__ __volatile__ ( "rep; nop;" : : );

        /*
         * The critical bit! Getting preempted here will shaft us a bit,
         * but the loop above should make this a rare occurrence.
         */
	this = rpcc();
	diff = this - prev;
	prev = this;

        /* if ( diff > (2 * preempt_estimate) */
        if ( diff > (no_preempt_estimate<<1) )
        {
            /* We were probably preempted for a while. */
            preempt_time += diff - no_preempt_estimate;
            preempt_count++;
        }
        else
        {
            /*
             * Looks like we weren't preempted -- update our time estimate:
             * New estimate = 0.75*old_est + 0.25*curr_diff
             */
            no_preempt_estimate =
                (no_preempt_estimate >> 1) + 
                (no_preempt_estimate >> 2) +
                (diff >> 2);
        }
	    
        /* Dump CPU time every second. */
        if ( this > next_est ) 
        { 
            printf("Slurped %.2f%% CPU, preempted %lu times\n", 
                   100.0 * (((double)this - start - preempt_time) / 
                            ((double)this - start)), 
                   preempt_count);
            start         = this;
            next_est     += US_INTERVAL * mhz;
            preempt_time  = 0;
            preempt_count = 0;
        }
    }

    return(0);
}
