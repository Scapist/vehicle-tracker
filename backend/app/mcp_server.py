"""MCP server for AI assistants (Claude Desktop, Claude Code, ...) at /mcp. Off unless MCP_ENABLED=true.

Every request needs `Authorization: Bearer <token>`, a personal access token made in Settings → AI assistants.
The token decides the account, and every tool only ever sees that account's data, through the same ownership
checks and services the app uses. The assistant can read, log km and services, and attach receipts; it can't
edit or delete anything.

The tools are plain functions taking (db, user, ...), so they are tested without any MCP plumbing; the
`@mcp.tool` wrappers below only find the user and open a database session."""
import base64
import binascii
import hashlib
import logging
import secrets
import time
from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import func, select
from starlette.responses import JSONResponse

from app import auth
from app import models as m
from app.api.deps import user_vehicle_ids, visible_service_types
from app.bot.logic import BIG_JUMP_KM
from app.clock import today_local
from app.config import settings
from app.db import SessionLocal
from app.domain.status import ORDER
from app.services import evaluator_hook, odometer, records, reports, status

log = logging.getLogger("mcp")
TOKEN_PREFIX = "vt_"
UPLOAD_LINK_TTL = 15 * 60
MAX_ATTACHMENTS = 30
UPLOAD_PREFIX = "vu_"
# link -> (user id, service id, expires, id of the access token that made it)
_upload_links: dict[str, tuple[int, int, float, int | None]] = {}


# ---------- tokens ----------

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def user_for_token(db, token: str) -> m.User | None:
    row = db.scalar(select(m.ApiToken).where(m.ApiToken.token_hash == hash_token(token),
                                             m.ApiToken.revoked_at.is_(None)))
    if not row:
        return None
    user = db.get(m.User, row.user_id)
    if user and not may_use_mcp(user):
        return None  # e.g. MCP_USERS was changed back to "owner" after a member made a token
    row.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return user


def may_use_mcp(user: m.User) -> bool:
    return user.is_owner or settings.mcp_users == "all"


# ---------- the tools, as plain functions ----------

class NotFound(ToolError):
    pass


def _vehicles(db, user: m.User, include_archived: bool = False) -> list[m.Vehicle]:
    q = select(m.Vehicle).where(m.Vehicle.user_id == user.id)
    if not include_archived:
        q = q.where(m.Vehicle.archived.is_(False))
    return list(db.scalars(q.order_by(m.Vehicle.nickname)))


def find_vehicle(db, user: m.User, vehicle: str | int) -> m.Vehicle:
    """A nickname (any case) or an id. Other people's vehicles are 'not found', like in the app."""
    mine = _vehicles(db, user, include_archived=True)
    key = str(vehicle).strip()
    for v in mine:
        if str(v.id) == key or v.nickname.lower() == key.lower():
            return v
    names = ", ".join(v.nickname for v in mine if not v.archived) or "none yet"
    raise NotFound(f"No vehicle called {key!r}. Your vehicles: {names}.")


def _own_service(db, user: m.User, service_id: int) -> m.ServiceRecord:
    rec = db.get(m.ServiceRecord, service_id)
    if not rec or rec.vehicle_id not in user_vehicle_ids(db, user):
        raise NotFound(f"No service with id {service_id}.")
    return rec


def list_vehicles_impl(db, user: m.User) -> list[dict]:
    return [{"id": v.id, "nickname": v.nickname, "year": v.year, "make": v.make, "model": v.model,
             "current_km": odometer.current_km(db, v.id)} for v in _vehicles(db, user)]


def whats_due_impl(db, user: m.User, vehicle: str | None = None) -> list[dict]:
    items = status.all_items(db, today_local(), user_id=user.id)
    if vehicle:
        vid = find_vehicle(db, user, vehicle).id
        items = [i for i in items if i.vehicle_id == vid]
    names = {v.id: v.nickname for v in _vehicles(db, user, include_archived=True)}
    return [{"vehicle": names.get(i.vehicle_id), "item": i.title, "status": i.status, "detail": i.detail,
             "due_date": i.due.isoformat() if i.due else None, "km_remaining": i.km_remaining}
            for i in sorted(items, key=lambda i: ORDER[i.status]) if not i.informational]


