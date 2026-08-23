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


VISIBLE_BUTTON_JS = """() => {
    const visible = (el) => !!(el && (el.offsetWidth || el.offsetHeight));
    return [...document.querySelectorAll(
        'button, a, input[type=button], input[type=submit], [role=button]'
    )].map((el, index) => ({
        index,
        text: (el.innerText || el.value || el.getAttribute('aria-label') || '')
            .trim().slice(0, 80),
        name: el.getAttribute('name') || '',
        id: el.id || '',
        visible: visible(el),
    })).filter((item) => item.visible && item.text);
}"""


def collect_visible_buttons(page) -> list[dict]:
    try:
        return page.evaluate(VISIBLE_BUTTON_JS) or []
    except Exception:
        return []


def accept_agreement_page(page) -> dict:
    """Click the single ACCEPT control. Never clicks reject."""
    buttons = collect_visible_buttons(page)
    classified = classify_agreement_buttons(buttons)
    chosen = classified.get("chosen")
    if chosen is None:
        return {
            "reached": True,
            "found": False,
            "clicked": False,
            "reason": "ambiguous_or_missing_accept",
            "accept_candidates": classified["accept_candidates"],
            "reject_candidates": classified["reject_candidates"],
        }
    clicked = False
    label = str(chosen.get("text") or "")
    try:
        page.get_by_text(label, exact=False).first.click(timeout=5000)
        clicked = True
    except Exception:
        try:
            locator = page.locator(
                "button, a, input[type=button], input[type=submit], [role=button]"
            )
            locator.nth(int(chosen["index"])).click(timeout=5000)
            clicked = True
        except Exception:
            clicked = False
    return {
        "reached": True,
        "found": True,
        "clicked": clicked,
        "chosen_label_len": len(label),
        "accept_candidates": classified["accept_candidates"],
        "reject_candidates": classified["reject_candidates"],
    }
