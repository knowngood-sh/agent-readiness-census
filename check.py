#!/usr/bin/env python3
"""check.py — agent-readiness scorecard for one host.

Stdlib only. Implements the knowngood.sh production rubric (see RUBRIC.md):
STRONG capabilities, MEDIUM awareness signals, INFO observations that score
nothing, tier = CONFIRMED / PROBABLE / DECLARED_ONLY / NONE.

Consent first: robots.txt is fetched before anything else. A site that
declares ai-input=no is not probed further (pass --owner to override on a
site you own).

Usage:
    python3 check.py example.com
    python3 check.py example.com --owner
    python3 check.py --selftest
"""

import argparse
import json
import re
import socket
import sys
import urllib.error
import urllib.request

UA = "KnownGood-Census/1.0 (+https://knowngood.sh/bot)"
TIMEOUT = 10
AI_BOTS = ("gptbot", "claudebot", "claude-web", "perplexitybot", "oai-searchbot",
           "google-extended", "applebot-extended", "ccbot", "bytespider",
           "anthropic-ai", "amazonbot", "meta-externalagent")
WEBMCP_RE = re.compile(r"modelContext|registerTool\s*\(|navigator\.modelContext")


def fetch(url, accept=None, max_bytes=262144):
    """GET url; return (status, headers-dict-lower, body-str) or (None, {}, err)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    if accept:
        req.add_header("Accept", accept)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read(max_bytes)
            hdrs = {k.lower(): v for k, v in r.headers.items()}
            return r.status, hdrs, body.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, ""
    except (urllib.error.URLError, socket.timeout, OSError, ValueError) as e:
        return None, {}, str(e)


def is_html(ctype, body):
    if "html" in (ctype or ""):
        return True
    return bool(re.search(r"<\s*(!doctype|html|head|body)\b", body[:2048], re.I))


def looks_markdown(body):
    return bool(re.search(r"^#{1,3}\s+\S", body, re.M)) or bool(
        re.search(r"\[[^\]]+\]\([^)]+\)", body))


def parse_robots(body):
    """Return dict: ai_input (yes/no/None), content_signal (bool), named_bots (list)."""
    out = {"ai_input": None, "content_signal": False, "named_bots": []}
    for line in body.splitlines():
        line = line.strip()
        low = line.lower()
        if low.startswith("content-signal:"):
            out["content_signal"] = True
            m = re.search(r"ai-input\s*=\s*(yes|no)", low)
            if m:
                out["ai_input"] = m.group(1)
        if low.startswith("user-agent:"):
            agent = low.split(":", 1)[1].strip()
            if agent in AI_BOTS and agent not in out["named_bots"]:
                out["named_bots"].append(agent)
    return out


def probe(host, owner=False, base=None):
    """Probe one host. Returns (signals, notes) — signals is a list of
    (bucket, name, detail); notes is a list of strings."""
    base = base or f"https://{host}"
    strong, medium, info, notes = [], [], [], []

    # 0. consent gate
    status, _h, body = fetch(f"{base}/robots.txt")
    robots = parse_robots(body if status == 200 else "")
    if status == 200 and robots["ai_input"] == "no":
        if not owner:
            return None, [f"{host} declares ai-input=no in robots.txt. "
                          "Consent is absolute: not probing further, and "
                          "knowngood will never probe or list this site. "
                          "(--owner overrides on a site you own.)"]
        notes.append("ai-input=no declared — probing ONLY because --owner was passed.")
    if status == 200 and robots["ai_input"] == "yes":
        notes.append("robots.txt declares ai-input=yes.")
    if robots["named_bots"]:
        medium.append(("named_ai_bots", ", ".join(robots["named_bots"])))
    if robots["content_signal"]:
        notes.append("Content-Signal present in robots.txt.")

    # 1. homepage: markdown negotiation + Link headers + WebMCP markers
    status, hdrs, body = fetch(base, accept="text/markdown, text/plain;q=0.9, */*;q=0.1")
    if status == 200:
        ctype = hdrs.get("content-type", "")
        if "markdown" in ctype and looks_markdown(body):
            strong.append(("markdown_negotiation", f"Accept: text/markdown honoured ({ctype})"))
        link = hdrs.get("link", "")
        if link and re.search(r'rel="?(alternate|service|api-catalog)"?', link):
            medium.append(("link_headers", link[:120]))
    elif status is None:
        notes.append(f"homepage unreachable: {body[:80]}")
    # plain-HTML fetch for WebMCP markers (negotiated fetch may not be HTML)
    status2, _h2, html = fetch(base)
    if status2 == 200 and WEBMCP_RE.search(html):
        info.append(("webmcp_markers", "modelContext markers in homepage source — "
                     "attribution (site-authored vs CDN-injected) not established; scores nothing"))

    # 2. markdown twin
    status, hdrs, body = fetch(f"{base}/index.md")
    if status == 200 and not is_html(hdrs.get("content-type", ""), body) and looks_markdown(body):
        strong.append(("markdown_url", "/index.md serves markdown"))

    # 3. llms.txt — strict rule
    status, hdrs, body = fetch(f"{base}/llms.txt")
    if status == 200:
        if not is_html(hdrs.get("content-type", ""), body) and \
           re.search(r"^#\s+\S", body, re.M) and re.search(r"\[[^\]]+\]\([^)]+\)", body):
            medium.append(("llms_txt", "valid: 200, non-HTML, heading, markdown links"))
        else:
            notes.append("/llms.txt returns 200 but fails the strict rule "
                         "(soft-404 or malformed) — scores nothing.")

    # 4. well-knowns
    def wk_json(path, name, label, required_key=None):
        s, h, b = fetch(f"{base}{path}")
        if s != 200 or is_html(h.get("content-type", ""), b):
            return
        try:
            doc = json.loads(b)
        except ValueError:
            return
        if required_key and required_key not in doc:
            return
        strong.append((name, label))

    wk_json("/.well-known/api-catalog", "wellknown_api_catalog", "RFC 9727 API catalog parses")
    wk_json("/.well-known/mcp/server-card.json", "wellknown_mcp_server_card",
            "MCP server card parses", required_key="name")
    wk_json("/.well-known/oauth-authorization-server", "wellknown_oauth_as",
            "RFC 8414 AS metadata parses", required_key="issuer")
    wk_json("/.well-known/oauth-protected-resource", "wellknown_oauth_pr",
            "RFC 9728 PR metadata parses", required_key="resource")
    wk_json("/.well-known/agent-skills/index.json", "wellknown_agent_skills",
            "agent-skills index parses")
    wk_json("/.well-known/http-message-signatures-directory", "wellknown_wba_dir",
            "Web Bot Auth key directory parses", required_key="keys")

    # 5. informational: openapi + auth.md
    s, h, b = fetch(f"{base}/openapi.json")
    if s == 200 and not is_html(h.get("content-type", ""), b):
        try:
            doc = json.loads(b)
            if "openapi" in doc or "swagger" in doc:
                info.append(("openapi_json", f"OpenAPI {doc.get('openapi', doc.get('swagger'))} "
                             "at root — reported, not tiered (platform attribution first)"))
        except ValueError:
            pass
    s, h, b = fetch(f"{base}/.well-known/auth.md")
    if s == 200 and not is_html(h.get("content-type", ""), b) and looks_markdown(b):
        info.append(("auth_md", "agent registration file present"))

    signals = [("STRONG", n, d) for n, d in strong] + \
              [("MEDIUM", n, d) for n, d in medium] + \
              [("INFO", n, d) for n, d in info]
    return signals, notes


def tier_for(signals):
    s = sum(1 for b, _n, _d in signals if b == "STRONG")
    m = sum(1 for b, _n, _d in signals if b == "MEDIUM")
    if s >= 1 and s + m >= 2:
        return "CONFIRMED"
    if s == 1 or m >= 2:
        return "PROBABLE"
    if s + m >= 1 or any(b == "INFO" for b, _n, _d in signals):
        return "DECLARED_ONLY"
    return "NONE"


def report(host, signals, notes):
    print(f"\nagent-readiness scorecard — {host}")
    print("=" * (28 + len(host)))
    if signals is None:
        for n in notes:
            print(n)
        return
    for bucket in ("STRONG", "MEDIUM", "INFO"):
        rows = [(n, d) for b, n, d in signals if b == bucket]
        if rows:
            print(f"\n{bucket}:")
            for n, d in rows:
                print(f"  [x] {n:28s} {d}")
    tier = tier_for(signals)
    print(f"\nTier: {tier}  (CONFIRMED needs >=1 STRONG and >=2 scored signals)")
    if notes:
        print("\nNotes:")
        for n in notes:
            print(f"  - {n}")
    missing = []
    have = {n for _b, n, _d in signals}
    if "markdown_negotiation" not in have and "markdown_url" not in have:
        missing.append("serve markdown (Accept: text/markdown, or an /index.md twin)")
    if "llms_txt" not in have:
        missing.append("a valid /llms.txt (heading + markdown links, non-HTML)")
    if "wellknown_mcp_server_card" not in have:
        missing.append("an MCP server card at /.well-known/mcp/server-card.json")
    if missing:
        print("\nNext moves: " + "; ".join(missing) + ".")
    print("\nRubric: https://github.com/knowngood-sh/agent-readiness-census/blob/main/RUBRIC.md")
    print("Get verified by the probe (listings are earned, not requested): https://knowngood.sh")


# ---------------------------------------------------------------- selftest
def selftest():
    import http.server
    import threading

    FIX = {
        "/robots.txt": (200, "text/plain", "User-agent: *\nAllow: /\nUser-agent: GPTBot\nAllow: /\n"),
        "/": (200, "text/markdown", "# Home\n\n[docs](/docs)\n"),
        "/index.md": (200, "text/markdown", "# Home\n\n[docs](/docs)\n"),
        "/llms.txt": (200, "text/plain", "# Site\n\n- [Docs](/docs.md)\n"),
        "/.well-known/mcp/server-card.json": (200, "application/json",
                                              '{"name":"t","version":"1.0"}'),
    }

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            st, ct, body = FIX.get(self.path, (404, "text/html", "<html>nope</html>"))
            self.send_response(st)
            self.send_header("Content-Type", ct)
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"

    ok = True

    def expect(cond, label):
        nonlocal ok
        print(("PASS: " if cond else "FAIL: ") + label)
        ok = ok and cond

    sig, notes = probe("selftest", base=base)
    names = {n for _b, n, _d in sig}
    expect("markdown_negotiation" in names, "markdown negotiation detected")
    expect("markdown_url" in names, "/index.md twin detected")
    expect("llms_txt" in names, "strict llms.txt detected")
    expect("wellknown_mcp_server_card" in names, "server card detected")
    expect("named_ai_bots" in names, "named AI bot stanza detected")
    expect(tier_for(sig) == "CONFIRMED", "tier CONFIRMED")

    FIX["/robots.txt"] = (200, "text/plain", "Content-Signal: ai-input=no\nUser-agent: *\nAllow: /\n")
    sig2, notes2 = probe("selftest", base=base)
    expect(sig2 is None and "ai-input=no" in notes2[0], "ai-input=no refuses probe")
    sig3, _n3 = probe("selftest", base=base, owner=True)
    expect(sig3 is not None, "--owner overrides on own site")

    FIX["/llms.txt"] = (200, "text/html", "<html><h1>404</h1></html>")
    FIX["/robots.txt"] = (200, "text/plain", "User-agent: *\nAllow: /\n")
    sig4, notes4 = probe("selftest", base=base)
    expect("llms_txt" not in {n for _b, n, _d in sig4}, "soft-404 llms.txt rejected")
    expect(any("strict rule" in n for n in notes4), "soft-404 explained in notes")

    empty_tier = tier_for([])
    expect(empty_tier == "NONE", "no signals -> NONE")
    expect(tier_for([("STRONG", "x", ""), ("MEDIUM", "y", "")]) == "CONFIRMED",
           "1 strong + 1 medium -> CONFIRMED")
    expect(tier_for([("STRONG", "x", "")]) == "PROBABLE", "1 strong alone -> PROBABLE")
    expect(tier_for([("MEDIUM", "x", ""), ("MEDIUM", "y", "")]) == "PROBABLE",
           "2 medium -> PROBABLE")
    srv.shutdown()
    print("ALL PASS" if ok else "FAILURES ABOVE")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("host", nargs="?", help="hostname, e.g. example.com")
    ap.add_argument("--owner", action="store_true",
                    help="probe despite ai-input=no (your own site only)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if not args.host:
        ap.error("host required (or --selftest)")
    host = args.host.strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
    signals, notes = probe(host, owner=args.owner)
    report(host, signals, notes)


if __name__ == "__main__":
    main()