def service_history_impl(db, user: m.User, vehicle: str, limit: int = 20) -> list[dict]:
    v = find_vehicle(db, user, vehicle)
    recs = db.scalars(select(m.ServiceRecord).where(m.ServiceRecord.vehicle_id == v.id)
                      .order_by(m.ServiceRecord.date.desc(), m.ServiceRecord.id.desc())
                      .limit(max(1, min(limit, 100))))
    return [{"id": r.id, "date": r.date.isoformat(), "services": records.type_names(db, r),
             "odometer_km": r.odometer_km, "cost": r.cost_cents / 100, "vendor": r.vendor, "notes": r.notes,
             "receipts": len(r.attachments)} for r in recs]


def spending_impl(db, user: m.User, start: date, end: date, vehicle: str | None = None,
                  categories: list[str] | None = None) -> dict:
    if end < start:
        raise ToolError("The end date is before the start date.")
    if (end - start).days > 366 * 10:
        raise ToolError("Ask for at most 10 years at a time.")
    ids = [find_vehicle(db, user, vehicle).id] if vehicle else user_vehicle_ids(db, user)
    out = reports.spending(db, ids, start, end, categories)
    dollars = lambda c: round(c / 100, 2)  # noqa: E731
    return {"total": dollars(out["total_cents"]), "still_scheduled": dollars(out["scheduled_cents"]),
            "by_category": {k: dollars(v) for k, v in out["by_category"].items()},
            "by_month": [{"month": r["month"], "total": dollars(r["total_cents"])} for r in out["by_month"]],
            "entries": [{"date": e["date"].isoformat(), "category": e["category"], "amount": dollars(e["cents"]),
                         "what": e["label"], "scheduled": e["scheduled"]} for e in out["entries"][:200]]}


def list_service_types_impl(db, user: m.User) -> list[str]:
    return list(db.scalars(select(m.ServiceType.name).where(visible_service_types(user))
                           .order_by(m.ServiceType.name)))


def log_odometer_impl(db, user: m.User, vehicle: str, km: int, correction: bool = False,
                      confirm_big_jump: bool = False) -> dict:
    v = find_vehicle(db, user, vehicle)
    if v.archived:
        raise ToolError(f"{v.nickname} is archived.")
    if km < 0 or km > 2_000_000:
        raise ToolError("That isn't a plausible odometer reading.")
    cur = odometer.current_km(db, v.id)
    if correction and (cur is None or km >= cur):
        raise ToolError("correction=true is only for a reading lower than the current one. Nothing was logged.")
    if cur is not None and km < cur and not correction:
        raise ToolError(f"{km:,} km is below {v.nickname}'s current {cur:,} km. Nothing was logged. If the "
                        "earlier reading was wrong, ask the user, then call again with correction=true.")
    if cur is not None and km - cur > BIG_JUMP_KM and not confirm_big_jump:
        raise ToolError(f"That's +{km - cur:,} km since the last reading ({cur:,} km). Nothing was logged. "
                        "Confirm with the user, then call again with confirm_big_jump=true.")
    hidden = sum(1 for r in odometer.valid_readings(db, v.id) if r.km > km) if correction else 0
    try:
        odometer.add_reading(db, v.id, km, "mcp", is_correction=correction)
    except odometer.OdometerError as e:
        raise ToolError(str(e))
    evaluator_hook.after_change(db, user.id)
    out = {"logged_km": km, "vehicle": v.nickname, "previous_km": cur}
    if correction:
        out["readings_marked_wrong"] = hidden  # they stay in the app's history
    return out


def log_service_impl(db, user: m.User, vehicle: str, on: date, services: list[str], cost: float = 0,
                     vendor: str | None = None, odometer_km: int | None = None, notes: str | None = None,
                     confirm_big_jump: bool = False) -> dict:
    v = find_vehicle(db, user, vehicle)
    if on > today_local():
        raise ToolError("The service date can't be in the future.")
    if not 0 <= cost <= 1_000_000:  # written this way so NaN fails too
        raise ToolError("The cost must be between 0 and 1,000,000.")
    if odometer_km is not None and not 0 <= odometer_km <= 2_000_000:
        raise ToolError("That isn't a plausible odometer reading.")
    cur = odometer.current_km(db, v.id)
    if odometer_km is not None and cur is not None and odometer_km - cur > BIG_JUMP_KM and not confirm_big_jump:
        # a service km above the current reading becomes the new odometer reading, so it gets the same check
        raise ToolError(f"odometer_km is +{odometer_km - cur:,} km above the last reading ({cur:,} km). Nothing "
                        "was logged. Confirm with the user, then call again with confirm_big_jump=true.")
    if not services and not notes:
        raise ToolError("Say what was done: pass service names (see list_service_types) or notes.")
    types = {t.name.lower(): t for t in db.scalars(select(m.ServiceType).where(visible_service_types(user)))}
    unknown = [s for s in services if s.strip().lower() not in types]
    if unknown:
        raise ToolError(f"Unknown service name(s): {', '.join(unknown)}. Use names from this list, or put the "
                        f"work in notes: {', '.join(sorted(t.name for t in types.values()))}.")
    ids = list(dict.fromkeys(types[s.strip().lower()].id for s in services))
    rec = records.log_service(db, v.id, on, odometer_km, round(cost * 100), (vendor or "")[:120] or None,
                              (notes or "")[:5000] or None, [(t, None) for t in ids])
    evaluator_hook.after_change(db, user.id)
    return {"service_id": rec.id, "vehicle": v.nickname, "date": on.isoformat(),
            "services": records.type_names(db, rec), "cost": rec.cost_cents / 100}


