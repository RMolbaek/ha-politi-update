"""Tilbudsjæger: en agent der finder aktuelle vintilbud ud fra dine kriterier."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from typing import Any

from . import claude
from .models import Deal, DealCriteria, DealJob, DealResult

_LOGGER = logging.getLogger(__name__)

DEALS_SYSTEM = """\
Du er en erfaren vinkøber, der jagter gode tilbud i Danmark på vegne af en kunde.
Kunden har opstillet nogle regler. En vin er relevant, hvis den passer til mindst
én regel (alle udfyldte felter i reglen skal passe).

Fremgangsmåde:
1. Søg bredt: danske vinhandleres tilbuds-/kampagnesider, supermarkedernes
   vintilbud, outlet/restsalg, nyhedsbreve og tilbudsaviser, og
   prissammenligningssider. Søg på både områder, druer og producenter fra reglerne.
2. Åbn siderne og aflæs aktuel pris og - hvis den fremgår - normalpris/førpris.
   Medtag kun tilbud, hvor prisen står på en side, du har set i denne søgning,
   og kun tilbud der ser ud til at gælde nu.
3. Vurder hvert fund: Er det reelt et godt køb? Tag højde for rabat, prisniveau
   i forhold til hvad vinen normalt koster i Danmark, producentens ry og årgang.
   Giv deal_score 1-10 (10 = fremragende køb) og forklar kort på dansk i why.
4. Find gerne 5-15 gode fund, spredt over reglerne. Hellere få gode end mange
   middelmådige.
5. Afslut ALTID ved at kalde report_deals - også hvis listen er tom.

