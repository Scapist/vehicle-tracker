"""Accounts: first-run setup with a one-time code, invite-only sign-up, login, sessions, chat app linking."""
import base64
import hashlib
import hmac
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models as m
from app.config import settings
from app.db import get_db

log = logging.getLogger("auth")
router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE = "vt_session"
MAX_AGE = 30 * 24 * 3600
MIN_PASSWORD = 10
INVITE_DAYS = 7
LINK_CODE_TTL = 10 * 60
FREE_ATTEMPTS = 5  # per device+email pair
FREE_ATTEMPTS_PER_DEVICE = 20  # across all emails from one device (password spraying)
MAX_LOCK = 15 * 60
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I

# in-process state (single container): failed logins, the first-run setup code, chat link codes
_failures: dict[str, tuple[int, float]] = {}
_setup_code: str | None = None
_link_codes: dict[str, tuple[int, float]] = {}  # code -> (user id, expires)


# ---------- passwords ----------

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, maxmem=64 * 1024 * 1024, **_SCRYPT)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                             dklen=32, maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(got, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = hash_password(secrets.token_hex(8))  # so unknown emails take as long as wrong passwords


# ---------- sessions ----------

_keys: dict[str, bytes] = {}  # cached per source, so the hot path never touches the disk


def _key() -> bytes:
    if settings.secret_key:
        return settings.secret_key.encode()
    path = settings.data_dir / "secret_key"
    cached = _keys.get(str(path))
    if cached:
        return cached
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32))
        try:
            path.chmod(0o600)
        except OSError:
            pass
    _keys[str(path)] = key = path.read_text().strip().encode()
    return key


def _sign(uid: int, version: int, exp: int) -> str:
    return hmac.new(_key(), f"{uid}:{version}:{exp}".encode(), hashlib.sha256).hexdigest()


def make_token(user: m.User) -> str:
    exp = int(time.time()) + MAX_AGE
    return f"{user.id}.{user.session_version}.{exp}.{_sign(user.id, user.session_version, exp)}"


def parse_token(token: str | None) -> tuple[int, int] | None:
    """(user id, session version) if the signature and expiry check out. No database access."""
    try:
        uid, ver, exp, sig = (token or "").split(".")
        uid_i, ver_i, exp_i = int(uid), int(ver), int(exp)
    except ValueError:
        return None
    if exp_i < time.time() or not hmac.compare_digest(sig.encode(), _sign(uid_i, ver_i, exp_i).encode()):
        return None
    return uid_i, ver_i


def cookie_looks_valid(request: Request) -> bool:
    return parse_token(request.cookies.get(COOKIE)) is not None


def _set_session(response: Response, request: Request, user: m.User) -> None:
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(COOKIE, make_token(user), max_age=MAX_AGE, httponly=True, samesite="lax",
                        secure=https, path="/")


def session_user(db: Session, request: Request) -> m.User | None:
    """The account this request's session cookie belongs to, if the session is still valid."""
    parsed = parse_token(request.cookies.get(COOKIE))
    user = db.get(m.User, parsed[0]) if parsed else None
    if not user or user.session_version != parsed[1]:
        return None
    return user


def current_user(request: Request, db: Session = Depends(get_db)) -> m.User:
    user = session_user(db, request)
    if not user:
        raise HTTPException(401, "Sign in first")
    return user


def owner_user(user: m.User = Depends(current_user)) -> m.User:
    if not user.is_owner:
        raise HTTPException(403, "Only the owner can do that")
    return user


# ---------- first-run setup ----------

def has_users(db: Session) -> bool:
    return db.scalar(select(func.count()).select_from(m.User)) > 0


def ensure_setup_code() -> str:
    global _setup_code
    if _setup_code is None:
        _setup_code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
    return _setup_code


def announce_setup(db: Session) -> None:
    """Called at startup: with no accounts yet, print the code needed to create the owner account."""
    if not has_users(db):
        code = ensure_setup_code()
        banner = "=" * 60
        log.warning("\n%s\n  No accounts yet. Open the app and create the owner account\n"
                    "  with this one-time setup code:   %s\n%s", banner, code, banner)


def link_legacy_chat(db: Session, user: m.User) -> None:
    """Carry over a single chat id from TELEGRAM_ALLOWED_CHAT_IDS (pre-accounts setup) to the owner."""
    from app.notify.factory import allowed_chat_ids

    ids = allowed_chat_ids()
    if user.telegram_chat_id is None and len(ids) == 1 and not db.scalar(
            select(m.User.id).where(m.User.telegram_chat_id == ids[0])):
        user.telegram_chat_id = ids[0]


# ---------- rate limiting ----------

def _check_lock(*keys: str) -> None:
    now = time.time()
    for k in keys:
        until = _failures.get(k, (0, 0.0))[1]
        if until > now:
            raise HTTPException(429, f"Too many attempts. Try again in {int(until - now) + 1} seconds.")


def _fail(*keys: str) -> None:
    for k in keys:
        free = FREE_ATTEMPTS_PER_DEVICE if k.startswith(("ip:", "mcp:")) else FREE_ATTEMPTS
        count = _failures.get(k, (0, 0.0))[0] + 1
        until = time.time() + min(MAX_LOCK, 30 * 2 ** (count - free)) if count >= free else 0.0
        _failures[k] = (count, until)