def save_receipt(db, user: m.User, service_id: int, filename: str, data: bytes) -> dict:
    rec = _own_service(db, user, service_id)
    if len(rec.attachments) >= MAX_ATTACHMENTS:
        raise ToolError(f"A service can have at most {MAX_ATTACHMENTS} receipts.")
    try:
        att = records.save_attachment(db, rec, filename, data)
    except records.UploadError as e:
        raise ToolError(str(e))
    db.commit()
    return {"attachment_id": att.id, "service_id": rec.id, "file": att.orig_name}


def attach_receipt_impl(db, user: m.User, service_id: int, filename: str, content_base64: str) -> dict:
    _own_service(db, user, service_id)  # "not found" before any size or format complaint
    if len(content_base64) > (records.MAX_UPLOAD * 4) // 3 + 8:
        raise ToolError("That file is over 20 MB.")
    try:
        data = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise ToolError("content_base64 isn't valid base64.")
    return save_receipt(db, user, service_id, filename, data)


def receipt_upload_link_impl(db, user: m.User, service_id: int, base_url: str,
                             api_token_id: int | None = None) -> dict:
    rec = _own_service(db, user, service_id)
    now = time.time()
    for t, entry in list(_upload_links.items()):
        if entry[2] < now:
            del _upload_links[t]
    token = UPLOAD_PREFIX + secrets.token_urlsafe(24)
    _upload_links[token] = (user.id, rec.id, now + UPLOAD_LINK_TTL, api_token_id)
    return {"url": f"{base_url.rstrip('/')}/receipt-upload/{token}",
            "expires_in_minutes": UPLOAD_LINK_TTL // 60,
            "how": "Give the user this link; it opens a page where they pick the receipt file. It works once."}


# ---------- MCP wiring ----------

mcp = MCPServer(
    "Vehicle Tracker",
    instructions=(
        "A personal vehicle maintenance tracker (km; amounts in dollars). Start with list_vehicles to learn the "
        "nicknames. To log: before log_service call list_service_types and use those exact names (anything else goes "
        "in notes). If the user shows you a receipt, read it yourself (date, total with taxes, vendor, odometer at "
        "the visit, what was done), confirm with them, then log it; to keep the file call attach_receipt if you have "
        "its bytes, otherwise receipt_upload_link. To set things up: add_vehicle, then add_reminder for each "
        "maintenance item (e.g. oil every 8,000 km or 12 months), add_date for insurance and registration renewals, "
        "add_winter_tire_reminders if they swap tires for winter, add_tire_set, and add_recurring_payment for "
        "automatic payments such as monthly insurance or financing. Ask for the details you need rather than "
        "guessing dates or amounts. Nothing can be edited or deleted through these tools; tell the user to do that "
        "in the app."),
)


@contextmanager
def _session():  # a seam for tests
    with SessionLocal() as db:
        yield db


def _user(ctx: Context, db) -> m.User:
    req = ctx.request_context.request
    uid = req.scope.get("state", {}).get("mcp_user_id") if req is not None else None
    user = db.get(m.User, uid) if uid else None
    if not user:
        raise ToolError("Not signed in.")
    return user


def _base_url(ctx: Context) -> str:
    req = ctx.request_context.request
    return str(req.base_url) if req is not None else ""


@mcp.tool()
def list_vehicles(ctx: Context) -> list[dict]:
    """The user's vehicles with their current odometer (km)."""
    with _session() as db:
        return list_vehicles_impl(db, _user(ctx, db))


@mcp.tool()
def whats_due(ctx: Context, vehicle: str | None = None) -> list[dict]:
    """Reminders and dates with their status (overdue, due_soon, ok, unknown), most urgent first.
    vehicle: a nickname or id; leave empty for all vehicles."""
    with _session() as db:
        return whats_due_impl(db, _user(ctx, db), vehicle)


