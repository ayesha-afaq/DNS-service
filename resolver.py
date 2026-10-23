# resolver.py - Machine 2. Caching resolver (sequential, one query at a time).
import socket, json, time
import config

cache = {}   # {(name, record_type): (rec_type, value, expiry_monotonic)}
stats = {"queries": 0, "hits": 0, "misses": 0, "upstream_bytes": 0}
_upstream_id = 0


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def error(qid, name, rtype, status, text):
    return {"id": qid, "type": "RESPONSE", "status": status, "name": name,
            "record_type": rtype, "error": text}


def next_upstream_id():
    """Resolver's own id space for upstream questions, independent of client ids."""
    global _upstream_id
    _upstream_id = _upstream_id % 65535 + 1
    return _upstream_id


def ask_auth(sock, name, rtype, acct):
    """Ask the authoritative server (retrying with the SAME id).
    acct accumulates bytes/datagrams exchanged. Returns the reply or None."""
    uid = next_upstream_id()
    msg = json.dumps({"id": uid, "type": "QUERY", "name": name,
                      "record_type": rtype}).encode("utf-8")
    for attempt in range(1, config.UPSTREAM_RETRIES + 1):
        sock.sendto(msg, (config.AUTH_IP, config.AUTH_PORT))
        acct["bytes"] += len(msg)
        acct["dgrams"] += 1
        deadline = time.monotonic() + config.UPSTREAM_TIMEOUT
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                data, _ = sock.recvfrom(config.BUFFER_SIZE)
            except socket.timeout:
                break
            except ConnectionResetError:      # Windows: auth server not listening
                time.sleep(min(0.2, max(0.0, remaining)))
                continue
            acct["bytes"] += len(data)
            acct["dgrams"] += 1
            try:
                reply = json.loads(data.decode("utf-8"))
            except ValueError:
                continue
            # accept only the reply to THIS question (id AND name), ignore stale ones
            if isinstance(reply, dict) and reply.get("id") == uid and reply.get("name") == name:
                return reply
        log(f"  upstream timeout for {name} {rtype} (attempt {attempt}/{config.UPSTREAM_RETRIES})")
    return None


def resolve(up, qid, name, rtype):
    acct = {"bytes": 0, "dgrams": 0}
    chain, cur, used_auth, min_ttl = [], name, False, None
    for _ in range(config.MAX_CNAME_DEPTH + 1):
        key = (cur, rtype)
        entry = cache.get(key)
        now = time.monotonic()
        if entry and now < entry[2]:
            rec_type, value, expiry = entry
            ttl_left = int(round(expiry - now))
            log(f"  CACHE HIT  {cur} {rtype} (ttl left {ttl_left}s)")
        else:
            log(f"  CACHE MISS {cur} {rtype}")
            reply = ask_auth(up, cur, rtype, acct)
            if reply is None:
                return error(qid, name, rtype, "TIMEOUT", "authoritative server did not respond")
            if reply.get("status") != "OK":
                return error(qid, name, rtype, reply.get("status", "SERVFAIL"), reply.get("error", ""))
            used_auth = True
            rec_type, value, ttl_left = reply["record_type"], reply["value"], int(reply["ttl"])
            cache[key] = (rec_type, value, time.monotonic() + ttl_left)
        min_ttl = ttl_left if min_ttl is None else min(min_ttl, ttl_left)
        if rec_type == rtype or rtype == "CNAME":
            stats["upstream_bytes"] += acct["bytes"]
            out = {"id": qid, "type": "RESPONSE", "status": "OK", "name": name,
                   "record_type": rtype, "value": value, "ttl": min_ttl,
                   "source": "AUTH" if used_auth else "CACHE",
                   "upstream_bytes": acct["bytes"], "upstream_dgrams": acct["dgrams"]}
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
        try:
            data, addr = sock.recvfrom(config.BUFFER_SIZE)
        except ConnectionResetError:
            continue                  # Windows: client's port closed before our reply arrived
        try:
            req = json.loads(data.decode("utf-8"))
            kind = req.get("type")
            if kind == "FLUSH":       # lab helper: empty the cache so the next query is a miss
                qid = int(req.get("id", 0))
            elif kind == "QUERY":
                qid = int(req["id"])
                name = str(req["name"]).lower().strip()
                rtype = str(req["record_type"]).upper().strip()
            else:
                raise ValueError("unknown message type")
        except Exception:
            sock.sendto(json.dumps(error(0, "", "", "FORMERR", "malformed query")).encode(), addr)
            log(f"{addr[0]} malformed query -> FORMERR")
            continue

        if kind == "FLUSH":
            n = len(cache)
            cache.clear()
            reply = {"id": qid, "type": "RESPONSE", "status": "OK", "name": "", "record_type": "",
                     "value": f"flushed {n} entries"}
            log(f"{addr[0]} FLUSH -> {n} entries removed")
        else:
            log(f"{addr[0]} id={qid} {name} {rtype}")
            stats["queries"] += 1
            if rtype not in ("A", "CNAME"):
                reply = error(qid, name, rtype, "NOTIMP", "record type not supported")
            else:
                reply = resolve(up, qid, name, rtype)
                if reply.get("source") == "CACHE":
                    stats["hits"] += 1
                elif reply.get("source") == "AUTH":
                    stats["misses"] += 1
        sock.sendto(json.dumps(reply).encode("utf-8"), addr)
        log(f"  -> {reply['status']} {reply.get('value','')} {reply.get('source','')}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log(f"Resolver stopped. queries={stats['queries']} hits={stats['hits']} "
            f"misses={stats['misses']} upstream_bytes={stats['upstream_bytes']}")
