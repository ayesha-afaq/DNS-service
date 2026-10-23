# resolver.py - Machine 2. Caching resolver (sequential, one query at a time).
import socket, json, time
import config

cache = {}   # {(name, record_type): (rec_type, value, expiry_monotonic)}

def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)

def error(qid, name, rtype, status, text):
    return {"id": qid, "type": "RESPONSE", "status": status, "name": name,
            "record_type": rtype, "error": text}

def ask_auth(sock, qid, name, rtype):
    """Query the authoritative server with retries (same id). Returns reply or None."""
    msg = json.dumps({"id": qid, "type": "QUERY", "name": name,
                      "record_type": rtype}).encode("utf-8")
    for attempt in range(1, config.UPSTREAM_RETRIES + 1):
        sock.sendto(msg, (config.AUTH_IP, config.AUTH_PORT))
        deadline = time.monotonic() + config.UPSTREAM_TIMEOUT
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                data, _ = sock.recvfrom(config.BUFFER_SIZE)
                reply = json.loads(data.decode("utf-8"))
                if reply.get("id") == qid:
                    return reply
            except socket.timeout:
                break
            except Exception:
                continue
        log(f"  upstream timeout for {name} {rtype} (attempt {attempt}/{config.UPSTREAM_RETRIES})")
    return None

def resolve(up, qid, name, rtype):
    chain, cur, used_auth, min_ttl = [], name, False, None
    for _ in range(config.MAX_CNAME_DEPTH + 1):
        key = (cur, rtype)
        entry = cache.get(key)
        now = time.monotonic()
        if entry and now < entry[2]:
            rec_type, value, expiry = entry
            ttl_left = int(round(expiry - now))
            log(f"  CACHE HIT  {cur} {rtype}")
        else:
            log(f"  CACHE MISS {cur} {rtype}")
            reply = ask_auth(up, qid, cur, rtype)
            if reply is None:
                return error(qid, name, rtype, "TIMEOUT", "authoritative server did not respond")
            if reply.get("status") != "OK":
                return error(qid, name, rtype, reply.get("status", "SERVFAIL"), reply.get("error", ""))
            used_auth = True
            rec_type, value, ttl_left = reply["record_type"], reply["value"], int(reply["ttl"])
            cache[key] = (rec_type, value, time.monotonic() + ttl_left)
        min_ttl = ttl_left if min_ttl is None else min(min_ttl, ttl_left)
        if rec_type == rtype or rtype == "CNAME":
            out = {"id": qid, "type": "RESPONSE", "status": "OK", "name": name,
                   "record_type": rtype, "value": value, "ttl": min_ttl,
                   "source": "AUTH" if used_auth else "CACHE"}
            if chain:
                out["cname_chain"] = chain
            return out
        chain.append(value)       # got a CNAME: follow it
        cur = value
    return error(qid, name, rtype, "SERVFAIL", "CNAME chain too long")

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", config.RESOLVER_PORT))
    up = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    log(f"Resolver listening on UDP {config.RESOLVER_PORT}, upstream {config.AUTH_IP}:{config.AUTH_PORT}")
    while True:
        data, addr = sock.recvfrom(config.BUFFER_SIZE)
        try:
            req = json.loads(data.decode("utf-8"))
            if req.get("type") != "QUERY":
                raise ValueError("not a QUERY")
            qid = int(req["id"])
            name = str(req["name"]).lower().strip()
            rtype = str(req["record_type"]).upper().strip()
        except Exception:
            sock.sendto(json.dumps(error(0, "", "", "FORMERR", "malformed query")).encode(), addr)
            log(f"{addr[0]} malformed query -> FORMERR")
            continue
        log(f"{addr[0]} id={qid} {name} {rtype}")
        if rtype not in ("A", "CNAME"):
            reply = error(qid, name, rtype, "NOTIMP", "record type not supported")
        else:
            reply = resolve(up, qid, name, rtype)
        sock.sendto(json.dumps(reply).encode("utf-8"), addr)
        log(f"  -> {reply['status']} {reply.get('value','')} {reply.get('source','')}")

if __name__ == "__main__":
    main()