@mcp.tool()
def service_history(ctx: Context, vehicle: str, limit: int = 20) -> list[dict]:
    """Past services for one vehicle, newest first (id, date, services, km, cost, vendor, notes)."""
    with _session() as db:
        return service_history_impl(db, _user(ctx, db), vehicle, limit)


@mcp.tool()
def spending(ctx: Context, start: date, end: date, vehicle: str | None = None,
             categories: list[str] | None = None) -> dict:
    """What was spent between two dates (inclusive), with totals by category and month and every entry.
    Includes services, tires and recurring payments (insurance, financing...)."""
    with _session() as db:
        return spending_impl(db, _user(ctx, db), start, end, vehicle, categories)


@mcp.tool()
def list_service_types(ctx: Context) -> list[str]:
    """Service names log_service accepts (built-in ones and the user's own)."""
    with _session() as db:
        return list_service_types_impl(db, _user(ctx, db))


@mcp.tool()
def log_odometer(ctx: Context, vehicle: str, km: int, correction: bool = False,
                 confirm_big_jump: bool = False) -> dict:
    """Log the current odometer reading in km. A lower number than the last reading needs correction=true,
    a jump of more than 5,000 km needs confirm_big_jump=true; ask the user before setting either."""
    with _session() as db:
        return log_odometer_impl(db, _user(ctx, db), vehicle, km, correction, confirm_big_jump)


@mcp.tool()
def log_service(ctx: Context, vehicle: str, date: date, services: list[str], cost: float = 0,
                vendor: str | None = None, odometer_km: int | None = None, notes: str | None = None,
                confirm_big_jump: bool = False) -> dict:
    """Log a service visit. services: names from list_service_types. cost: total paid in dollars, taxes
    included. odometer_km: the reading at the visit, if known; more than 5,000 km above the last reading needs
    confirm_big_jump=true (ask the user first). Returns the new service_id."""
    with _session() as db:
        return log_service_impl(db, _user(ctx, db), vehicle, date, services, cost, vendor, odometer_km, notes,
                                confirm_big_jump)


@mcp.tool()
def attach_receipt(ctx: Context, service_id: int, filename: str, content_base64: str) -> dict:
    """Attach a receipt file (JPEG, PNG, WebP, HEIC or PDF, at most 20 MB, base64-encoded) to a service."""
    with _session() as db:
        return attach_receipt_impl(db, _user(ctx, db), service_id, filename, content_base64)


@mcp.tool()
def receipt_upload_link(ctx: Context, service_id: int) -> dict:
    """A one-time link (valid 15 minutes) where the user can upload a receipt file for a service. Use this
    when you can't pass the file's bytes to attach_receipt."""
    with _session() as db:
        req = ctx.request_context.request
        token_id = req.scope.get("state", {}).get("mcp_token_id") if req is not None else None
        return receipt_upload_link_impl(db, _user(ctx, db), service_id, _base_url(ctx), token_id)


# ---------- HTTP: bearer check in front of the MCP transport ----------

class _Running:
    manager = None


