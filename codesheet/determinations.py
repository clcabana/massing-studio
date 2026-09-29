"""
codesheet.determinations — the one output shape every rule module returns.

A code analysis sheet is a list of lines like

    Building height ............ 6 storeys      [Div. A 1.4.1.2 "Building height"]

Each line is a Determination: what was decided, the value, which clause it
rests on (with the edition and page so a reviewer can open the book), and a
short plain-language "because…" so a junior can follow the reasoning and a
senior can check it. Rule modules never print; they return these, and the
sheet assembler renders them.
"""
from __future__ import annotations

import json, pathlib
from dataclasses import dataclass, field
from typing import Any, Optional

ROOT = pathlib.Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Clause:
    """A citation. `id` is the article or definition; `page` is in the PDF."""
    id: str                      # e.g. "3.2.2.51" or "Div.A 1.4.1.2 'First storey'"
    edition: str                 # e.g. "VBBL 2025 (cons. 2026-01-01)"
    page: Optional[int] = None
    title: Optional[str] = None
    sentence: Optional[int] = None

    def ref(self) -> str:
        s = self.id + (f".({self.sentence})" if self.sentence else "")
        return f"{s} — {self.edition}" + (f", p.{self.page}" if self.page else "")


@dataclass
class Determination:
    key: str                     # machine name, e.g. "north.storeys_above_grade"
    label: str                   # sheet label, e.g. "Building height (storeys)"
    value: Any
    unit: str = ""
    clauses: list[Clause] = field(default_factory=list)
    because: str = ""            # one or two sentences of reasoning
    block: Optional[str] = None  # which firewall-separated building, if any
    inputs: dict = field(default_factory=dict)   # the numbers the rule used
    flags: list[str] = field(default_factory=list)  # warnings for the reviewer

    def display(self) -> str:
        v = f"{self.value:g}" if isinstance(self.value, float) else str(self.value)
        return f"{v} {self.unit}".strip()


# --- clause lookup -----------------------------------------------------------

class Bylaw:
    """Thin reader over data/bylaw/<edition>/articles.json plus the Div. A definitions."""

    DEFINITIONS = {   # Div. A 1.4.1.2, VBBL 2025 — page numbers from the PDF
        "Building area": (32, "the greatest horizontal area of a building above grade within the outside surface of exterior walls or within the outside surface of exterior walls and the centre line of firewalls"),
        "Building height": (32, "the number of storeys contained between the roof and the floor of the first storey"),
        "Basement": (32, "a storey or storeys of a building located below the first storey"),
        "First storey": (36, "the uppermost storey having its floor level not more than 2 m above grade"),
        "Limiting distance": (38, "the distance from an exposing building face to a property line, the centre line of a street, lane or public thoroughfare, or to an imaginary line between 2 buildings or fire compartments on the same property, measured at right angles to the exposing building face"),
        "Grade": (37, "the lowest of the average levels of finished ground adjoining each exterior wall of a building, except that localized depressions need not be considered"),
        "Mezzanine": (40, "an intermediate floor assembly between the floor and ceiling of any room or storey and includes an interior balcony"),
        "Storey": (43, "that portion of a building that is situated between the top of any floor and the top of the floor next above it, and if there is no floor above it, that portion between the top of such floor and the ceiling above it"),
    }

    def __init__(self, edition: str = "vbbl-2025"):
        self.edition_key = edition
        self.edition = {"vbbl-2025": "VBBL 2025 (cons. 2026-01-01)", "bcbc-2024": "BCBC 2024 rev.2"}[edition]
        path = ROOT / "data" / "bylaw" / edition / "articles.json"
        self.articles = {a["id"]: a for a in json.loads(path.read_text(encoding="utf-8"))} if path.exists() else {}

    def article(self, aid: str, sentence: Optional[int] = None) -> Clause:
        a = self.articles.get(aid)
        return Clause(id=aid, edition=self.edition, page=a["page"] if a else None,
                      title=a["title"] if a else None, sentence=sentence)

    def sentence_text(self, aid: str, n: int) -> str:
        a = self.articles.get(aid)
        if not a:
            return ""
        for s in a["sentences"]:
            if s["n"] == n:
                return s["text"]
        return ""

    def definition(self, term: str) -> Clause:
        page, _ = self.DEFINITIONS[term]
        return Clause(id=f"Div. A 1.4.1.2 “{term}”", edition=self.edition, page=page, title=term)

    def definition_text(self, term: str) -> str:
        return self.DEFINITIONS[term][1]
