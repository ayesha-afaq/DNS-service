import socket, json, time, sys, config

counter = 0   # request ID counter, as in the spec

def query(sock, name, rtype):
    """Send one query (retrying with the SAME id). Returns (response, ms) or (None, ms)."""
    global counter
    counter += 1
    qid = counter
    msg = json.dumps({"id": qid, "type": "QUERY", "name": name,
                      "record_type": rtype}).encode("utf-8")
    start = time.perf_counter()
    for attempt in range(1, config.CLIENT_ATTEMPTS + 1):
        sock.sendto(msg, (config.RESOLVER_IP, config.RESOLVER_PORT))
        try:
            while True:
                data, _ = sock.recvfrom(config.BUFFER_SIZE)
                try:
                    r = json.loads(data.decode("utf-8"))
                except ValueError:
                    continue
                if r.get("id") == qid:
                    return r, (time.perf_counter() - start) * 1000
        except socket.timeout:
            print(f"  (timeout, attempt {attempt}/{config.CLIENT_ATTEMPTS})")
    return None, (time.perf_counter() - start) * 1000

def show(r, ms):
    if r is None:
        print("TIMEOUT: no response from resolver"); return
    if r["status"] == "OK":
        extra = f" via {r['cname_chain']}" if "cname_chain" in r else ""
        print(f"{r['name']} {r['record_type']} -> {r['value']} "
              f"(ttl {r['ttl']}s, source {r.get('source','?')}{extra}) [{ms:.2f} ms]")
    else:
        print(f"{r['status']}: {r.get('error','')} [{ms:.2f} ms]")

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(config.CLIENT_TIMEOUT)
    if len(sys.argv) >= 2:                       # one-shot:  python client.py www.campus.com A
        rtype = sys.argv[2].upper() if len(sys.argv) > 2 else "A"
        show(*query(sock, sys.argv[1], rtype)); return
    print("Type: <name> [A|CNAME]   (blank line to quit)")
    while True:
        line = input("> ").split()
        if not line: break
        show(*query(sock, line[0], line[1].upper() if len(line) > 1 else "A"))

if __name__ == "__main__":
    main()