def _client(request: Request) -> str:
    return "ip:" + (request.client.host if request.client else "?")


# ---------- schemas ----------

class PasswordMixin(BaseModel):
    password: str = Field(min_length=MIN_PASSWORD, max_length=256)


class NewAccount(PasswordMixin):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        local, _, domain = v.partition("@")
        if not local or "." not in domain or " " in v:
            raise ValueError("Enter a valid email address")
        return v

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Enter your name")
        return v.strip()


class SetupIn(NewAccount):
    setup_code: str = Field(max_length=20)


class SignupIn(NewAccount):
    invite: str = Field(max_length=100)


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(min_length=MIN_PASSWORD, max_length=256)


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    is_owner: bool
    telegram_linked: bool
    discord_linked: bool = False
    alert_channel: str | None = None


class Me(BaseModel):
    user: UserOut | None
    setup_required: bool
    channels_available: list[str] = []  # chat apps set up on this server
    mcp_enabled: bool = False


def _user_out(u: m.User) -> UserOut:
    return UserOut(id=u.id, name=u.name, email=u.email, is_owner=u.is_owner,
                   telegram_linked=u.telegram_chat_id is not None, discord_linked=u.discord_user_id is not None,
                   alert_channel=u.alert_channel)


def _me(user: m.User | None, setup_required: bool) -> "Me":
    from app.notify.factory import available_channels

    return Me(user=_user_out(user) if user else None, setup_required=setup_required,
              channels_available=available_channels(), mcp_enabled=settings.mcp_enabled)


# ---------- endpoints ----------

@router.get("/me", response_model=Me)
def me(request: Request, db: Session = Depends(get_db)):
    user = session_user(db, request)
    return _me(user, not has_users(db))


@router.post("/setup", response_model=Me, status_code=201)
def setup(body: SetupIn, request: Request, response: Response, db: Session = Depends(get_db)):
    """Create the owner account. Only works while there are no accounts, and needs the code from the log."""
    if has_users(db):
        raise HTTPException(409, "The owner account already exists. Sign in instead.")
    client = "guess:" + _client(request)  # setup codes / invite links: the strict limit
    _check_lock(client)
    if not hmac.compare_digest(body.setup_code.strip().upper().encode(), ensure_setup_code().encode()):
        _fail(client)
        raise HTTPException(403, "That setup code is wrong. It's printed in the server log.")
    user = m.User(email=body.email, name=body.name, password_hash=hash_password(body.password), is_owner=True)
    db.add(user)
    db.flush()
    # everything created before accounts existed belongs to the owner
    db.execute(update(m.Vehicle).where(m.Vehicle.user_id.is_(None)).values(user_id=user.id))
    db.execute(update(m.DateItem).where(m.DateItem.user_id.is_(None)).values(user_id=user.id))
    link_legacy_chat(db, user)
    db.commit()
    global _setup_code
    _setup_code = None
    _failures.pop(client, None)
    log.info("owner account created for %s", user.email)
    _set_session(response, request, user)
    return _me(user, False)


