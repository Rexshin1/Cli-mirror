#include "mdns.h"
#include <stdio.h>
#include <stdlib.h>
#include <signal.h>
#include <unistd.h>
#include <string.h>

static volatile int keep_running = 1;

static void handle_signal(int sig) {
    (void)sig;
    keep_running = 0;
}

int main(int argc, char *argv[]) {
    mdns_context_t mdns_ctx;
    char friendly_name[128] = "CliMirror";
    int port_airplay = 7000;
    int port_raop = 5000;

    // Command-line arguments parsing
    for (int i = 1; i < argc; ++i) {
        if ((strcmp(argv[i], "-n") == 0 || strcmp(argv[i], "--name") == 0) && i + 1 < argc) {
            strncpy(friendly_name, argv[++i], sizeof(friendly_name) - 1);
        } else if ((strcmp(argv[i], "-p") == 0 || strcmp(argv[i], "--port") == 0) && i + 1 < argc) {
            port_airplay = atoi(argv[++i]);
        } else if ((strcmp(argv[i], "-r") == 0 || strcmp(argv[i], "--raop-port") == 0) && i + 1 < argc) {
            port_raop = atoi(argv[++i]);
        } else if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--help") == 0) {
            printf("Usage: %s [options]\n", argv[0]);
            printf("Options:\n");
            printf("  -n, --name <name>       Set the friendly name for AirPlay discovery (default: CliMirror)\n");
            printf("  -p, --port <port>       Set the AirPlay RTSP port (default: 7000)\n");
            printf("  -r, --raop-port <port>  Set the RAOP Audio port (default: 5000)\n");
            printf("  -h, --help              Show this help menu\n");
            return 0;
        }
    }

    // Set up signal handlers for clean exit
    struct sigaction sa;
    sa.sa_handler = handle_signal;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = 0;
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    printf("=========================================\n");
    printf("        cli-mirror-engine starting       \n");
    printf("=========================================\n");
    printf("Friendly Name : %s\n", friendly_name);
    printf("AirPlay Port  : %d\n", port_airplay);
    printf("RAOP Port     : %d\n", port_raop);

    // Initialize mDNS discovery
    if (mdns_init(&mdns_ctx, friendly_name, port_airplay, port_raop) < 0) {
        fprintf(stderr, "Failed to initialize mDNS. Exiting.\n");
        return EXIT_FAILURE;
    }

    printf("Discovery active. Press Ctrl+C to terminate.\n");

    // Wait loop
    while (keep_running) {
        sleep(1);
    }

    printf("\nShutting down engine gracefully...\n");
    mdns_cleanup(&mdns_ctx);
    printf("Engine stopped.\n");

    return EXIT_SUCCESS;
}
