# ---- Central settings. Edit ONLY this file when IPs change. ----
# For real deployment replace with the real IPs from ipconfig / ip addr.

AUTH_IP = "127.0.0.1"        # Machine 3 (authoritative server)
AUTH_PORT = 5300

RESOLVER_IP = "127.0.0.1"    # Machine 2 (resolver)
RESOLVER_PORT = 5301

BUFFER_SIZE = 4096           # max bytes read per datagram
ZONE_FILE = "zone.txt"

# Resolver -> authoritative reliability
#How long and how many times the resolver waits for the authoritative server
UPSTREAM_TIMEOUT = 1.0       # seconds per attempt 
UPSTREAM_RETRIES = 2         # total attempts
MAX_CNAME_DEPTH = 5          #How many aliases to follow before giving up (loop protection)

# Client -> resolver reliability (must be longer than the resolver's total wait)
CLIENT_TIMEOUT = 5.0
CLIENT_ATTEMPTS = 3

# Failure demo: authoritative ignores every Nth query (0 = never drop)
DROP_EVERY_N = 0