def _new_manager():
    # Host and Origin are already checked by the main app (TrustedHostMiddleware and the CSRF guard).
    mcp.streamable_http_app(stateless_http=True, json_response=True,
                            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    return mcp.session_manager


@asynccontextmanager
async def running():
    """Run from the app's lifespan. A fresh session manager each time, since one can only start once."""
    if not settings.mcp_enabled:
        yield
        return
    manager = _new_manager()
    async with manager.run():
        _Running.manager = manager
        try:
            yield
        finally:
            _Running.manager = None


def _bearer(scope) -> str | None:
    for k, v in scope.get("headers", []):
        if k == b"authorization":
            kind, _, token = v.decode("latin-1").partition(" ")
            return token.strip() if kind.lower() == "bearer" and token.strip() else None
    return None


async def _handle(scope, receive, send) -> None:
    if not settings.mcp_enabled:
        await JSONResponse({"detail": "Not Found"}, status_code=404)(scope, receive, send)
        return
    client = "mcp:" + (scope.get("client") or ("?",))[0]
    try:
        auth._check_lock(client)
    except Exception as e:  # HTTPException 429
        await JSONResponse({"detail": getattr(e, "detail", "Too many attempts")}, status_code=429)(
            scope, receive, send)
        return
    token = _bearer(scope)
    with _session() as db:
        user = user_for_token(db, token) if token else None
        uid = user.id if user else None
        token_id = db.scalar(select(m.ApiToken.id).where(m.ApiToken.token_hash == hash_token(token))) if uid else None
    if uid is None:
        if token:
            auth._fail(client)
        await JSONResponse({"detail": "A valid access token is required (Settings → AI assistants)."},
                           status_code=401, headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)
        return
    if _Running.manager is None:
        await JSONResponse({"detail": "The MCP server is starting"}, status_code=503)(scope, receive, send)
        return
    auth._failures.pop(client, None)  # like a successful login: a good token clears earlier mistakes
    scope.setdefault("state", {}).update(mcp_user_id=uid, mcp_token_id=token_id)
    await _Running.manager.handle_request(scope, receive, send)


class _Endpoint:
    """A raw ASGI app for /mcp (an instance, so Starlette doesn't treat it as a request/response function)."""

    async def __call__(self, scope, receive, send) -> None:
        await _handle(scope, receive, send)


mcp_endpoint = _Endpoint()


# ---------- one-time receipt upload page ----------

upload_router = APIRouter(include_in_schema=False)

_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Upload receipt</title>
<style>body{{font-family:system-ui,sans-serif;max-width:28rem;margin:3rem auto;padding:0 1rem;line-height:1.5}}
button{{font-size:1rem;padding:.6rem 1.2rem;margin-top:1rem}}</style></head><body>{body}</body></html>"""


def _page(body: str, code: int = 200) -> HTMLResponse:
    return HTMLResponse(_PAGE.format(body=body), status_code=code)


def _link(token: str):
    entry = _upload_links.get(token)
    if not entry or entry[2] < time.time():
        _upload_links.pop(token, None)
        return None
    return entry


@upload_router.get("/receipt-upload/{token}")
def upload_page(token: str):
    if not settings.mcp_enabled or not _link(token):
        return _page("<h1>Link expired</h1><p>This upload link was used already or has expired. "
                     "Ask the assistant for a new one.</p>", 404)
    with _session() as db:
        rec = db.get(m.ServiceRecord, _link(token)[1])
        v = db.get(m.Vehicle, rec.vehicle_id) if rec else None
        what = f"{v.nickname}, {rec.date:%b} {rec.date.day}, {rec.date.year}" if v else "this service"
    return _page(f"<h1>Upload receipt</h1><p>For {_escape(what)}.</p>"
                 '<form method="post" enctype="multipart/form-data">'
                 '<input type="file" name="file" accept="image/*,application/pdf" required>'
                 "<br><button>Upload</button></form>")


@upload_router.post("/receipt-upload/{token}")
async def upload_receipt(token: str, request: Request):
    entry = _link(token) if settings.mcp_enabled else None
    if not entry:
        return _page("<h1>Link expired</h1><p>Ask the assistant for a new one.</p>", 404)
    _upload_links.pop(token, None)  # claimed now, before any await, so two uploads can't both use it

    def retry(page: HTMLResponse) -> HTMLResponse:
        _upload_links[token] = entry  # a wrong file shouldn't cost the link
        return page

    form = await request.form()
    f = form.get("file")
    if f is None or not hasattr(f, "read"):
        return retry(_page("<h1>No file</h1><p>Go back and pick a file.</p>", 422))
    data = await f.read(records.MAX_UPLOAD + 1)
    with _session() as db:
        user = db.get(m.User, entry[0])
        if not user or not _token_still_valid(db, user, entry[3]):
            return _page("<h1>Link expired</h1><p>The access behind this link was revoked.</p>", 404)
        try:
            save_receipt(db, user, entry[1], f.filename or "receipt", data)
        except ToolError as e:
            return retry(_page(f"<h1>Couldn't upload</h1><p>{_escape(str(e))}</p><p>Go back to try another "
                               "file.</p>", 422))
    return _page("<h1>Uploaded ✓</h1><p>The receipt is attached. You can close this page.</p>")


def _token_still_valid(db, user: m.User, api_token_id: int | None) -> bool:
    if not may_use_mcp(user):
        return False
    if api_token_id is None:
        return True
    row = db.get(m.ApiToken, api_token_id)
    return bool(row and row.revoked_at is None)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def token_count(db, user: m.User) -> int:
    return db.scalar(select(func.count()).select_from(m.ApiToken).where(
        m.ApiToken.user_id == user.id, m.ApiToken.revoked_at.is_(None))) or 0


from app import mcp_setup  # noqa: E402,F401  (registers the setup tools on `mcp`)
