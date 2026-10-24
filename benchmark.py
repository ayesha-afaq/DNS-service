# benchmark.py - Machine 1. Measurements for R6 and the sustainability section.
#
# Experiment 1 (latency): for each name, repeat N times:
#     flush resolver cache -> query (forced MISS) -> query again (HIT)
#   Records latency and bytes for every query.
# Experiment 2 (ttl): query each name once per second for a fixed time and record
#   whether each answer came from CACHE or AUTH. Shows hit ratio and traffic saved
#   for a short vs a long TTL (freshness vs traffic reduction).
#
# Usage (resolver + authoritative must be running):
#   python benchmark.py                          # both experiments
#   python benchmark.py --only latency -n 200
#   python benchmark.py --only ttl --ttl-seconds 60
#   python benchmark.py --tag loss               # adds _loss to file names (use with DROP_EVERY_N)
#
# Output goes to results/: latency.csv, latency_summary.csv, latency_compare.csv,
#   ttl.csv, ttl_summary.csv and (if matplotlib is installed) latency.png, ttl.png
import argparse, csv, math, os, socket, statistics, sys, time
import config, client

HDR = config.IP_UDP_HEADER_BYTES


def make_row(i, name, case, r, ms, info):
    ok = r is not None
    up_bytes = r.get("upstream_bytes", 0) if ok else 0
    up_dg = r.get("upstream_dgrams", 0) if ok else 0
    cl_bytes = info["sent"] + info["recv"]
    cl_dg = info["attempts"] + (1 if ok else 0)
    return {"iteration": i, "name": name, "case": case,
            "source": r.get("source", "") if ok else "",
            "status": r.get("status", "") if ok else "TIMEOUT",
            "latency_ms": round(ms, 3), "attempts": info["attempts"],
            "client_bytes": cl_bytes, "upstream_bytes": up_bytes,
            "client_dgrams": cl_dg, "upstream_dgrams": up_dg,
            # payload bytes on every hop + IP/UDP headers for every datagram
            "ip_bytes": cl_bytes + up_bytes + HDR * (cl_dg + up_dg)}


def valid(row):
    """Keep only rows that behaved as intended (a 'MISS' really went to AUTH, etc.)."""
    if row["status"] != "OK":
        return False
    return (row["case"] == "MISS" and row["source"] == "AUTH") or \
           (row["case"] == "HIT" and row["source"] == "CACHE")


def pct95(xs):
    xs = sorted(xs)
    return xs[max(0, math.ceil(0.95 * len(xs)) - 1)]


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"  saved {os.path.relpath(path, config.BASE_DIR)}")


# ---------------------------------------------------------------- experiment 1
def run_latency(sock, names, n):
    rows = []
    for name in names:
        client.query(sock, name, "A")            # warm-up (ARP, socket, imports)
        print(f"latency: {name} x{n}")
        for i in range(1, n + 1):
            client.flush_cache(sock)
            r, ms, info = client.query(sock, name, "A")
            rows.append(make_row(i, name, "MISS", r, ms, info))
            r, ms, info = client.query(sock, name, "A")
            rows.append(make_row(i, name, "HIT", r, ms, info))
    return rows


def summarise_latency(rows, names):
    summary, compare = [], []
    by = {}
    for name in names:
        for case in ("MISS", "HIT"):
            sel = [r for r in rows if r["name"] == name and r["case"] == case]
            good = [r for r in sel if valid(r)]
            if not good:
                continue
            lat = [r["latency_ms"] for r in good]
            by[(name, case)] = {
                "mean": statistics.mean(lat),
                "ip_bytes": statistics.mean(r["ip_bytes"] for r in good),
                "payload": statistics.mean(r["client_bytes"] + r["upstream_bytes"] for r in good)}
            summary.append({
                "name": name, "case": case, "samples": len(good), "discarded": len(sel) - len(good),
                "mean_ms": round(statistics.mean(lat), 3), "median_ms": round(statistics.median(lat), 3),
                "stdev_ms": round(statistics.stdev(lat), 3) if len(lat) > 1 else 0.0,
                "min_ms": round(min(lat), 3), "p95_ms": round(pct95(lat), 3), "max_ms": round(max(lat), 3),
                "mean_payload_bytes": round(by[(name, case)]["payload"], 1),
                "mean_ip_bytes": round(by[(name, case)]["ip_bytes"], 1),
                "mean_attempts": round(statistics.mean(r["attempts"] for r in good), 3)})
    for name in names:
        if (name, "MISS") in by and (name, "HIT") in by:
            m, h = by[(name, "MISS")], by[(name, "HIT")]
            compare.append({
                "name": name, "miss_mean_ms": round(m["mean"], 3), "hit_mean_ms": round(h["mean"], 3),
                "slowdown_miss_vs_hit": round(m["mean"] / h["mean"], 2),
                "latency_saved_pct": round((m["mean"] - h["mean"]) / m["mean"] * 100, 1),
                "miss_ip_bytes": round(m["ip_bytes"], 1), "hit_ip_bytes": round(h["ip_bytes"], 1),
                "bytes_saved_per_hit": round(m["ip_bytes"] - h["ip_bytes"], 1),
                "bytes_saved_pct": round((m["ip_bytes"] - h["ip_bytes"]) / m["ip_bytes"] * 100, 1)})
    return summary, compare, by


