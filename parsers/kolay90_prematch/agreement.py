"""Detect and accept the Kolay90 user-agreement page. Isolated experiment only."""

from __future__ import annotations

import unicodedata

ACCEPT_WORDS = (
    "kabul et",
    "kabul ediyorum",
    "kabul",
    "onayliyorum",
    "onaylıyorum",
    "onayla",
    "evet",
    "accept",
    "agree",
    "i agree",
    "tamam",
)
REJECT_WORDS = (
    "reddet",
    "kabul etmiyorum",
    "hayir",
    "hayır",
    "vazgec",
    "vazgeç",
    "iptal",
    "reject",
    "disagree",
    "cancel",
    "no",
)
AGREEMENT_MARKERS = (
    "sozlesme",
    "sozleşme",
    "sözleşme",
    "sözlesme",
    "user agreement",
    "bilgilendirme ve eglence",
    "bilgilendirme ve eğlence",
    "son kararın admine",
    "son kararin admine",
)


def fold(text: str) -> str:
    lowered = (text or "").casefold()
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", lowered) if not unicodedata.combining(ch)
    )


def is_agreement_page(url: str = "", title: str = "", text: str = "") -> bool:
    blob = fold(f"{url} {title} {text}")
    if "sozlesme" in fold(url or ""):
        return True
    return any(fold(marker) in blob for marker in AGREEMENT_MARKERS)


def _score_label(label: str) -> str | None:
    text = fold(label).strip()
    if not text:
        return None
    if any(fold(word) == text or fold(word) in text for word in REJECT_WORDS):
        return "reject"
    if any(fold(word) == text or fold(word) in text for word in ACCEPT_WORDS):
        return "accept"
    return None


def classify_agreement_buttons(buttons: list[dict]) -> dict:
    scored = []
    for item in buttons:
        label = str(item.get("text") or "")
        role = _score_label(label)
        if role:
            scored.append({**item, "role": role, "text": label[:80]})
    accepts = [item for item in scored if item["role"] == "accept"]
    rejects = [item for item in scored if item["role"] == "reject"]
    chosen = None
    if len(accepts) == 1:
        chosen = accepts[0]
    elif len(accepts) > 1:
        exact = [item for item in accepts if fold(item["text"]) in {fold(w) for w in ACCEPT_WORDS}]
        if len(exact) == 1:
            chosen = exact[0]
    return {
        "accept_candidates": [item.get("text") for item in accepts],
        "reject_candidates": [item.get("text") for item in rejects],
        "chosen": chosen,
        "ambiguous": chosen is None and len(accepts) != 1,
    }