Priser er pr. flaske i DKK inkl. moms. Kassepriser omregnes til pris pr. flaske
(skriv betingelsen i why)."""

REPORT_DEALS_TOOL: dict[str, Any] = {
    "name": "report_deals",
    "description": "Rapportér de fundne tilbud. Kaldes præcis én gang til sidst.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["deals", "summary"],
        "properties": {
            "summary": {"type": "string", "description": "2-3 sætninger på dansk om de bedste fund"},
            "deals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "wine", "producer", "region", "grapes", "color", "vintage",
                        "shop", "url", "price_dkk", "normal_price_dkk", "bottle_ml",
                        "matched_rule", "why", "deal_score",
                    ],
                    "properties": {
                        "wine": {"type": "string", "description": "Vinens fulde navn"},
                        "producer": {"type": ["string", "null"]},
                        "region": {"type": ["string", "null"]},
                        "grapes": {"type": ["string", "null"]},
                        "color": {"type": ["string", "null"]},
                        "vintage": {"type": ["integer", "null"]},
                        "shop": {"type": "string"},
                        "url": {"type": "string", "description": "Direkte link til produktsiden"},
                        "price_dkk": {"type": "number", "description": "Tilbudspris pr. flaske"},
                        "normal_price_dkk": {
                            "type": ["number", "null"],
                            "description": "Normalpris/førpris pr. flaske, hvis den fremgår",
                        },
                        "bottle_ml": {"type": "integer"},
                        "matched_rule": {
                            "type": ["integer", "null"],
                            "description": "Nummer på reglen vinen passer til (1, 2, ...)",
                        },
                        "why": {"type": "string"},
                        "deal_score": {"type": "integer", "description": "1-10"},
                    },
                },
            },
        },
    },
}


def _fmt_rule(i: int, rule: Any) -> str:
    parts = []
    if rule.colors:
        parts.append("type: " + " eller ".join(rule.colors))
    if rule.regions:
        parts.append("område: " + " eller ".join(rule.regions))
    if rule.grapes:
        parts.append("drue: " + " eller ".join(rule.grapes))
    if rule.producers:
        parts.append("producent: " + " eller ".join(rule.producers))
    if rule.max_price:
        parts.append(f"max {rule.max_price:.0f} kr.")
    return f"Regel {i}: " + "; ".join(parts)


def build_request(criteria: DealCriteria) -> str:
    rules = [r for r in criteria.rules if not r.is_empty()]
    lines = ["Find de bedste aktuelle vintilbud i Danmark, der passer til:"]
    lines += [_fmt_rule(i, r) for i, r in enumerate(rules, 1)]
    if criteria.max_price:
        lines.append(f"Generel max pris: {criteria.max_price:.0f} kr. pr. flaske.")
    if criteria.min_discount:
        lines.append(f"Kun tilbud med mindst {criteria.min_discount} % rabat i forhold til normalpris.")
    if criteria.notes:
        lines.append(f"Kundens ønsker: {criteria.notes}")
    return "\n".join(lines)


def normalize_deals(raw: list[dict[str, Any]], criteria: DealCriteria) -> list[Deal]:
    """Valider, beregn rabat, håndhæv prisgrænser og sorter efter hvor godt et køb det er."""
    rules = [r for r in criteria.rules if not r.is_empty()]
    seen: set[str] = set()
    deals: list[Deal] = []
    for item in raw:
        try:
            price = float(item.get("price_dkk") or 0)
            normal = float(item["normal_price_dkk"]) if item.get("normal_price_dkk") else None
        except (TypeError, ValueError):
            continue
        url = (item.get("url") or "").strip()
        if price <= 0 or not url.startswith(("http://", "https://")) or not item.get("wine"):
            continue
        key = url.lower().removeprefix("https://").removeprefix("http://").removeprefix("www.").rstrip("/")
        if key in seen:
            continue
        seen.add(key)

        bottle_ml = int(item.get("bottle_ml") or 750) or 750
        per_75 = price * 750 / bottle_ml
        rule_no = item.get("matched_rule")
        rule = rules[rule_no - 1] if isinstance(rule_no, int) and 1 <= rule_no <= len(rules) else None
        limit = min(
            (p for p in (criteria.max_price, rule.max_price if rule else None) if p),
            default=None,
        )
        if limit and per_75 > limit * 1.001:
            continue

        discount = None
        if normal and normal > price:
            discount = round((normal - price) / normal * 100)
        if criteria.min_discount and (discount or 0) < criteria.min_discount:
            continue

        score = item.get("deal_score")
        deals.append(
            Deal(
                wine=item["wine"].strip(),
                producer=item.get("producer"),
                region=item.get("region"),
                grapes=item.get("grapes"),
                color=item.get("color"),
                vintage=item.get("vintage"),
                shop=(item.get("shop") or "").strip() or key.split("/")[0],
                url=url,
                price_dkk=round(price, 2),
                normal_price_dkk=round(normal, 2) if normal and normal > price else None,
                discount_pct=discount,
                bottle_ml=bottle_ml,
                matched_rule=rule_no if rule else None,
                why=item.get("why"),
                deal_score=max(1, min(10, int(score))) if isinstance(score, (int, float)) else 5,
            )
        )
    deals.sort(key=lambda d: (-d.deal_score, -(d.discount_pct or 0), d.price_dkk))
    return deals


async def find_deals(criteria: DealCriteria) -> DealResult:
    raw = await claude._run_agent(
        DEALS_SYSTEM,
        build_request(criteria),
        [*claude._web_tools(searches=15, fetches=25), REPORT_DEALS_TOOL],
        "report_deals",
        effort="high",
    )
    return DealResult(deals=normalize_deals(raw.get("deals", []), criteria), summary=raw.get("summary"))


def criteria_key(criteria: DealCriteria) -> str:
    return hashlib.sha256(criteria.model_dump_json().lower().encode()).hexdigest()


class JobRunner:
    """Kører tilbudsjagter i baggrunden, så telefonen kan polle i stedet for at
    holde en forbindelse åben i flere minutter (reverse proxies lukker ofte efter ~100 s)."""

    def __init__(self, max_running: int = 2, cache_seconds: float = 3600, keep_seconds: float = 3600):
        self.max_running = max_running
        self.cache_seconds = cache_seconds
        self.keep_seconds = keep_seconds
        self.jobs: dict[str, tuple[float, DealJob]] = {}
        self.by_criteria: dict[str, str] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def _prune(self) -> None:
        now = time.monotonic()
        for job_id, (stamp, job) in list(self.jobs.items()):
            if job.status != "running" and now - stamp > self.keep_seconds:
                del self.jobs[job_id]
        self.by_criteria = {k: v for k, v in self.by_criteria.items() if v in self.jobs}

    def running(self) -> int:
        return sum(1 for _, j in self.jobs.values() if j.status == "running")

    def start(self, criteria: DealCriteria, refresh: bool = False) -> DealJob:
        self._prune()
        key = criteria_key(criteria)
        existing_id = self.by_criteria.get(key)
        if existing_id and existing_id in self.jobs:
            stamp, job = self.jobs[existing_id]
            fresh = time.monotonic() - stamp < self.cache_seconds
            if job.status == "running":
                return job
            if job.status == "done" and fresh and not refresh and job.result:
                return job.model_copy(update={"result": job.result.model_copy(update={"cached": True})})
        if self.running() >= self.max_running:
            raise RuntimeError("Der kører allerede en tilbudsjagt - vent til den er færdig")

        job = DealJob(id=uuid.uuid4().hex, status="running")
        self.jobs[job.id] = (time.monotonic(), job)
        self.by_criteria[key] = job.id
        task = asyncio.create_task(self._run(job, criteria))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def _run(self, job: DealJob, criteria: DealCriteria) -> None:
        try:
            job.result = await find_deals(criteria)
            job.status = "done"
        except claude.ClaudeError as err:
            job.error, job.status = str(err), "error"
        except Exception:  # noqa: BLE001 - vises som generel fejl i appen
            _LOGGER.exception("Tilbudsjagt fejlede")
            job.error, job.status = "Der skete en fejl under tilbudsjagten - prøv igen", "error"
        self.jobs[job.id] = (time.monotonic(), job)

    def get(self, job_id: str) -> DealJob | None:
        hit = self.jobs.get(job_id)
        return hit[1] if hit else None
