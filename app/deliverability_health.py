"""Mailbox rehabilitation and sending-domain health monitoring.

Smartlead warmup reputation is a useful operational signal, not an independent
measurement of Gmail/Microsoft inbox placement. This module deliberately shows
that distinction: mailbox phases use Smartlead; domain health uses DNS auth and
an optional external blacklist provider; Smart Delivery remains a separate
placement test when the client's plan includes it.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app import client_assets, db, smartlead
from app.config import settings

log = logging.getLogger("deliverability_health")

# The starting numbers for every client. Each container keeps its own copy in
# its own app_settings once it is edited on the Health tab, so clients are
# configured independently with no tenancy in the code.
PHASES = {
    "rehab": {"cold": 5, "warm_min": 35, "warm_max": 45},
    "comeback": {"cold": 15, "warm_min": 25, "warm_max": 30},
    "full": {"cold": 25, "warm_min": 18, "warm_max": 25},
}
POLICY_SETTING_KEY = "deliverability_policy"
# Smartlead rejects total_warmup_per_day outside 1-50.
_WARM_CEILING = 50
_COLD_CEILING = 500

_lock = threading.Lock()
_running = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _reputation(account: dict) -> int | None:
    value = (account.get("warmup_details") or {}).get("warmup_reputation")
    if value is None:
        return None
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    if not match:
        return None
    return max(0, min(100, round(float(match.group()))))


def _domain(email: str) -> str:
    value = (email or "").strip().lower()
    return value.rsplit("@", 1)[1] if "@" in value else ""


def _env_policy() -> dict:
    return {
        "auto_apply": bool(settings.deliverability_auto_apply),
        "auto_apply_source": "env",
        "threshold": settings.mailbox_rehab_threshold,
        "stable_days": settings.mailbox_phase_stable_days,
        "phases": {name: dict(values) for name, values in PHASES.items()},
    }


def load_policy(conn=None) -> dict:
    """This client's switch and stage numbers: dashboard edits over env defaults."""
    policy = _env_policy()
    if conn is None:
        with db.db_session() as own:
            raw = db.get_setting(own, POLICY_SETTING_KEY)
    else:
        raw = db.get_setting(conn, POLICY_SETTING_KEY)
    try:
        stored = json.loads(raw) if raw else {}
    except ValueError:
        log.warning("ignoring unreadable %s setting", POLICY_SETTING_KEY)
        stored = {}
    if isinstance(stored.get("auto_apply"), bool):
        policy["auto_apply"] = stored["auto_apply"]
        policy["auto_apply_source"] = "dashboard"
    for key in ("threshold", "stable_days"):
        if isinstance(stored.get(key), int):
            policy[key] = stored[key]
    for name, values in (stored.get("phases") or {}).items():
        if name in policy["phases"] and isinstance(values, dict):
            for field in ("cold", "warm_min", "warm_max"):
                if isinstance(values.get(field), int):
                    policy["phases"][name][field] = values[field]
    return policy


