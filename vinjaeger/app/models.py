"""Datamodeller for Vinjæger."""

from __future__ import annotations

from typing import Annotated

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


# ---------- Tilbudsjæger ----------

Words = list[Annotated[str, Field(min_length=1, max_length=60)]]


class DealRule(BaseModel):
    """Én regel - en vin passer, hvis den matcher alle udfyldte felter i reglen."""

    colors: Words = Field(default_factory=list, max_length=6, description="rød, hvid, rosé, mousserende, dessert/hedvin")
    regions: Words = Field(default_factory=list, max_length=15, description="Område/appellation, fx Bourgogne, Barolo")
    grapes: Words = Field(default_factory=list, max_length=15)
    producers: Words = Field(default_factory=list, max_length=15, description="Producent/vinhus")
    max_price: float | None = Field(None, gt=0, description="Max pris pr. flaske for denne regel")

    def is_empty(self) -> bool:
        return not (self.colors or self.regions or self.grapes or self.producers)


class DealCriteria(BaseModel):
    rules: list[DealRule] = Field(min_length=1, max_length=10)
    max_price: float | None = Field(None, gt=0, description="Generel max pris pr. flaske")
    min_discount: int | None = Field(None, ge=0, le=90, description="Mindste rabat i procent")
    notes: str | None = Field(None, max_length=500, description="Fritekst, fx 'gerne modne årgange'")


class Deal(BaseModel):
    wine: str
    producer: str | None = None
    region: str | None = None
    grapes: str | None = None
    color: str | None = None
    vintage: int | None = None
    shop: str
    url: str
    price_dkk: float
    normal_price_dkk: float | None = None
    discount_pct: int | None = None
    bottle_ml: int = 750
    matched_rule: int | None = None
    why: str | None = None
    deal_score: int = 5


class DealResult(BaseModel):
    deals: list[Deal]
    summary: str | None = None
    cached: bool = False


class DealJob(BaseModel):
    id: str
    status: str  # "running" | "done" | "error"
    result: DealResult | None = None
    error: str | None = None
