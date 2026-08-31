#include "mdns.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/ioctl.h>
#include <net/if.h>
#include <ifaddrs.h>
#include <netpacket/packet.h>
#include <avahi-common/error.h>
#include <avahi-common/alternative.h>

static void entry_group_callback(AvahiEntryGroup *g, AvahiEntryGroupState state, void *userdata);
static void client_callback(AvahiClient *c, AvahiClientState state, void *userdata);
static void register_services(mdns_context_t *ctx);

/**
 * Retrieves the hardware MAC address of the first active non-loopback network interface.
 * Fills mac_str with "XX:XX:XX:XX:XX:XX" and mac_clean with "XXXXXXXXXXXX".
 */
static int get_mac_address(char *mac_str, char *mac_clean) {
    struct ifaddrs *ifaddr, *ifa;
    unsigned char mac_bin[6] = {0};
    int found = 0;

    if (getifaddrs(&ifaddr) == -1) {
        return -1;
    }

    for (ifa = ifaddr; ifa != NULL; ifa = ifa->ifa_next) {
        if (ifa->ifa_addr == NULL) continue;
        if (ifa->ifa_flags & IFF_LOOPBACK) continue;
        
        if (ifa->ifa_addr->sa_family == AF_PACKET) {
            struct sockaddr_ll *sll = (struct sockaddr_ll *)ifa->ifa_addr;
            if (sll->sll_halen == 6) {
                memcpy(mac_bin, sll->sll_addr, 6);
                // Ensure it's not a zero MAC
                if (mac_bin[0] || mac_bin[1] || mac_bin[2] || mac_bin[3] || mac_bin[4] || mac_bin[5]) {
                    found = 1;
                    break;
                }
            }
        }
    }
    freeifaddrs(ifaddr);

    if (found) {
        snprintf(mac_str, 18, "%02X:%02X:%02X:%02X:%02X:%02X",
                 mac_bin[0], mac_bin[1], mac_bin[2], mac_bin[3], mac_bin[4], mac_bin[5]);
        snprintf(mac_clean, 13, "%02X%02X%02X%02X%02X%02X",
                 mac_bin[0], mac_bin[1], mac_bin[2], mac_bin[3], mac_bin[4], mac_bin[5]);
        return 0;
    }

    return -1;
}

int mdns_init(mdns_context_t *ctx, const char *friendly_name, int port_airplay, int port_raop) {
    char mac_clean[13];
    int error;

    memset(ctx, 0, sizeof(mdns_context_t));
    ctx->port_airplay = port_airplay;
    ctx->port_raop = port_raop;

    strncpy(ctx->friendly_name, friendly_name, sizeof(ctx->friendly_name) - 1);
    strncpy(ctx->service_name, friendly_name, sizeof(ctx->service_name) - 1);

    // Retrieve active MAC address
    if (get_mac_address(ctx->device_id, mac_clean) < 0) {
        fprintf(stderr, "mDNS Warning: Active network MAC address not found. Using fallback.\n");
        strcpy(ctx->device_id, "00:11:22:33:44:55");
        strcpy(mac_clean, "001122334455");
    }

    // RAOP service name prefix is "MACADDRESS@friendly_name"
    snprintf(ctx->raop_service_name, sizeof(ctx->raop_service_name), "%s@%s", mac_clean, ctx->service_name);

    printf("mDNS: Local Device ID set to %s\n", ctx->device_id);

    // Initialize Avahi threaded poll loop
    ctx->threaded_poll = avahi_threaded_poll_new();
    if (!ctx->threaded_poll) {
        fprintf(stderr, "mDNS Error: Failed to create Avahi threaded poll loop.\n");
        return -1;
    }

    // Create client
    ctx->client = avahi_client_new(
        avahi_threaded_poll_get(ctx->threaded_poll),
        AVAHI_CLIENT_NO_FAIL,
        client_callback,
        ctx,
        &error
    );

    if (!ctx->client) {
        fprintf(stderr, "mDNS Error: Failed to create Avahi client: %s\n", avahi_strerror(error));
        avahi_threaded_poll_free(ctx->threaded_poll);
        return -1;
    }

    // Start poll loop thread
    if (avahi_threaded_poll_start(ctx->threaded_poll) < 0) {
        fprintf(stderr, "mDNS Error: Failed to start Avahi thread.\n");
        avahi_client_free(ctx->client);
        avahi_threaded_poll_free(ctx->threaded_poll);
        return -1;
    }

    return 0;
}

void mdns_cleanup(mdns_context_t *ctx) {
    if (ctx->threaded_poll) {
        avahi_threaded_poll_stop(ctx->threaded_poll);
    }

    if (ctx->client) {
        avahi_client_free(ctx->client);
    }

    if (ctx->threaded_poll) {
        avahi_threaded_poll_free(ctx->threaded_poll);
    }

    memset(ctx, 0, sizeof(mdns_context_t));
    printf("mDNS: Publisher cleaned up.\n");
}