def _int_in(value: Any, low: int, high: int, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a whole number")
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a whole number")
    if not low <= number <= high:
        raise ValueError(f"{label} must be between {low} and {high}")
    return number


def save_policy(data: dict) -> dict:
    """Validate and store a Health-tab edit.

    ``reset`` restores the default numbers but keeps the switch where it is,
    so resetting numbers can never silently turn automation on or off.
    """
    current = load_policy()
    if data.get("reset"):
        stored: dict = {"auto_apply": current["auto_apply"]}
    else:
        stored = {
            "auto_apply": bool(data.get("auto_apply", current["auto_apply"])),
            "threshold": _int_in(data.get("threshold", current["threshold"]), 1, 100, "Rehab threshold"),
            "stable_days": _int_in(data.get("stable_days", current["stable_days"]), 1, 60, "Perfect days per step"),
            "phases": {},
        }
        incoming = data.get("phases") or {}
        for name, label in (("rehab", "Rehab"), ("comeback", "Comeback"), ("full", "Full")):
            values = {**current["phases"][name], **(incoming.get(name) or {})}
            cold = _int_in(values["cold"], 1, _COLD_CEILING, f"{label} cold emails")
            warm_min = _int_in(values["warm_min"], 1, _WARM_CEILING, f"{label} warmup minimum")
            warm_max = _int_in(values["warm_max"], 1, _WARM_CEILING, f"{label} warmup maximum")
            if warm_min > warm_max:
                raise ValueError(f"{label} warmup minimum is above its maximum")
            stored["phases"][name] = {"cold": cold, "warm_min": warm_min, "warm_max": warm_max}
    with db.db_session() as conn:
        db.set_setting(conn, POLICY_SETTING_KEY, json.dumps(stored))
        return load_policy(conn)


def _initial_phase(account: dict, phases: dict | None = None) -> str:
    """Preserve an already-throttled mailbox on the first local check.

    The live Mindaptive account already contains rehab/comeback-shaped limits.
    Treating every >=90 reputation mailbox as full on first discovery would
    erase that operational state as soon as auto-apply was enabled.
    """
    phases = phases or PHASES
    warm = account.get("warmup_details") or {}
    try:
        cold = int(account.get("message_per_day"))
    except (TypeError, ValueError):
        return "full"
    try:
        warm_max = int(warm.get("warmup_max_count") or warm.get("max_email_per_day"))
    except (TypeError, ValueError):
        warm_max = 0
    # Above comeback's warm ceiling, not at rehab's own: mailboxes throttled
    # by hand before the rehab range became 35-45 sit at 5 / 33-40, and must
    # still be recognised as rehab rather than promoted to full.
    if cold <= phases["rehab"]["cold"] and warm_max > phases["comeback"]["warm_max"]:
        return "rehab"
    if cold <= phases["comeback"]["cold"] and 0 < warm_max <= phases["comeback"]["warm_max"]:
        return "comeback"
    return "full"


def _next_phase(
    previous: Any, reputation: int | None, today: str, policy: dict | None = None
) -> tuple[str, int, str | None]:
    policy = policy or _env_policy()
    old_phase = previous["phase"] if previous else "full"
    old_days = int(previous["perfect_days"] or 0) if previous else 0
    last_day = previous["last_observation_day"] if previous else None
    if reputation is None:
        return old_phase, old_days, None
    if reputation < policy["threshold"]:
        transition = f"{old_phase}->rehab" if old_phase != "rehab" else None
        return "rehab", 0, transition

    # Only one streak increment per UTC calendar day. Repeated manual checks
    # cannot speed a mailbox through the five-day safety gate.
    is_new_day = today != last_day
    if old_phase == "rehab":
        days = old_days + 1 if reputation == 100 and is_new_day else (old_days if reputation == 100 else 0)
        if days >= policy["stable_days"]:
            return "comeback", 0, "rehab->comeback"
        return "rehab", days, None
    if old_phase == "comeback":
        days = old_days + 1 if reputation == 100 and is_new_day else (old_days if reputation == 100 else 0)
        if days >= policy["stable_days"]:
            return "full", 0, "comeback->full"
        return "comeback", days, None
    return "full", 0, None


def _doh(name: str, record_type: str) -> list[str]:
    response = httpx.get(
        "https://dns.google/resolve",
        params={"name": name, "type": record_type},
        headers={"Accept": "application/dns-json"},
        timeout=12.0,
    )
    response.raise_for_status()
    data = response.json()
    return [str(row.get("data", "")).strip('"') for row in data.get("Answer", [])]


def _authentication(domain: str) -> tuple[dict, str | None]:
    try:
        mx = _doh(domain, "MX")
        txt = _doh(domain, "TXT")
        dmarc_txt = _doh(f"_dmarc.{domain}", "TXT")
        spf = next((v for v in txt if v.lower().startswith("v=spf1")), None)
        dmarc = next((v for v in dmarc_txt if v.lower().startswith("v=dmarc1")), None)
        policy_match = re.search(r"(?:^|;)\s*p\s*=\s*(none|quarantine|reject)", dmarc or "", re.I)
        policy = policy_match.group(1).lower() if policy_match else None
        return {
            "mx": bool(mx),
            "mx_records": mx[:5],
            "spf": bool(spf),
            "spf_record": spf,
            "dmarc": bool(dmarc),
            "dmarc_policy": policy,
            "dmarc_record": dmarc,
            "dkim": "not_checked_selector_unknown",
        }, None
    except Exception as exc:
        return {}, f"DNS check failed: {exc}"


def _apivoid_blacklist(domain: str) -> tuple[list[str], list[str], str | None]:
    """Return detected and checked APIVoid engines for one sending domain.

    An empty/malformed engine collection is an error, never a clean result.
    That distinction matters because a provider outage must not turn a domain
    green or erase the last known listing.
    """
    if not settings.apivoid_api_key:
        return [], [], "Blacklist lookup not configured (APIVOID_API_KEY missing)"
    try:
        response = httpx.post(
            "https://api.apivoid.com/v2/domain-reputation",
            headers={
                "Content-Type": "application/json",
                "X-API-Key": settings.apivoid_api_key,
            },
            json={"host": domain},
            timeout=25.0,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            payload = payload["data"]
        blacklists = payload.get("blacklists") if isinstance(payload, dict) else None
        engines = blacklists.get("engines") if isinstance(blacklists, dict) else None
        rows = list(engines.values()) if isinstance(engines, dict) else engines
        if not isinstance(rows, list) or not rows:
            raise ValueError("APIVoid returned no blacklist engines")

        listings: list[str] = []
        checked: list[str] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            checked.append(name)
            detected = item.get("detected")
            if detected is True or str(detected).strip().lower() in {"1", "true", "yes"}:
                listings.append(name)
        if not checked:
            raise ValueError("APIVoid returned no named blacklist engines")
        return sorted(set(listings)), sorted(set(checked)), None
    except Exception as exc:
        return [], [], f"APIVoid blacklist check failed: {exc}"


def _notify(payload: dict) -> None:
    if not settings.deliverability_alert_webhook_url:
        return
    try:
        httpx.post(
            settings.deliverability_alert_webhook_url,
            json={"client": client_assets.CLIENT_LABEL, "observed_at": _iso(), **payload},
            timeout=15.0,
        ).raise_for_status()
    except Exception:
        log.exception("deliverability alert webhook failed")


def _apply_phase(account_id: int, target: dict, auto_apply: bool) -> tuple[str | None, int | None]:
    if not auto_apply:
        return "monitor_only", None
    if settings.dry_run:
        return "dry_run", None
    smartlead.update_email_account_limit(account_id, target["cold"])
    _, variation = smartlead.update_email_account_warmup(
        account_id, minimum=target["warm_min"], maximum=target["warm_max"]
    )
    return "applied", int(variation)


def run_health_check(*, force_domains: bool = False) -> dict:
    """Refresh all mailboxes, advance phases, and refresh due domains."""
    global _running
    if not _lock.acquire(blocking=False):
        return {"started": False, "reason": "already_running"}
    _running = True
    started = _now()
    alerts: list[dict] = []
    with db.db_session() as conn:
        cur = conn.execute(
            "INSERT INTO deliverability_runs(started_at,status) VALUES (?, 'running')",
            (_iso(started),),
        )
        run_id = cur.lastrowid
    try:
        policy = load_policy()
        phases = policy["phases"]
        accounts = list(smartlead.list_email_accounts())
        domains: set[str] = set()
        today = started.date().isoformat()
        for account in accounts:
            account_id = int(account["id"])
            email = (account.get("from_email") or account.get("username") or "").strip().lower()
            domain = _domain(email)
            if domain:
                domains.add(domain)
            reputation = _reputation(account)
            warm = account.get("warmup_details") or {}
            with db.db_session() as conn:
                previous = conn.execute(
                    "SELECT * FROM mailbox_health_state WHERE account_id=?", (account_id,)
                ).fetchone()
            phase_seed = previous or {
                "phase": _initial_phase(account, phases),
                "perfect_days": 0,
                "last_observation_day": None,
            }
            phase, perfect_days, transition = _next_phase(phase_seed, reputation, today, policy)
            target = phases[phase]
            action = None
            variation_confirmed = previous["variation_confirmed"] if previous else None
            applied_at = previous["last_applied_at"] if previous else None
            apply_error = None
            # Apply on a phase transition, first discovery, or visible cap drift.
            current_limit = account.get("message_per_day")
            current_warm_min = warm.get("warmup_min_count")
            current_warm_max = warm.get("warmup_max_count") or warm.get("max_email_per_day")
            needs_apply = bool(
                previous is None
                or transition
                or (current_limit is not None and int(current_limit) != target["cold"])
                or (current_warm_min is not None and int(current_warm_min) != target["warm_min"])
                or (current_warm_max is not None and int(current_warm_max) != target["warm_max"])
            )
            if needs_apply:
                try:
                    action, variation_confirmed = _apply_phase(account_id, target, policy["auto_apply"])
                    if action == "applied":
                        applied_at = _iso()
                except Exception as exc:
                    action = "failed"
                    apply_error = str(exc)[:500]
            actual_cold = target["cold"] if action == "applied" else account.get("message_per_day")
            actual_warm_min = target["warm_min"] if action == "applied" else warm.get("warmup_min_count")
            actual_warm_max = target["warm_max"] if action == "applied" else (warm.get("warmup_max_count") or warm.get("max_email_per_day"))
            phase_since = _iso(started) if transition or not previous else previous["phase_since"]
            with db.db_session() as conn:
                conn.execute(
                    """INSERT INTO mailbox_health_state(
                           account_id,email,domain,phase,reputation,perfect_days,last_observation_day,
                           phase_since,last_checked_at,smtp_ok,imap_ok,warmup_status,blocked_reason,
                           cold_daily_limit,warm_min,warm_max,target_cold,target_warm_min,target_warm_max,
                           variation_confirmed,last_applied_at,apply_error)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(account_id) DO UPDATE SET
                         email=excluded.email,domain=excluded.domain,phase=excluded.phase,
                         reputation=excluded.reputation,perfect_days=excluded.perfect_days,
                         last_observation_day=excluded.last_observation_day,phase_since=excluded.phase_since,
                         last_checked_at=excluded.last_checked_at,smtp_ok=excluded.smtp_ok,imap_ok=excluded.imap_ok,
                         warmup_status=excluded.warmup_status,blocked_reason=excluded.blocked_reason,
                         cold_daily_limit=excluded.cold_daily_limit,warm_min=excluded.warm_min,
                         warm_max=excluded.warm_max,target_cold=excluded.target_cold,
                         target_warm_min=excluded.target_warm_min,target_warm_max=excluded.target_warm_max,
                         variation_confirmed=excluded.variation_confirmed,
                         last_applied_at=excluded.last_applied_at,apply_error=excluded.apply_error""",
                    (
                        account_id,email,domain,phase,reputation,perfect_days,today,phase_since,_iso(),
                        int(bool(account.get("is_smtp_success"))),int(bool(account.get("is_imap_success"))),
                        warm.get("status"),warm.get("blocked_reason"),actual_cold,actual_warm_min,
                        actual_warm_max,target["cold"],target["warm_min"],target["warm_max"],
                        variation_confirmed,applied_at,apply_error,
                    ),
                )
                conn.execute(
                    """INSERT INTO mailbox_health_history(
                           account_id,email,checked_at,reputation,phase,perfect_days,transition,action,error)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (account_id,email,_iso(),reputation,phase,perfect_days,transition,action,apply_error),
                )
            if transition:
                alerts.append({"type": "mailbox_phase_changed", "email": email, "reputation": reputation, "transition": transition})
            was_connected = bool(previous and previous["smtp_ok"] and previous["imap_ok"])
            is_connected = bool(account.get("is_smtp_success") and account.get("is_imap_success"))
            if (previous is None or was_connected) and not is_connected:
                alerts.append({"type": "mailbox_connection_issue", "email": email, "smtp_ok": bool(account.get("is_smtp_success")), "imap_ok": bool(account.get("is_imap_success"))})
            if warm.get("blocked_reason") and (not previous or previous["blocked_reason"] != warm.get("blocked_reason")):
                alerts.append({"type": "mailbox_warmup_blocked", "email": email, "reason": warm.get("blocked_reason")})

        now = _now()
        for domain in sorted(domains):
            with db.db_session() as conn:
                previous = conn.execute("SELECT * FROM domain_health_state WHERE domain=?", (domain,)).fetchone()
            auth, dns_error = _authentication(domain)
            due = force_domains or not previous or not previous["blacklist_checked_at"]
            if not due and previous:
                try:
                    due = datetime.fromisoformat(previous["blacklist_checked_at"]) <= now - timedelta(hours=max(1, settings.domain_blacklist_check_hours))
                except ValueError:
                    due = True
            if due:
                listings, checked, blacklist_error = _apivoid_blacklist(domain)
                if blacklist_error:
                    # Preserve the last successful result during an outage. A
                    # failed lookup is unknown, not evidence of delisting.
                    listings = json.loads(previous["listings_json"] or "[]") if previous else []
                    checked = json.loads(previous["checked_json"] or "[]") if previous else []
                    blacklist_checked_at = previous["blacklist_checked_at"] if previous else None
                else:
                    blacklist_checked_at = _iso(now)
            else:
                listings = json.loads(previous["listings_json"] or "[]")
                checked = json.loads(previous["checked_json"] or "[]")
                blacklist_error = previous["error"]
                blacklist_checked_at = previous["blacklist_checked_at"]
            auth_warning = not auth.get("mx") or not auth.get("spf") or not auth.get("dmarc") or auth.get("dmarc_policy") == "none"
            status = "listed" if listings else ("unknown" if blacklist_error or dns_error else ("warning" if auth_warning else "healthy"))
            old_listings = set(json.loads(previous["listings_json"] or "[]")) if previous else set()
            new_listings = sorted(set(listings) - old_listings)
            error = "; ".join(x for x in (dns_error, blacklist_error) if x) or None
            with db.db_session() as conn:
                conn.execute(
                    """INSERT INTO domain_health_state(domain,checked_at,blacklist_checked_at,status,listings_json,auth_json,checked_json,error)
                       VALUES (?,?,?,?,?,?,?,?)
                       ON CONFLICT(domain) DO UPDATE SET checked_at=excluded.checked_at,
                         blacklist_checked_at=excluded.blacklist_checked_at,status=excluded.status,
                         listings_json=excluded.listings_json,auth_json=excluded.auth_json,
                         checked_json=excluded.checked_json,error=excluded.error""",
                    (domain,_iso(now),blacklist_checked_at,status,json.dumps(listings),json.dumps(auth),json.dumps(checked),error),
                )
            if new_listings:
                alerts.append({"type": "domain_blacklisted", "domain": domain, "lists": new_listings})
            old_auth = json.loads(previous["auth_json"] or "{}") if previous else {}
            old_auth_warning = bool(previous) and (
                not old_auth.get("mx")
                or not old_auth.get("spf")
                or not old_auth.get("dmarc")
                or old_auth.get("dmarc_policy") == "none"
            )
            if auth_warning and (not previous or not old_auth_warning):
                alerts.append({"type": "domain_dns_warning", "domain": domain, "authentication": auth})

        with db.db_session() as conn:
            conn.execute(
                "UPDATE deliverability_runs SET finished_at=?,status='done',mailbox_count=?,domain_count=? WHERE id=?",
                (_iso(), len(accounts), len(domains), run_id),
            )
        for alert in alerts:
            _notify(alert)
        return {"started": True, "mailboxes": len(accounts), "domains": len(domains), "alerts": len(alerts)}
    except Exception as exc:
        log.exception("deliverability health check failed")
        with db.db_session() as conn:
            conn.execute(
                "UPDATE deliverability_runs SET finished_at=?,status='failed',error=? WHERE id=?",
                (_iso(), str(exc)[:1000], run_id),
            )
        return {"started": True, "error": str(exc)}
    finally:
        _running = False
        _lock.release()


def trigger(*, force_domains: bool = False) -> bool:
    if _running:
        return False
    thread = threading.Thread(target=run_health_check, kwargs={"force_domains": force_domains}, daemon=True)
    thread.start()
    return True


def snapshot() -> dict:
    with db.db_session() as conn:
        mailboxes = [dict(row) for row in conn.execute("SELECT * FROM mailbox_health_state ORDER BY phase,email")]
        domains = [dict(row) for row in conn.execute(
            """SELECT * FROM domain_health_state
               ORDER BY CASE status WHEN 'listed' THEN 0 WHEN 'warning' THEN 1
                                    WHEN 'unknown' THEN 2 ELSE 3 END, domain"""
        )]
        run = conn.execute("SELECT * FROM deliverability_runs ORDER BY id DESC LIMIT 1").fetchone()
    for row in domains:
        row["listings"] = json.loads(row.pop("listings_json") or "[]")
        row["auth"] = json.loads(row.pop("auth_json") or "{}")
        row["checked"] = json.loads(row.pop("checked_json") or "[]")
    policy = load_policy()
    counts = {phase: sum(1 for row in mailboxes if row["phase"] == phase) for phase in PHASES}
    last_mailbox = max((row["last_checked_at"] for row in mailboxes), default=None)
    last_blacklist = max((row["blacklist_checked_at"] for row in domains if row["blacklist_checked_at"]), default=None)
    def next_at(value: str | None, hours: int) -> str | None:
        return (datetime.fromisoformat(value) + timedelta(hours=max(1, hours))).isoformat() if value else None
    return {
        "mailboxes": mailboxes,
        "domains": domains,
        "counts": counts,
        "running": _running,
        "last_run": dict(run) if run else None,
        "next_mailbox_check": next_at(last_mailbox, settings.mailbox_health_check_hours),
        "next_blacklist_check": next_at(last_blacklist, settings.domain_blacklist_check_hours),
        "automation": "active" if policy["auto_apply"] and not settings.dry_run else ("dry_run" if policy["auto_apply"] else "monitor_only"),
        "blacklist_provider": "APIVoid" if settings.apivoid_api_key else "not_configured",
        "policy": {**policy, "defaults": PHASES, "dry_run": settings.dry_run},
    }
