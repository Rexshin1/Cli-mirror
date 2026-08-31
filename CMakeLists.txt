cmake_minimum_required(VERSION 3.10)
project(cli-mirror-engine C)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)

# Add compiler warnings and optimizations
add_compile_options(-Wall -Wextra -O2)

# Find PkgConfig to locate Avahi libraries
find_package(PkgConfig REQUIRED)

# Check and import Avahi libraries
pkg_check_modules(AVAHI_CLIENT REQUIRED avahi-client)
pkg_check_modules(AVAHI_COMMON REQUIRED avahi-common)

# Include directories
include_directories(
    src/core
    ${AVAHI_CLIENT_INCLUDE_DIRS}
    ${AVAHI_COMMON_INCLUDE_DIRS}
)

# Link directories
link_directories(
    ${AVAHI_CLIENT_LIBRARY_DIRS}
    ${AVAHI_COMMON_LIBRARY_DIRS}
)

# Source files
set(SOURCES
    src/core/main.c
    src/core/mdns.c
)

# Executable target
add_executable(cli-mirror-engine ${SOURCES})

# Link libraries
target_link_libraries(cli-mirror-engine
    ${AVAHI_CLIENT_LIBRARIES}
    ${AVAHI_COMMON_LIBRARIES}
)

# Print status messages
message(STATUS "Avahi Client Include Dirs: ${AVAHI_CLIENT_INCLUDE_DIRS}")
message(STATUS "Avahi Client Libraries: ${AVAHI_CLIENT_LIBRARIES}")
