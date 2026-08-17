"""Which mailbox provider actually receives a lead's mail.

The question this answers is "when we send to `info@zahnarzt-mueller.de`, whose
spam filter decides whether it lands" — Microsoft, Google, or one of the long
tail of hosters. It is the one campaign variable that has nothing to do with the
copy or the ICP, and Andrew already suspects it matters: two of his own campaigns
are literally named `… - Google` and `… - Office`, split by hand at scrape time.

**The answer is the domain's MX record, not anything Smartlead tells us.**
Smartlead does hold its own verdict — `esp_domain_type` on `GET /leads/{id}`,
which decodes as 0=other / 1=Google / 2=Microsoft (verified 2026-08-17 against
the two split campaigns above: every sampled lead in `… - Office` came back 2,
ten of twelve in `… - Google` came back 1). It is unusable here for two reasons.
It is one HTTP call *per lead*, so a 5,000-lead campaign would need 5,000 calls
before any analysis could start. And it is a snapshot taken when the lead was
imported, so it goes stale: `cortical.io` is labelled 2 (Microsoft) while its
live MX is Fastmail, and `techcitylabs.com` is labelled 0 (other) while its live
MX is Google.

An MX lookup has neither problem. It is keyed on the *domain*, so it is cached
once and reused by every campaign and every client that ever mails that domain;
it is live; and it costs no Smartlead quota at all. Measured on the real data:
203 lookups/second at 24 workers, 400/400 resolved on Dental Clinics - EU, so a
4,664-domain campaign resolves in about 25 seconds — once, ever.

Resolution is DNS-over-HTTPS rather than a DNS library, for the same reason
`app/sheets.py` is five REST calls instead of the Google SDK: it is a plain
httpx GET against a resolver, so `requirements.txt` and the image's pip layer
stay untouched. The stdlib cannot do MX at all (`socket` has no resolver access),
so the alternative was a new dependency.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx

from app import db

log = logging.getLogger("mailbox_provider")

# Public DoH resolvers, tried in order. Both speak the same `application/dns-json`
# shape. The fallback exists because a single resolver refusing us (rate limit,
# regional block on the droplet) would otherwise turn every domain into
# `unresolved` and silently empty the whole analysis.
_RESOLVERS = (
    "https://cloudflare-dns.com/dns-query",
    "https://dns.google/resolve",
)

_WORKERS = 24
_TIMEOUT = 8.0
# A backstop, not a real limit — the biggest campaign in the account has ~4.7k
# distinct domains. If a run ever wants more than this, something is wrong and
# the log line matters more than the extra lookups.
_MAX_LOOKUPS_PER_RUN = 20000
# Providers do migrate (a practice moves from IONOS to Microsoft 365), so a
# cached answer is not kept forever. Long, because the drift is slow and every
# re-check is a lookup we already paid for once.
_CACHE_DAYS = 180


# ---------------------------------------------------------------------------
# The provider table
# ---------------------------------------------------------------------------

# Display names. The keys are what goes in the database, so renaming a label is
# free but renaming a key is a migration.
PROVIDER_LABELS = {
    "microsoft": "Microsoft 365 / Outlook",
    "google": "Google Workspace / Gmail",
    "gateway": "Security gateway",
    "ionos": "IONOS",
    "strato": "Strato",
    "all-inkl": "All-Inkl",
    "godaddy": "GoDaddy",
    "one.com": "one.com",
    "ovh": "OVH",
    "zoho": "Zoho",
    "apple": "iCloud",
    "fastmail": "Fastmail",
    "proton": "Proton",
    "yandex": "Yandex",
    "united-internet": "GMX / web.de",
    "mailbox.org": "mailbox.org",
    "hostinger": "Hostinger",
    "namecheap": "Namecheap",
    "rackspace": "Rackspace",
    "infomaniak": "Infomaniak",
    "hetzner": "Hetzner",
    "domainfactory": "DomainFactory",
    "united-domains": "United Domains",
    "jimdo": "Jimdo",
    "amazon-ses": "Amazon SES",
    "titan": "Titan",
    "other": "Other / self-hosted",
    "no-mx": "No mail server",
    "unresolved": "Could not be checked",
}

# MX hostname suffix -> provider. Matched longest-suffix-first (see `_PATTERNS`),
# so a more specific entry always beats a more general one.
#
# Every entry below `gateway` is here because it actually showed up in this
# account's campaigns; the point of naming them is that "Other" is otherwise a
# meaningless 79% bar on the German campaigns. Anything unmatched is `other`,
# and the raw MX host is stored alongside so the table can grow later without
# re-querying DNS.
_MX_MAP = {
    # Microsoft. `mail.protection.outlook.com` is the M365 tenant form;
    # `mx.microsoft` is the newer one; hotmail/outlook.com are consumer.
    "protection.outlook.com": "microsoft",
    "outlook.com": "microsoft",
    "mx.microsoft": "microsoft",
    "hotmail.com": "microsoft",
    "msn.com": "microsoft",
    "microsoft.com": "microsoft",
    # Google.
    "google.com": "google",
    "googlemail.com": "google",
    "gmail.com": "google",
    # Filtering gateways. These sit in FRONT of a mailbox we cannot see, so the
    # real provider is unknowable from DNS — but a gateway is itself the hardest
    # deliverability case, which is why it is a bucket rather than "other".
    "pphosted.com": "gateway",
    "ppe-hosted.com": "gateway",
    "mimecast.com": "gateway",
    "mimecast.co.za": "gateway",
    "barracudanetworks.com": "gateway",
    "iphmx.com": "gateway",
    "hornetsecurity.com": "gateway",
    "mailspamprotection.com": "gateway",
    "spamexperts.com": "gateway",
    "antispamcloud.com": "gateway",
    "mailcontrol.com": "gateway",
    "trendmicro.com": "gateway",
    "sophos.com": "gateway",
    "mailinblack.com": "gateway",
    "securemail.pro": "gateway",
    "fortimailcloud.com": "gateway",
    "securence.com": "gateway",
    "secure-mailgate.com": "gateway",
    "cloudflare.net": "gateway",
    "nospamproxy.de": "gateway",
    # The long tail, mostly European hosters.
    "ionos.de": "ionos",
    "ionos.com": "ionos",
    "ionos.fr": "ionos",
    "ionos.es": "ionos",
    "ionos.co.uk": "ionos",
    "1and1.com": "ionos",
    "kundenserver.de": "ionos",
    "rzone.de": "strato",
    "strato.de": "strato",
    "kasserver.com": "all-inkl",
    "secureserver.net": "godaddy",
    "one.com": "one.com",
    "ovh.net": "ovh",
    "ovh.com": "ovh",
    "zoho.com": "zoho",
    "zoho.eu": "zoho",
    "zohomail.com": "zoho",
    "icloud.com": "apple",
    "me.com": "apple",
    "messagingengine.com": "fastmail",
    "fastmail.com": "fastmail",
    "protonmail.ch": "proton",
    "proton.me": "proton",
    "yandex.net": "yandex",
    "yandex.ru": "yandex",
    "gmx.net": "united-internet",
    "web.de": "united-internet",
    "mailbox.org": "mailbox.org",
    "hostinger.com": "hostinger",
    "privateemail.com": "namecheap",
    "emailsrvr.com": "rackspace",
    "infomaniak.ch": "infomaniak",
    "your-server.de": "hetzner",
    "agenturserver.de": "domainfactory",
    "ispgateway.de": "domainfactory",
    "udag.de": "united-domains",
    "jimdo.com": "jimdo",
    "amazonses.com": "amazon-ses",
    "titan.email": "titan",
}

# Longest suffix first so `protection.outlook.com` is tested before
# `outlook.com`, and `zoho.eu` before any hypothetical `.eu` entry.
_PATTERNS = sorted(_MX_MAP.items(), key=lambda item: -len(item[0]))

# The three-way split Andrew actually asked the question in. Everything that is
# neither of the two giants is "other" at the headline, and keeps its own name in
# the table underneath.
def group_of(provider: str) -> str:
    if provider in ("microsoft", "google"):
        return provider
    if provider in ("unresolved", "no-mx"):
        return "unknown"
    return "other"


GROUP_LABELS = {
    "microsoft": "Microsoft",
    "google": "Google",
    "other": "Other providers",
    "unknown": "Unknown",
}


def label_for(provider: str) -> str:
    return PROVIDER_LABELS.get(provider, provider)


def domain_of(email: str | None) -> str | None:
    """The mail domain of an address, or None if it isn't one. Outcome rows fall
    back to a stats_id when the email is missing, so this has to reject
    non-addresses rather than trust its input."""
    if not email or "@" not in email:
        return None
    domain = email.rsplit("@", 1)[-1].strip().lower().rstrip(".")
    return domain if domain and "." in domain else None


def classify(mx_hosts: list[str]) -> str:
    """Provider from a domain's MX hosts, in preference order.

    Walks the list rather than only reading the primary: a domain whose first MX
    is an unrecognised host but whose backup is `alt1.aspmx.l.google.com` is a
    Google domain, and calling it `other` would be wrong. An empty list is a
    domain that cannot receive mail at all, which is a real and useful answer —
    those addresses were never going to arrive."""
    if not mx_hosts:
        return "no-mx"
    for host in mx_hosts:
        for suffix, provider in _PATTERNS:
            if host == suffix or host.endswith("." + suffix):
                return provider
    return "other"


# ---------------------------------------------------------------------------
# DNS over HTTPS
# ---------------------------------------------------------------------------

def _mx_hosts(client: httpx.Client, domain: str) -> list[str] | None:
    """MX hostnames for a domain, sorted by preference. None means the lookup
    itself failed — distinct from `[]`, which means the domain answered and has
    no MX at all."""
    for resolver in _RESOLVERS:
        try:
            resp = client.get(
                resolver,
                params={"name": domain, "type": "MX"},
                headers={"accept": "application/dns-json"},
            )
            if resp.status_code >= 400:
                continue
            data = resp.json()
        except (httpx.HTTPError, ValueError):
            continue
        # 0 = NOERROR, 3 = NXDOMAIN. Anything else (SERVFAIL, REFUSED) is this
        # resolver's problem, so fall through and let the next one try.
        status = data.get("Status")
        if status not in (0, 3):
            continue
        records = []
        for answer in data.get("Answer") or []:
            # An MX query also returns the CNAMEs it followed; only type 15 is
            # an MX record.
            if answer.get("type") != 15:
                continue
            value = (answer.get("data") or "").strip().rstrip(".")
            if not value:
                continue
            parts = value.split(None, 1)
            if len(parts) == 2 and parts[0].isdigit():
                records.append((int(parts[0]), parts[1].lower().rstrip(".")))
            else:
                records.append((0, parts[0].lower().rstrip(".")))
        return [host for _, host in sorted(records) if host]
    return None


def _lookup(client: httpx.Client, domain: str) -> tuple[str, str, str | None]:
    hosts = _mx_hosts(client, domain)
    if hosts is None:
        return domain, "unresolved", None
    return domain, classify(hosts), (hosts[0] if hosts else None)


def resolve(domains, progress=None) -> dict[str, str]:
    """domain -> provider for every domain given, hitting DNS only for the ones
    that aren't already cached.

    Opens its own short database sessions rather than taking a connection,
    deliberately: an open SQLite write transaction is an exclusive writer lock,
    and holding one across ~25 seconds of network calls would block the scan,
    every send and every webhook for the duration — the same mistake
    `webhook._process_reply` was making before it was split (see CLAUDE.md).
    Reads the cache, closes, does the network, then writes in batches.
    """
    wanted = {d for d in (domains or []) if d}
    if not wanted:
        return {}

    cutoff = (datetime.now(timezone.utc) - timedelta(days=_CACHE_DAYS)).isoformat()
    with db.db_session() as conn:
        cached = db.get_mailbox_domains(conn, sorted(wanted))
    known = {
        row["domain"]: row["provider"]
        for row in cached
        # A failed lookup is cached too (so one dead resolver doesn't re-storm
        # DNS on every re-analysis), but it is retried on the next run rather
        # than kept for six months.
        if row["provider"] != "unresolved" and (row["checked_at"] or "") >= cutoff
    }

    missing = sorted(wanted - set(known))
    if len(missing) > _MAX_LOOKUPS_PER_RUN:
        log.warning(
            "mailbox_provider: %d domains to resolve, capping at %d",
            len(missing), _MAX_LOOKUPS_PER_RUN,
        )
        missing = missing[:_MAX_LOOKUPS_PER_RUN]

    if missing:
        if progress:
            progress(f"Checking who hosts {len(missing):,} recipient domains…")
        done = 0
        # One client shared by every worker (httpx.Client is thread-safe), with a
        # pool big enough that they never queue behind each other. This is not a
        # tidiness point: a client per lookup means a fresh TLS handshake per
        # domain, which took the measured rate from ~200/s to a crawl and turned
        # a 25-second step into one that had not finished after ten minutes.
        limits = httpx.Limits(max_connections=_WORKERS * 2, max_keepalive_connections=_WORKERS)
        with httpx.Client(timeout=_TIMEOUT, limits=limits) as client:
            with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
                batch: list[tuple[str, str, str | None]] = []
                for result in pool.map(lambda d: _lookup(client, d), missing):
                    batch.append(result)
                    if len(batch) >= 500:
                        with db.db_session() as conn:
                            db.upsert_mailbox_domains(conn, batch)
                        done += len(batch)
                        batch = []
                        if progress:
                            progress(f"Checked {done:,} of {len(missing):,} recipient domains…")
                if batch:
                    with db.db_session() as conn:
                        db.upsert_mailbox_domains(conn, batch)
        with db.db_session() as conn:
            for row in db.get_mailbox_domains(conn, missing):
                known[row["domain"]] = row["provider"]

    return {domain: known.get(domain, "unresolved") for domain in wanted}
