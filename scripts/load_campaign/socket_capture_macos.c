/* Opt-in Mac UDP socket observation for the small external accounting check.
 * Delegates the original libc calls unchanged. Records complete successful UDP
 * payloads in synthetic Ethernet/IP headers: IP/UDP sizes assume IPv4, no options.
 * Timestamps are socket send completion / receive observation, not NIC timestamps.
 */
#include <arpa/inet.h>
#include <dlfcn.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

static FILE *evidence;

__attribute__((constructor)) static void initialize(void) {
    const char *path = getenv("OMEGA_SOCKET_PCAP");
    if (path) {
        evidence = fopen(path, "wb");
        if (!evidence) { perror("socket capture open"); abort(); }
        setvbuf(evidence, NULL, _IOFBF, 1024 * 1024);
        const uint32_t global[] = {0xa1b2c3d4, 0x00040002, 0, 0, 65536, 1};
        if (fwrite(global, sizeof(global), 1, evidence) != 1) abort();
    }
}

static void observe(int fd, const void *payload, size_t length, const struct sockaddr *remote, int outbound) {
    if (!evidence || !remote || remote->sa_family != AF_INET || length > 65507) return;
    struct sockaddr_in local;
    socklen_t size = sizeof(local);
    if (getsockname(fd, (struct sockaddr *)&local, &size) || local.sin_family != AF_INET) return;
    const struct sockaddr_in *peer = (const struct sockaddr_in *)remote;
    if (ntohs(local.sin_port) != 8081 && ntohs(peer->sin_port) != 8081) return;
    const struct sockaddr_in *source = outbound ? &local : peer;
    const struct sockaddr_in *target = outbound ? peer : &local;
    unsigned char header[42] = {0};
    header[12] = 8; header[14] = 0x45; header[22] = 64; header[23] = 17;
    uint16_t ip_length = htons((uint16_t)(length + 28));
    uint16_t udp_length = htons((uint16_t)(length + 8));
    memcpy(header + 16, &ip_length, 2);
    memcpy(header + 26, &source->sin_addr, 4);
    memcpy(header + 30, &target->sin_addr, 4);
    memcpy(header + 34, &source->sin_port, 2);
    memcpy(header + 36, &target->sin_port, 2);
    memcpy(header + 38, &udp_length, 2);
    struct timespec stamp;
    clock_gettime(CLOCK_REALTIME, &stamp);
    uint32_t record[] = {(uint32_t)stamp.tv_sec, (uint32_t)(stamp.tv_nsec / 1000), (uint32_t)(length + 42), (uint32_t)(length + 42)};
    flockfile(evidence);
    if (fwrite(record, sizeof(record), 1, evidence) != 1 || fwrite(header, sizeof(header), 1, evidence) != 1 || fwrite(payload, length, 1, evidence) != 1) abort();
    funlockfile(evidence);
}

static ssize_t omega_sendto(int fd, const void *buffer, size_t length, int flags, const struct sockaddr *address, socklen_t address_length) {
    ssize_t result = sendto(fd, buffer, length, flags, address, address_length);
    int saved_errno = errno;
    if (result > 0) observe(fd, buffer, (size_t)result, address, 1);
    errno = saved_errno;
    return result;
}

static ssize_t omega_recvfrom(int fd, void *buffer, size_t length, int flags, struct sockaddr *address, socklen_t *address_length) {
    ssize_t result = recvfrom(fd, buffer, length, flags, address, address_length);
    int saved_errno = errno;
    if (result > 0) observe(fd, buffer, (size_t)result, address, 0);
    errno = saved_errno;
    return result;
}

__attribute__((used)) static const struct {
    const void *replacement;
    const void *replacee;
} interpositions[] __attribute__((section("__DATA,__interpose"))) = {
    {(const void *)omega_sendto, (const void *)sendto},
    {(const void *)omega_recvfrom, (const void *)recvfrom},
};

__attribute__((destructor)) static void finish(void) {
    if (evidence && fclose(evidence)) abort();
}
