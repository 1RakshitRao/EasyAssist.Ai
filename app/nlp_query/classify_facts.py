"""Classify company_facts questions into a single category (and optional entity)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

CATEGORIES = (
    "clients",
    "services",
    "locations",
    "products",
    "team",
    "partnerships",
)

# Exact entity → category (longest names first when matching)
ENTITY_CATEGORY: dict[str, str] = {
    "global tech partners": "clients",
    "acme corporation": "clients",
    "meridian group": "clients",
    "vertex solutions": "clients",
    "bluewater capital": "clients",
    "apex retail group": "clients",
    "northstar insurance": "clients",
    "orion energy": "clients",
    "cascade pharma": "clients",
    "redwood logistics": "clients",
    "ai, genai & agentic ai": "services",
    "intelligent automation": "services",
    "infrastructure modernization": "services",
    "cybersecurity and risk management": "services",
    "forensic accounting and fraud investigations": "services",
    "staffing services": "services",
    "chantilly, va": "locations",
    "u.s. office network": "locations",
    "global office network": "locations",
    "innovation labs": "locations",
    "nashik campus": "locations",
    "atlanta, ga": "locations",
    "charlotte, nc": "locations",
    "chicago, il": "locations",
    "dallas, tx": "locations",
    "denver, co": "locations",
    "detroit, mi": "locations",
    "farmington, ct": "locations",
    "houston, tx": "locations",
    "jacksonville, fl": "locations",
    "newark, ca": "locations",
    "new york, ny": "locations",
    "owings mills, md": "locations",
    "parsippany, nj": "locations",
    "richmond, va": "locations",
    "san francisco, ca": "locations",
    "washington, dc": "locations",
    "columbus, oh": "locations",
    "birmingham, al": "locations",
    "ampcus knowledge base": "products",
    "ops health dashboard": "products",
    "client portal": "products",
    "compliance tracker": "products",
    "ai query engine": "products",
    "field service app": "products",
    'anjali "ann" ramakumaran': "team",
    "anjali ramakumaran": "team",
    "ann ramakumaran": "team",
    "salil sankaran": "team",
    "ramana challa": "team",
    "charles mcmahon": "team",
    "danielle gardiner": "team",
    "chris brosnan": "team",
    "joe scarlato": "team",
    "biju george": "team",
    "donna howell": "team",
    "samir sankaran": "team",
    "sanjeev chauhan": "team",
    "carlos rivera": "team",
    "phani kumar": "team",
    "jim jacobsen": "team",
    "karen kok": "team",
    "oma taiga": "team",
    "kamal vadrevu": "team",
    "rashme vohra": "team",
    "shweta bhanot": "team",
    "julie potter": "team",
    "abhishek gautam": "team",
    "laurie smith": "team",
    "sap": "partnerships",
    "oracle": "partnerships",
    "salesforce": "partnerships",
    "appian": "partnerships",
    "vmware": "partnerships",
    "uipath": "partnerships",
    "snowflake": "partnerships",
    "blackberry": "partnerships",
    "avaya": "partnerships",
    "cisco": "partnerships",
    "ruckus": "partnerships",
    "sas": "partnerships",
    "terremark": "partnerships",
    "ns2": "partnerships",
    "carpathia": "partnerships",
    "microsoft": "partnerships",
    "alliance for science": "partnerships",
    "diversity alliance": "partnerships",
}

_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "clients": (
        "client",
        "clients",
        "customer",
        "customers",
        "account",
        "accounts",
        "enterprise client",
        "strategic account",
    ),
    "services": (
        "service",
        "services",
        "practice area",
        "what do we offer",
        "offering",
        "offerings",
        "genai",
        "agentic",
        "forensics",
        "staffing",
        "automation",
        "cybersecurity",
    ),
    "locations": (
        "location",
        "locations",
        "office",
        "offices",
        "hq",
        "headquarters",
        "where are",
        "chantilly",
        "atlanta",
        "charlotte",
        "chicago",
        "dallas",
        "denver",
        "detroit",
        "houston",
        "jacksonville",
        "newark",
        "new york",
        "richmond",
        "san francisco",
        "washington",
        "columbus",
        "birmingham",
        "nashik",
        "innovation lab",
        "global office",
    ),
    "products": (
        "product",
        "products",
        "platform",
        "dashboard",
        "portal",
        "app",
    ),
    "team": (
        "team",
        "who leads",
        "head of",
        "cto",
        "who is the",
        "leadership",
        "people",
    ),
    "partnerships": (
        "partnership",
        "partnerships",
        "vendor",
        "vendors",
        "technology partner",
        "tech partner",
        "tech partners",
        "cloud partner",
        "our partners",
        "which partners",
        "partner with",
        "partners with",
    ),
}


@dataclass
class FactsClassification:
    category: Optional[str]
    entity_name: Optional[str] = None
    reason: str = ""
    confidence: str = "medium"  # high | medium | low


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _match_entity(q: str) -> Optional[tuple[str, str]]:
    for name in sorted(ENTITY_CATEGORY.keys(), key=len, reverse=True):
        if name in q:
            return name, ENTITY_CATEGORY[name]
    return None


def _score_categories(q: str) -> dict[str, int]:
    scores = {c: 0 for c in CATEGORIES}
    for cat, words in _CATEGORY_KEYWORDS.items():
        for w in words:
            if w in q:
                # Longer / more specific phrases weigh more
                scores[cat] += 2 if " " in w else 1
    # Whole-word aws/okta → partnerships
    if re.search(r"\b(aws|okta)\b", q):
        scores["partnerships"] += 3
    # Bare "partners" (not already counted via "our partners") → partnerships intent
    if re.search(r"\bpartners?\b", q) and "global tech partners" not in q:
        if scores["partnerships"] == 0:
            scores["partnerships"] += 2
    if any(w in q for w in ("cto", "chief technology officer", "chief technology")):
        scores["team"] += 3
    # "client portal" is a product — don't boost clients from "client" alone in that phrase
    if "client portal" in q:
        scores["products"] += 3
        scores["clients"] = max(0, scores["clients"] - 1)
    return scores


def classify_company_facts(question: str) -> FactsClassification:
    """
    Classify a Company-data question into exactly one company_facts category.

    Priority:
    1. Known entity name → that entity's category (e.g. Global Tech Partners → clients)
    2. Keyword scores → winning category
    3. None → broad list across categories
    """
    q = _normalize(question)
    if not q:
        return FactsClassification(category=None, reason="empty", confidence="low")

    entity = _match_entity(q)
    if entity:
        name, cat = entity
        return FactsClassification(
            category=cat,
            entity_name=name,
            reason=f"entity:{name}",
            confidence="high",
        )

    scores = _score_categories(q)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_cat, best = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0

    if best <= 0:
        return FactsClassification(
            category=None,
            reason="no_category_signal",
            confidence="low",
        )

    # Tie-break clients vs partnerships: prefer the more specific signal set
    if best_cat in {"clients", "partnerships"} and second == best:
        other = "partnerships" if best_cat == "clients" else "clients"
        if scores[other] == best:
            # Prefer explicit wording
            if any(w in q for w in ("client", "clients", "customer", "customers")):
                best_cat = "clients"
            elif any(
                w in q
                for w in (
                    "partnership",
                    "vendor",
                    "partners",
                    "partner",
                )
            ):
                best_cat = "partnerships"

    confidence = "high" if best >= second + 2 else "medium"
    return FactsClassification(
        category=best_cat,
        reason=f"keywords:{best_cat}={best}",
        confidence=confidence,
    )