static void register_services(mdns_context_t *ctx) {
    int ret;

    // Create entry group if not already allocated
    if (!ctx->group) {
        ctx->group = avahi_entry_group_new(ctx->client, entry_group_callback, ctx);
        if (!ctx->group) {
            fprintf(stderr, "mDNS Error: avahi_entry_group_new() failed: %s\n",
                    avahi_strerror(avahi_client_errno(ctx->client)));
            return;
        }
    }

    if (avahi_entry_group_is_empty(ctx->group)) {
        char txt_deviceid[64];
        snprintf(txt_deviceid, sizeof(txt_deviceid), "deviceid=%s", ctx->device_id);

        // 1. Register AirPlay Service (_airplay._tcp)
        ret = avahi_entry_group_add_service(
            ctx->group,
            AVAHI_IF_UNSPEC,
            AVAHI_PROTO_UNSPEC,
            0,
            ctx->service_name,
            "_airplay._tcp",
            NULL, // Default domain
            NULL, // Default host
            ctx->port_airplay,
            txt_deviceid,
            "features=0x5A7FFFF7,0xE", // Video Mirroring & Audio support flags
            "model=AppleTV3,2",
            "srcvers=101.28",
            "flags=0x4",
            "vv=2",
            NULL
        );
        if (ret < 0) {
            fprintf(stderr, "mDNS Error: Failed to add _airplay._tcp service: %s\n", avahi_strerror(ret));
            return;
        }

        // 2. Register RAOP Audio Service (_raop._tcp)
        ret = avahi_entry_group_add_service(
            ctx->group,
            AVAHI_IF_UNSPEC,
            AVAHI_PROTO_UNSPEC,
            0,
            ctx->raop_service_name,
            "_raop._tcp",
            NULL,
            NULL,
            ctx->port_raop,
            "txtvers=1",
            "ch=2",
            "cn=0,1,2,3",
            "da=true",
            "et=0,3,5",
            "md=0,1,2",
            "pw=false",
            "sv=false",
            "sr=44100",
            "ss=16",
            "tp=UDP",
            "vn=65537",
            "vs=130.14",
            "am=AppleTV3,2",
            "sf=0x4",
            NULL
        );
        if (ret < 0) {
            fprintf(stderr, "mDNS Error: Failed to add _raop._tcp service: %s\n", avahi_strerror(ret));
            return;
        }

        // Commit services to network
        ret = avahi_entry_group_commit(ctx->group);
        if (ret < 0) {
            fprintf(stderr, "mDNS Error: Failed to commit entry group: %s\n", avahi_strerror(ret));
            return;
        }

        printf("mDNS: Committed AirPlay service '%s' (port %d) and RAOP service '%s' (port %d) to local network.\n",
               ctx->service_name, ctx->port_airplay, ctx->raop_service_name, ctx->port_raop);
    }
}

static void client_callback(AvahiClient *c, AvahiClientState state, void *userdata) {
    mdns_context_t *ctx = (mdns_context_t *)userdata;

    switch (state) {
        case AVAHI_CLIENT_S_RUNNING:
            // Connection to daemon established, publish our services
            register_services(ctx);
            break;

        case AVAHI_CLIENT_FAILURE:
            fprintf(stderr, "mDNS Error: Avahi client failure: %s\n", avahi_strerror(avahi_client_errno(c)));
            avahi_threaded_poll_quit(ctx->threaded_poll);
            break;

        case AVAHI_CLIENT_S_COLLISION:
        case AVAHI_CLIENT_S_REGISTERING:
            // State transitions, reset group
            if (ctx->group) {
                avahi_entry_group_reset(ctx->group);
            }
            break;

        default:
            break;
    }
}

static void entry_group_callback(AvahiEntryGroup *g, AvahiEntryGroupState state, void *userdata) {
    mdns_context_t *ctx = (mdns_context_t *)userdata;

    switch (state) {
        case AVAHI_ENTRY_GROUP_ESTABLISHED:
            printf("mDNS: Service successfully published and established on network.\n");
            break;

        case AVAHI_ENTRY_GROUP_COLLISION: {
            char *n;
            fprintf(stderr, "mDNS Warning: Service name collision, renaming...\n");
            
            n = avahi_alternative_service_name(ctx->service_name);
            strncpy(ctx->service_name, n, sizeof(ctx->service_name) - 1);
            avahi_free(n);

            char mac_clean[13];
            int j = 0;
            for (int i = 0; i < 17; i++) {
                if (ctx->device_id[i] != ':') {
                    mac_clean[j++] = ctx->device_id[i];
                }
            }
            mac_clean[j] = '\0';
            snprintf(ctx->raop_service_name, sizeof(ctx->raop_service_name), "%s@%s", mac_clean, ctx->service_name);

            avahi_entry_group_reset(g);
            register_services(ctx);
            break;
        }

        case AVAHI_ENTRY_GROUP_FAILURE:
            fprintf(stderr, "mDNS Error: Entry group failure: %s\n",
                    avahi_strerror(avahi_client_errno(ctx->client)));
            avahi_threaded_poll_quit(ctx->threaded_poll);
            break;

        case AVAHI_ENTRY_GROUP_UNCOMMITTED:
        case AVAHI_ENTRY_GROUP_REGISTERING:
        default:
            break;
    }
}
