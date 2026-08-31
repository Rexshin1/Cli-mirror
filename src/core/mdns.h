#ifndef MDNS_H
#define MDNS_H

#include <avahi-client/client.h>
#include <avahi-client/publish.h>
#include <avahi-common/thread-watch.h>

typedef struct {
    AvahiThreadedPoll *threaded_poll;
    AvahiClient *client;
    AvahiEntryGroup *group;
    char friendly_name[128];
    char service_name[256];
    char raop_service_name[256];
    char device_id[18]; // Format: XX:XX:XX:XX:XX:XX
    int port_airplay;
    int port_raop;
} mdns_context_t;

/**
 * Initialize and start publishing AirPlay/RAOP services via mDNS.
 * Returns 0 on success, non-zero on failure.
 */
int mdns_init(mdns_context_t *ctx, const char *friendly_name, int port_airplay, int port_raop);

/**
 * Stop publishing and clean up Avahi resources.
 */
void mdns_cleanup(mdns_context_t *ctx);

#endif // MDNS_H
