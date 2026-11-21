"""Personal access tokens for the MCP server (Settings → AI assistants). The token is shown once."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.auth import current_user
from app.config import settings
from app.db import get_db
from app.mcp_server import hash_token, may_use_mcp, new_token

router = APIRouter(prefix="/mcp-tokens", tags=["mcp"])
MAX_TOKENS = 20


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class TokenOut(BaseModel):
    id: int
    name: str
    created_at: datetime
    last_used_at: datetime | None
    token: str | None = None  # only in the response that creates it


def _allowed(user: m.User) -> None:
    if not settings.mcp_enabled:
        raise HTTPException(404, "The MCP server is turned off on this server (MCP_ENABLED)")
    if not may_use_mcp(user):
        raise HTTPException(403, "Only the owner can use AI assistants on this server")


def _out(t: m.ApiToken, token: str | None = None) -> TokenOut:
    return TokenOut(id=t.id, name=t.name, created_at=t.created_at, last_used_at=t.last_used_at, token=token)


@router.get("", response_model=list[TokenOut])
def list_tokens(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    _allowed(user)
    rows = db.scalars(select(m.ApiToken).where(m.ApiToken.user_id == user.id, m.ApiToken.revoked_at.is_(None))
                      .order_by(m.ApiToken.created_at))
    return [_out(t) for t in rows]


@router.post("", response_model=TokenOut, status_code=201)
def create_token(body: TokenIn, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    _allowed(user)
    active = db.scalars(select(m.ApiToken.id).where(m.ApiToken.user_id == user.id,
                                                    m.ApiToken.revoked_at.is_(None))).all()
    if len(active) >= MAX_TOKENS:
        raise HTTPException(409, f"At most {MAX_TOKENS} tokens; revoke one first")
    token = new_token()
    row = m.ApiToken(user_id=user.id, name=body.name.strip() or "Assistant", token_hash=hash_token(token))
    db.add(row)
    db.commit()
    return _out(row, token)


@router.delete("/{token_id}", status_code=204)
def revoke_token(token_id: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.get(m.ApiToken, token_id)
    if not row or row.user_id != user.id or row.revoked_at is not None:
        raise HTTPException(404, "Token not found")
    row.revoked_at = datetime.now(timezone.utc)
    db.commit()