@router.post("/signup", response_model=Me, status_code=201)
def signup(body: SignupIn, request: Request, response: Response, db: Session = Depends(get_db)):
    client = "guess:" + _client(request)  # setup codes / invite links: the strict limit
    _check_lock(client)
    now = datetime.now(timezone.utc)
    token_hash = hashlib.sha256(body.invite.encode()).hexdigest()
    # claim it atomically: of two simultaneous sign-ups with one link, only one gets rowcount 1
    claimed = db.execute(update(m.Invite)
                         .where(m.Invite.token_hash == token_hash, m.Invite.used_at.is_(None),
                                m.Invite.expires_at > now)
                         .values(used_at=now)).rowcount
    if claimed != 1:
        db.rollback()
        _fail(client)
        raise HTTPException(403, "This invite link is invalid, used or expired. Ask for a new one.")
    user = m.User(email=body.email, name=body.name, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()  # also releases the invite
        raise HTTPException(409, "An account with that email already exists")
    db.execute(update(m.Invite).where(m.Invite.token_hash == token_hash).values(used_by=user.id))
    db.commit()
    _set_session(response, request, user)
    return _me(user, False)


@router.post("/login", response_model=Me)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    # Locks are per device+email (so nobody can lock *you* out from elsewhere by typing your email)
    # plus a looser per-device limit. Behind a reverse proxy, set FORWARDED_ALLOW_IPS so the device
    # is the real client, not the proxy.
    device = _client(request)
    keys = (device, f"pair:{device}|{email}")
    _check_lock(*keys)
    user = db.scalar(select(m.User).where(m.User.email == email))
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok:
        _fail(*keys)
        log.warning("failed login for %r from %s", email, device)
        raise HTTPException(401, "Wrong email or password")
    _failures.pop(keys[1], None)
    _set_session(response, request, user)
    return _me(user, False)


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")


@router.post("/logout-everywhere", status_code=204)
def logout_everywhere(response: Response, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    user.session_version += 1
    db.commit()
    response.delete_cookie(COOKIE, path="/")


@router.post("/password", status_code=204)
def change_password(body: ChangePasswordIn, request: Request, response: Response,
                    user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(403, "Your current password is wrong")
    user.password_hash = hash_password(body.new_password)
    user.session_version += 1  # every other device is signed out
    db.commit()
    _set_session(response, request, user)  # this one stays signed in


# ---------- invites (owner) ----------

class InviteOut(BaseModel):
    id: int
    created_at: datetime
    expires_at: datetime
    used: bool
    used_by_name: str | None = None
    link: str | None = None  # only returned once, when created


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.post("/invites", response_model=InviteOut, status_code=201)
def create_invite(user: m.User = Depends(owner_user), db: Session = Depends(get_db)):
    token = secrets.token_urlsafe(24)
    inv = m.Invite(token_hash=hashlib.sha256(token.encode()).hexdigest(), created_by=user.id,
                   expires_at=datetime.now(timezone.utc) + timedelta(days=INVITE_DAYS))
    db.add(inv)
    db.commit()
    return InviteOut(id=inv.id, created_at=inv.created_at, expires_at=inv.expires_at, used=False,
                     link=f"/signup?invite={token}")


@router.get("/invites", response_model=list[InviteOut])
def list_invites(user: m.User = Depends(owner_user), db: Session = Depends(get_db)):
    names = dict(db.execute(select(m.User.id, m.User.name)).all())
    now = datetime.now(timezone.utc)
    out = []
    for inv in db.scalars(select(m.Invite).order_by(m.Invite.created_at.desc())):
        if inv.used_at is None and _aware(inv.expires_at) < now:
            continue  # expired and unused: not interesting
        out.append(InviteOut(id=inv.id, created_at=inv.created_at, expires_at=inv.expires_at,
                             used=inv.used_at is not None, used_by_name=names.get(inv.used_by)))
    return out


@router.delete("/invites/{invite_id}", status_code=204)
def revoke_invite(invite_id: int, user: m.User = Depends(owner_user), db: Session = Depends(get_db)):
    inv = db.get(m.Invite, invite_id)
    if not inv or inv.used_at is not None:
        raise HTTPException(404)
    db.delete(inv)
    db.commit()


@router.get("/users", response_model=list[UserOut])
def list_users(user: m.User = Depends(owner_user), db: Session = Depends(get_db)):
    return [_user_out(u) for u in db.scalars(select(m.User).order_by(m.User.created_at))]


# ---------- chat app linking (Telegram, Discord) ----------

CHANNELS = {"telegram": "telegram_chat_id", "discord": "discord_user_id"}


class LinkCode(BaseModel):
    code: str
    expires_in_seconds: int


def _new_link_code(user: m.User) -> LinkCode:
    now = time.time()
    for c, (_, exp) in list(_link_codes.items()):
        if exp < now:
            del _link_codes[c]
    code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
    _link_codes[code] = (user.id, now + LINK_CODE_TTL)
    return LinkCode(code=code, expires_in_seconds=LINK_CODE_TTL)


@router.post("/link-code", response_model=LinkCode)
def link_code(user: m.User = Depends(current_user)):
    """One code for any chat app: whichever bot receives it links that app."""
    return _new_link_code(user)


@router.post("/telegram/link-code", response_model=LinkCode)
def telegram_link_code(user: m.User = Depends(current_user)):
    return _new_link_code(user)


def _unlink(db: Session, user: m.User, channel: str) -> None:
    setattr(user, CHANNELS[channel], None)
    if user.alert_channel == channel:
        user.alert_channel = None
    db.commit()


@router.delete("/telegram", status_code=204)
def telegram_unlink(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    _unlink(db, user, "telegram")


@router.delete("/discord", status_code=204)
def discord_unlink(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    _unlink(db, user, "discord")


class AlertChannelIn(BaseModel):
    channel: str | None = None


@router.put("/alert-channel", response_model=UserOut)
def set_alert_channel(body: AlertChannelIn, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    if body.channel is not None:
        if body.channel not in CHANNELS:
            raise HTTPException(422, "Unknown chat app")
        if getattr(user, CHANNELS[body.channel]) is None:
            raise HTTPException(409, "Connect that app first")
    user.alert_channel = body.channel
    db.commit()
    return _user_out(user)


def consume_link_code(db: Session, code: str, address: int, channel: str = "telegram") -> m.User | None:
    """Used by the bots' link command. Returns the user the chat is now linked to."""
    column = CHANNELS[channel]
    entry = _link_codes.pop(code.strip().upper(), None)
    if not entry or entry[1] < time.time():
        return None
    user = db.get(m.User, entry[0])
    if not user:
        return None
    other = db.scalar(select(m.User).where(getattr(m.User, column) == address))
    if other and other.id != user.id:
        setattr(other, column, None)  # a chat belongs to one account
        if other.alert_channel == channel:
            other.alert_channel = None
        db.flush()  # release the unique id before giving it to the new account
    setattr(user, column, address)
    db.commit()
    return user
