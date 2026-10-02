"""Datamodeller for Vinjæger."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WineIdentity(BaseModel):
    """Hvad Claude kunne læse ud fra en etiket."""

    producer: str | None = Field(None, description="Producent/vinhus, fx 'Château Musar'")
    wine_name: str | None = Field(None, description="Vinens navn/cuvée, fx 'Rouge'")
    vintage: int | None = Field(None, description="Årgang, hvis den kan ses")
    country: str | None = None
    region: str | None = Field(None, description="Område/appellation")
    grapes: str | None = Field(None, description="Druesort(er), hvis det fremgår")
    color: str | None = Field(None, description="rød, hvid, rosé, mousserende, dessert ...")
    bottle_ml: int | None = Field(None, description="Flaskestørrelse i ml, hvis det fremgår")
    search_query: str = Field(description="Kort, præcis søgetekst til at finde netop denne vin i webshops")
    confidence: float = Field(description="0-1: hvor sikker identifikationen er")


class Offer(BaseModel):
    shop: str
    url: str
    price_dkk: float
    bottle_ml: int = 750
    vintage: int | None = None
    in_stock: bool | None = None
    note: str | None = None
    price_per_75cl: float = 0.0


class SearchResult(BaseModel):
    query: str
    offers: list[Offer]
    cheapest: Offer | None
    summary: str | None = None
    cached: bool = False
