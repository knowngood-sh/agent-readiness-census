# The knowngood verification rubric

This is the rubric [knowngood.sh](https://knowngood.sh) applies in
production, published so a score is reproducible. `check.py` implements it.

## One vocabulary

- **declared** — the site *says* something agent-relevant (an llms.txt, a
  robots signal). Cheap to fake, cheap to auto-generate.
- **probe-verified** — we fetched it and it behaved: correct status,
  correct content type, parseable, self-consistent.
- **behaviourally verified** — an agent completed a real outcome against
  it (a search answered, a tool call returned). The top of the ladder.

A census counts declarations. An index should list verifications. The gap
between those two numbers is most of the story.

## Signals

**STRONG** (a capability an agent can act on):

- `markdown_negotiation` — the homepage honours `Accept: text/markdown`
  with actual markdown.
- `markdown_url` — a markdown twin (e.g. `/index.md`) serves real markdown.
- `wellknown_api_catalog` — `/.well-known/api-catalog` is valid (RFC 9727).
- `wellknown_mcp_server_card` — `/.well-known/mcp/server-card.json` is
  valid JSON describing a server.
- `wellknown_oauth_as` — RFC 8414 authorization-server metadata.
- `wellknown_oauth_pr` — RFC 9728 protected-resource metadata.
- `wellknown_agent_skills` — agent-skills index parses.
- `wellknown_wba_dir` — Web Bot Auth key directory parses.

**MEDIUM** (agent-awareness, correctly implemented):

- `llms_txt` — `/llms.txt` returns 200, is not HTML, has a heading and at
  least one markdown link. (The strict rule matters: a large share of
  200-responses at this path are soft-404 error pages.)
- `named_ai_bots` — robots.txt addresses named AI agents deliberately.
- `link_headers` — the homepage advertises alternates/capabilities in
  `Link` headers.

**INFORMATIONAL** (reported, never scored — attribution pending):

- `openapi_json` — `/openapi.json` parses as OpenAPI. Real, but heavily
  platform-supplied; we attribute before we tier.
- `webmcp_markers` — WebMCP (`modelContext`) markers in homepage script.
  A majority of observed markers sit behind one CDN; until a headless
  list-never-invoke pass separates site-authored tools from injected
  scaffolding, markers score nothing.
- `auth_md` — `/.well-known/auth.md` agent-registration file present.

**WEAK signals never count.** A 200 status alone proves hosting, not
capability.

## Tiers

- **CONFIRMED** — at least 1 STRONG and at least 2 signals total
  (STRONG + MEDIUM).
- **PROBABLE** — exactly 1 STRONG, or 2+ MEDIUM.
- **DECLARED_ONLY** — declarations without a verifiable capability.
- Fetch errors bound the score honestly: if best-case and worst-case tiers
  differ, the verdict is UNCERTAIN, not the flattering end.

## Consent is absolute

If robots.txt declares `ai-input=no`, the site is never probed past
robots.txt and never listed, whatever was previously known. Listings are
earned by the probe; they cannot be bought, and they cannot be requested
around the probe.
