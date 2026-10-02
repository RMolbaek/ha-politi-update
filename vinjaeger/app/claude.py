"""Claude-integrationen: genkend en etiket og find priser på nettet."""

from __future__ import annotations

import base64
import logging
import os
from typing import Any

import anthropic

from .models import WineIdentity

_LOGGER = logging.getLogger(__name__)

MODEL = os.environ.get("VINJAEGER_MODEL", "claude-opus-5-5")
# "default" lader API'et vælge en fallback-model, hvis en forespørgsel afvises.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_ROUNDS = 6

IDENTIFY_PROMPT = """\
Billedet viser en vinflaske, en etiket eller et skærmbillede af en vin.
Udfyld felterne så præcist som muligt ud fra det, der faktisk kan ses.
Gæt ikke på årgang eller flaskestørrelse, hvis de ikke fremgår.
search_query skal være den korte tekst, man ville søge på i en dansk webshop
for at finde præcis denne vin (producent + vinnavn, uden årgang)."""

SEARCH_SYSTEM = """\
Du er en prisjæger for vin i Danmark. Brugeren står og kigger på en bestemt vin
og vil vide, om den kan købes billigere andre steder.

Fremgangsmåde:
1. Søg efter vinen hos danske vinforhandlere, supermarkedskæder med webshop og
   prissammenligningssider. Søg gerne flere gange med varianter af navnet.
2. Åbn de mest lovende produktsider og aflæs den aktuelle pris. Medtag kun
   tilbud, hvor prisen står på en side, du har set i denne søgning.
3. Det skal være samme vin (samme producent og cuvée). Notér årgang og
   flaskestørrelse. Kassepriser/mængderabat ("v. køb af 6") angives som pris pr.
   flaske, med forklaring i note.
4. Afslut ALTID ved at kalde værktøjet report_offers med alt, du har fundet -
   også hvis listen er tom.

Priser er i danske kroner inkl. moms. Udenlandske shops kun hvis de leverer til
Danmark, og prisen skal så omregnes til DKK (skriv det i note)."""

REPORT_TOOL: dict[str, Any] = {
    "name": "report_offers",
    "description": "Rapportér de fundne pristilbud på vinen. Kaldes præcis én gang til sidst.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["offers", "summary"],
        "properties": {
            "summary": {
                "type": "string",
                "description": "1-2 sætninger på dansk om resultatet",
            },
            "offers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "shop", "url", "price_dkk", "bottle_ml",
                        "vintage", "in_stock", "note",
                    ],
                    "properties": {
                        "shop": {"type": "string"},
                        "url": {"type": "string", "description": "Direkte link til produktsiden"},
                        "price_dkk": {"type": "number", "description": "Pris pr. flaske i DKK"},
                        "bottle_ml": {"type": "integer"},
                        "vintage": {"type": ["integer", "null"]},
                        "in_stock": {"type": ["boolean", "null"]},
                        "note": {"type": ["string", "null"]},
                    },
                },
            },
        },
    },
}


class ClaudeError(RuntimeError):
    """Fejl der kan vises til brugeren."""


def _client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic()


async def identify_label(image: bytes, media_type: str) -> WineIdentity:
    """Læs en etiket via Claude vision og returnér strukturerede data."""
    client = _client()
    response = await client.beta.messages.parse(
        model=MODEL,
        max_tokens=4000,
        betas=[FALLBACK_BETA],
        fallbacks="default",
        output_config={"effort": "low"},
        output_format=WineIdentity,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": base64.standard_b64encode(image).decode("ascii"),
                        },
                    },
                    {"type": "text", "text": IDENTIFY_PROMPT},
                ],
            }
        ],
    )
    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise ClaudeError("Kunne ikke genkende vinen på billedet.")
    return response.parsed_output


def _search_request(query: str, vintage: int | None, ean: str | None) -> str:
    lines = [f"Vin: {query}"]
    if vintage:
        lines.append(f"Årgang: {vintage} (andre årgange må gerne med, men markér dem)")
    if ean:
        lines.append(f"Stregkode (EAN): {ean}")
    lines.append("Find hvor den sælges i Danmark og hvad den koster.")
    return "\n".join(lines)


def _web_tools(searches: int, fetches: int) -> list[dict[str, Any]]:
    return [
        {
            "type": "web_search_20260209",
            "name": "web_search",
            "max_uses": searches,
            "user_location": {"type": "approximate", "country": "DK"},
        },
        {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": fetches},
    ]


async def _run_agent(
    system: str,
    request: str,
    tools: list[dict[str, Any]],
    report_tool: str,
    effort: str = "medium",
) -> dict[str, Any]:
    """Kør Claude med websøgning, indtil den kalder rapport-værktøjet."""
    client = _client()
    messages: list[dict[str, Any]] = [{"role": "user", "content": request}]

    for _ in range(MAX_ROUNDS):
        response = await client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            output_config={"effort": effort},
            system=system,
            tools=tools,
            messages=messages,
        )
        if response.stop_reason == "refusal":
            raise ClaudeError("Søgningen blev afvist.")

        for block in response.content:
            if block.type == "tool_use" and block.name == report_tool:
                return dict(block.input)

        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason == "pause_turn":
            # Serverværktøjerne er ikke færdige endnu - send igen for at fortsætte.
            continue
        messages.append(
            {"role": "user", "content": f"Kald nu {report_tool} med det, du har fundet."}
        )

    _LOGGER.warning("Ingen %s efter %s runder", report_tool, MAX_ROUNDS)
    raise ClaudeError("Søgningen blev ikke færdig. Prøv igen.")


async def find_offers(
    query: str, vintage: int | None = None, ean: str | None = None
) -> dict[str, Any]:
    """Lad Claude søge nettet igennem og returnér rå tilbud + opsummering."""
    return await _run_agent(
        SEARCH_SYSTEM,
        _search_request(query, vintage, ean),
        [*_web_tools(searches=8, fetches=12), REPORT_TOOL],
        "report_offers",
    )
