/*
 * XenRT: minimal DNS resolver.
 *
 * James Bulpin, January 2006
 *
 * Copyright (c) 2006 XenSource, Inc. All use and distribution of this
 * copyrighted material is governed by and subject to terms and
 * conditions as licensed by XenSource, Inc. All other rights reserved.
 *
 */

#include <stdio.h>
#include <netdb.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>

int main(int argc, char **argv)
{
    struct hostent *hp;

    if (argc < 2)
        return 1;

    hp = gethostbyname(argv[1]);
    if (!hp) {
        return 1;
    }

    printf("%s\n", inet_ntoa(*((struct in_addr *)hp->h_addr)));
    return 0;
}

