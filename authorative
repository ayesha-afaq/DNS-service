# authoritative.py - Machine 3. Answers queries from zone.txt (plain text, held in a dict).
import socket, json, os, time
import config

SUPPORTED = ("A", "CNAME")
zone = {}          # {(name, record_type): (value, ttl)}
zone_mtime = 0


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def parse_zone(path):
    """Read the zone file and return a new dict. Bad lines are skipped, never fatal."""
    new = {}
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) != 4:
                log(f"zone line {lineno}: expected 4 fields, skipped: {line}")
                continue
            name, rtype, value, ttl = parts
            if any(c in name + value for c in "[]()/<>"):
                log(f"zone line {lineno}: looks like pasted markdown/URL, skipped: {line}")
                continue
            rtype = rtype.upper()
            if rtype not in SUPPORTED:
                log(f"zone line {lineno}: unsupported type {rtype}, skipped")
                continue
            try:
                ttl = int(ttl)
                if ttl < 0:
                    raise ValueError
            except ValueError:
                log(f"zone line {lineno}: bad TTL '{parts[3]}', skipped")
                continue
            new[(name.lower().rstrip("."), rtype)] = (value.lower().rstrip("."), ttl)
    return new


def load_zone():
    global zone
    zone = parse_zone(config.ZONE_FILE)
    log(f"Zone loaded: {len(zone)} records from {config.ZONE_FILE}")


def reload_if_changed():
    """Hot reload. On any failure keep serving the old zone."""
    global zone_mtime
    try:
        m = os.path.getmtime(config.ZONE_FILE)
    except OSError:
        return                       # file briefly missing (editor save): keep old zone
    if m == zone_mtime:
        return
    zone_mtime = m                   # don't retry (and re-log) until the file changes again
    try:
        load_zone()
    except Exception as e:
        log(f"zone reload failed ({e}); keeping previous zone")


def error(qid, name, rtype, status, text):
    return {"id": qid, "type": "RESPONSE", "status": status, "name": name,
            "record_type": rtype, "error": text}


def handle(data):
    try:
        req = json.loads(data.decode("utf-8"))
        if req.get("type") != "QUERY":
            raise ValueError("not a QUERY")
        qid = int(req["id"])
        name = str(req["name"]).lower().strip()
        rtype = str(req["record_type"]).upper().strip()
    except Exception:
        return error(0, "", "", "FORMERR", "malformed query")

    if rtype not in SUPPORTED:
        return error(qid, name, rtype, "NOTIMP", "record type not supported")

    def ok(t):
        value, ttl = zone[(name, t)]
        return {"id": qid, "type": "RESPONSE", "status": "OK", "name": name,
                "record_type": t, "value": value, "ttl": ttl, "source": "AUTH"}

    if (name, rtype) in zone:
        return ok(rtype)
    if rtype == "A" and (name, "CNAME") in zone:     # alias: resolver will follow it
        return ok("CNAME")
    if any(n == name for (n, _) in zone):
        return error(qid, name, rtype, "NODATA", "name exists but has no such record type")
    return error(qid, name, rtype, "NXDOMAIN", "name does not exist")


def main():
    global zone_mtime
    zone_mtime = os.path.getmtime(config.ZONE_FILE)
    load_zone()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", config.AUTH_PORT))
    log(f"Authoritative server listening on UDP {config.AUTH_PORT}")
    count = 0
    while True:
        try:
            data, addr = sock.recvfrom(config.BUFFER_SIZE)
        except ConnectionResetError:
            continue                 # Windows: ICMP port-unreachable from a vanished peer
        count += 1
        if config.DROP_EVERY_N and count % config.DROP_EVERY_N == 0:
            log(f"DROPPED query #{count} from {addr[0]} (failure demo)")
            continue
        reload_if_changed()
        try:
            reply = handle(data)
        except Exception as e:
            reply = error(0, "", "", "SERVFAIL", f"internal error: {e}")
        try:
            sock.sendto(json.dumps(reply).encode("utf-8"), addr)
        except OSError as e:
            log(f"send to {addr[0]} failed: {e}")
            continue
        log(f"{addr[0]} id={reply['id']} {reply.get('name','?')} {reply.get('record_type','?')} -> {reply['status']}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Authoritative server stopped")