# ---- Central settings. Edit ONLY this file when IPs change. ----
# For real deployment replace with the real IPs from ipconfig / ip addr.
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

AUTH_IP = "10.73.117.86"        # Machine 3 (authoritative server)
AUTH_PORT = 5300

RESOLVER_IP = "10.73.117.196"    # Machine 2 (resolver)
RESOLVER_PORT = 5301

BUFFER_SIZE = 4096           # max bytes read per datagram

# Absolute path, so the server works no matter which folder you start it from.
ZONE_FILE = os.path.join(BASE_DIR, "zone.txt")

# Resolver -> authoritative reliability
UPSTREAM_TIMEOUT = 1.0       # seconds to wait per attempt
UPSTREAM_RETRIES = 2         # total attempts per upstream question
MAX_CNAME_DEPTH = 5          # aliases to follow before giving up (loop protection)

# Client -> resolver reliability.
# The client must wait longer than the resolver's WORST case, otherwise it
# retries while the resolver is still busy. Worst case = every hop in a
# maximum-length CNAME chain times out on every attempt.
RESOLVER_WORST_CASE = (MAX_CNAME_DEPTH + 1) * UPSTREAM_RETRIES * UPSTREAM_TIMEOUT
CLIENT_TIMEOUT = RESOLVER_WORST_CASE + 1.0   # seconds per attempt (13 s with the values above)
CLIENT_ATTEMPTS = 3

# Failure demo: authoritative ignores every Nth query (0 = never drop)
DROP_EVERY_N = 0

# Benchmark settings
BENCH_ITERATIONS = 100
RESULTS_DIR = os.path.join(BASE_DIR, "results")
IP_UDP_HEADER_BYTES = 28     # 20 (IPv4) + 8 (UDP), added per datagram in byte counts