def plot_latency(names, by, path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  (matplotlib not installed: pip install matplotlib to get graphs)")
        return
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 4))
    w, x = 0.35, range(len(names))
    for off, case in ((-w / 2, "MISS"), (w / 2, "HIT")):
        a1.bar([i + off for i in x], [by.get((n, case), {}).get("mean", 0) for n in names], w, label=case)
        a2.bar([i + off for i in x], [by.get((n, case), {}).get("ip_bytes", 0) for n in names], w, label=case)
    for a, t, yl in ((a1, "Mean latency", "ms"), (a2, "Bytes on the network per query", "bytes (IP level)")):
        a.set_xticks(list(x)); a.set_xticklabels(names, rotation=15); a.set_title(t); a.set_ylabel(yl); a.legend()
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)
    print(f"  saved {os.path.relpath(path, config.BASE_DIR)}")


# ---------------------------------------------------------------- experiment 2
def run_ttl(sock, names, seconds):
    rows = []
    for name in names:
        client.flush_cache(sock)
        print(f"ttl: {name} for {seconds}s (1 query/second)")
        t0 = time.monotonic()
        for s in range(seconds):
            wait = t0 + s - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            r, ms, info = client.query(sock, name, "A")
            row = make_row(s, name, "", r, ms, info)
            row["case"] = row["source"] or "TIMEOUT"
            row["second"] = s
            rows.append(row)
    return rows


def summarise_ttl(rows, names):
    out = []
    for name in names:
        sel = [r for r in rows if r["name"] == name and r["status"] == "OK"]
        if not sel:
            continue
        misses = [r for r in sel if r["source"] == "AUTH"]
        hits = [r for r in sel if r["source"] == "CACHE"]
        actual = sum(r["ip_bytes"] for r in sel)
        # what the traffic would have been with NO cache: every query costs a miss
        miss_cost = statistics.mean(r["ip_bytes"] for r in misses) if misses else 0
        nocache = miss_cost * len(sel)
        out.append({"name": name, "queries": len(sel), "misses": len(misses), "hits": len(hits),
                    "hit_ratio_pct": round(len(hits) / len(sel) * 100, 1),
                    "ip_bytes_with_cache": actual, "ip_bytes_without_cache": round(nocache),
                    "traffic_saved_pct": round((nocache - actual) / nocache * 100, 1) if nocache else 0})
    return out


def plot_ttl(rows, names, path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    fig, ax = plt.subplots(figsize=(7, 4))
    for name in names:
        sel = [r for r in rows if r["name"] == name]
        tot, ys = 0, []
        for r in sel:
            tot += r["ip_bytes"]
            ys.append(tot)
        ax.plot([r["second"] for r in sel], ys, label=name)
    ax.set_xlabel("seconds"); ax.set_ylabel("cumulative bytes on network"); ax.set_title("Traffic over time by TTL")
    ax.legend(); fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)
    print(f"  saved {os.path.relpath(path, config.BASE_DIR)}")


def print_table(title, rows):
    if not rows:
        return
    print(f"\n== {title} ==")
    keys = list(rows[0].keys())
    widths = [max(len(k), *(len(str(r[k])) for r in rows)) for k in keys]
    print("  ".join(k.ljust(w) for k, w in zip(keys, widths)))
    for r in rows:
        print("  ".join(str(r[k]).ljust(w) for k, w in zip(keys, widths)))


def main():
    p = argparse.ArgumentParser(description="Mini DNS benchmark")
    p.add_argument("-n", "--iterations", type=int, default=config.BENCH_ITERATIONS)
    p.add_argument("--names", nargs="+", default=["www.campus.com", "portal.campus.com"],
                   help="names for the latency experiment (portal is a CNAME: miss costs 2 upstream trips)")
    p.add_argument("--ttl-names", nargs="+", default=["short.campus.com", "www.campus.com", "long.campus.com"])
    p.add_argument("--ttl-seconds", type=int, default=30)
    p.add_argument("--only", choices=["latency", "ttl"], help="run just one experiment")
    p.add_argument("--tag", default="", help="suffix for output files, e.g. 'loss'")
    a = p.parse_args()
    suffix = f"_{a.tag}" if a.tag else ""
    os.makedirs(config.RESULTS_DIR, exist_ok=True)
    out = lambda f: os.path.join(config.RESULTS_DIR, f)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    r, _, _ = client.query(sock, "www.campus.com", "A")
    if r is None:
        sys.exit("Resolver not reachable. Start authoritative.py and resolver.py first and check config.py.")

    if a.only in (None, "latency"):
        rows = run_latency(sock, a.names, a.iterations)
        summary, compare, by = summarise_latency(rows, a.names)
        write_csv(out(f"latency{suffix}.csv"), rows)
        write_csv(out(f"latency_summary{suffix}.csv"), summary)
        write_csv(out(f"latency_compare{suffix}.csv"), compare)
        plot_latency(a.names, by, out(f"latency{suffix}.png"))
        print_table("latency summary", summary)
        print_table("hit vs miss", compare)

    if a.only in (None, "ttl"):
        rows = run_ttl(sock, a.ttl_names, a.ttl_seconds)
        summary = summarise_ttl(rows, a.ttl_names)
        write_csv(out(f"ttl{suffix}.csv"), rows)
        write_csv(out(f"ttl_summary{suffix}.csv"), summary)
        plot_ttl(rows, a.ttl_names, out(f"ttl{suffix}.png"))
        print_table("ttl experiment", summary)


if __name__ == "__main__":
    main()