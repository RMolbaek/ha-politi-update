"""Vinjæger - find den billigste pris på den vin, du kigger på."""

from __future__ import annotations

import hmac
import logging
import os
from pathlib import Path

import anthropic
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import claude
from .models import SearchResult, WineIdentity
from .pricing import TTLCache, normalize_offers, pick_cheapest

_LOGGER = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

ACCESS_TOKEN = os.environ.get("VINJAEGER_TOKEN", "")
cache = TTLCache(ttl_seconds=float(os.environ.get("VINJAEGER_CACHE_HOURS", "6")) * 3600)

app = FastAPI(title="Vinjæger")


def require_token(x_vinjaeger_token: str = Header(default="")) -> None:
    """Hvis VINJAEGER_TOKEN er sat, kræves den - så fremmede ikke bruger dine API-kreditter."""
    if ACCESS_TOKEN and not hmac.compare_digest(x_vinjaeger_token, ACCESS_TOKEN):
        raise HTTPException(401, "Forkert eller manglende adgangskode")


def _api_error(err: Exception) -> HTTPException:
    if isinstance(err, claude.ClaudeError):
        return HTTPException(502, str(err))
    if isinstance(err, anthropic.AuthenticationError):
        return HTTPException(500, "Serveren mangler en gyldig ANTHROPIC_API_KEY")
    if isinstance(err, anthropic.RateLimitError):
        return HTTPException(429, "For mange søgninger lige nu - prøv igen om lidt")
    _LOGGER.exception("Fejl fra Claude API")
    return HTTPException(502, "Der skete en fejl ved opslaget - prøv igen")


@app.get("/api/health")
async def health() -> dict[str, object]:
    return {"ok": True, "model": claude.MODEL, "token_required": bool(ACCESS_TOKEN)}


@app.post("/api/identify", dependencies=[Depends(require_token)])
async def identify(image: UploadFile = File(...)) -> WineIdentity:
    media_type = (image.content_type or "").lower()
    if media_type not in IMAGE_TYPES:
        raise HTTPException(415, "Billedet skal være JPEG, PNG, WebP eller GIF")
    data = await image.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Billedet er for stort (max 5 MB)")
    try:
        return await claude.identify_label(data, media_type)
    except (claude.ClaudeError, anthropic.APIError) as err:
        raise _api_error(err) from err


@app.get("/api/search", dependencies=[Depends(require_token)])
async def search(
    q: str = Query(..., min_length=2, max_length=200),
    vintage: int | None = Query(None, ge=1900, le=2100),
    ean: str | None = Query(None, pattern=r"^\d{8,14}$"),
    refresh: bool = False,
) -> SearchResult:
    key = cache.key(q, vintage, ean)
    if not refresh and (hit := cache.get(key)):
        return hit.model_copy(update={"cached": True})
    try:
        raw = await claude.find_offers(q, vintage, ean)
    except (claude.ClaudeError, anthropic.APIError) as err:
        raise _api_error(err) from err

    offers = normalize_offers(raw.get("offers", []), vintage)
    result = SearchResult(
        query=q,
        offers=offers,
        cheapest=pick_cheapest(offers, vintage),
        summary=raw.get("summary"),
    )
    cache.set(key, result)
    return result


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/", StaticFiles(directory=STATIC), name="static")
