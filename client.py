# client.py - Machine 1. Sends queries to the resolver. Also imported by benchmark.py.
import socket, json, time, sys, random
import config

# Request ID counter, as in the spec. Starts at a random offset so that separate
# one-shot runs of this script do not reuse the same ids.
counter = random.randint(1, 30000)


def exchange(sock, payload, qid):
    """Send payload to the resolver (retrying with the SAME id) and wait for the reply.
    Returns (reply_or_None, elapsed_ms, info) where info counts bytes/attempts."""
    msg = json.dumps(payload).encode("utf-8")
    info = {"sent": 0, "recv": 0, "attempts": 0}
    start = time.perf_counter()
    for attempt in range(1, config.CLIENT_ATTEMPTS + 1):
        info["attempts"] = attempt
        sock.sendto(msg, (config.RESOLVER_IP, config.RESOLVER_PORT))
        info["sent"] += len(msg)
        deadline = time.monotonic() + config.CLIENT_TIMEOUT
        reason = "timeout"
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                data, _ = sock.recvfrom(config.BUFFER_SIZE)
            except socket.timeout:
                break
            except ConnectionResetError:     # Windows: nothing listening on resolver port
                reason = "resolver unreachable"
                time.sleep(min(1.0, max(0.0, remaining)))
                break
            try:
                r = json.loads(data.decode("utf-8"))
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("id") == qid:
                info["recv"] += len(data)
                return r, (time.perf_counter() - start) * 1000, info
        print(f"  ({reason}, attempt {attempt}/{config.CLIENT_ATTEMPTS})")
    return None, (time.perf_counter() - start) * 1000, info


def query(sock, name, rtype="A"):
    """One DNS-style query. Returns (reply_or_None, ms, info)."""
    global counter
    counter += 1
    return exchange(sock, {"id": counter, "type": "QUERY", "name": name,
                           "record_type": rtype}, counter)


def flush_cache(sock):
    """Ask the resolver to empty its cache (lab helper used by benchmark.py)."""
    global counter
    counter += 1
    return exchange(sock, {"id": counter, "type": "FLUSH"}, counter)


def show(r, ms, info=None):
    if r is None:
        print(f"TIMEOUT: no response from resolver [{ms:.2f} ms]")
        return
    if r["status"] == "OK":
        extra = f" via {r['cname_chain']}" if "cname_chain" in r else ""
        print(f"{r['name']} {r['record_type']} -> {r['value']} "
              f"(ttl {r['ttl']}s, source {r.get('source','?')}{extra}) [{ms:.2f} ms]")
    else:
        print(f"{r['status']}: {r.get('error','')} [{ms:.2f} ms]")


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if len(sys.argv) >= 2:                       # one-shot:  python client.py www.campus.com A
        rtype = sys.argv[2].upper() if len(sys.argv) > 2 else "A"
        show(*query(sock, sys.argv[1], rtype))
        return
    print("Type: <name> [A|CNAME]   ('flush' empties the resolver cache, blank line to quit)")
    while True:
        try:
            line = input("> ").split()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            break
        if line[0].lower() == "flush":
            r, ms, _ = flush_cache(sock)
            print(r.get("value", r) if r else "TIMEOUT: no response from resolver")
            continue
        show(*query(sock, line[0], line[1].upper() if len(line) > 1 else "A"))


if __name__ == "__main__":
    main()
