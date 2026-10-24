"""An optional language-model step for what the rules cannot fix.

Vendor-neutral: OpenAI, Anthropic, or any OpenAI-compatible endpoint (a
local model server included), configured by the user — environment
variables, or ~/.matbaa/llm.json:

    {"provider": "openai", "model": "...", "api_key": "...", "base_url": "..."}

    MATBAA_LLM_PROVIDER, MATBAA_LLM_MODEL, MATBAA_LLM_API_KEY, MATBAA_LLM_BASE_URL

Nothing is sent unless the user asks for a chapter to be checked, and the
model is never trusted with the text itself. It is asked for two kinds of
proposal only — which paragraphs continue the one before (a sentence cut
at a page), and which words are a scanner's misreadings — and every
proposal is checked before it is shown: the word must be in the paragraph,
the correction must be small, the indices must exist. Applying a proposal
touches text only, never the markup (emphasis, note links) around it.
"""
from __future__ import annotations

import html
import json
import os
import re
import urllib.request
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Dict, List, Optional

SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".matbaa", "llm.json")
DEFAULT_MODELS = {"anthropic": "claude-sonnet-5-5"}
TAG = re.compile(r"<[^>]+>")
MAX_CHAPTER_CHARS = 60000
# a correction may change a few letters of a word, not rewrite it


def _small_correction(wrong: str, right: str) -> bool:
    changed = sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2
                  in SequenceMatcher(None, wrong, right, autojunk=False).get_opcodes() if tag != "equal")
    return changed <= max(2, len(wrong) // 3)


class LLMUnavailable(RuntimeError):
    pass


@dataclass
class Settings:
    provider: str
    model: str
    api_key: str
    base_url: str = ""


def load_settings() -> Optional[Settings]:
    data: Dict = {}
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as fh:
            data = json.load(fh) or {}
    except (OSError, ValueError):
        data = {}
    provider = (os.environ.get("MATBAA_LLM_PROVIDER") or data.get("provider") or "").strip().lower()
    api_key = (os.environ.get("MATBAA_LLM_API_KEY") or data.get("api_key") or "").strip()
    model = (os.environ.get("MATBAA_LLM_MODEL") or data.get("model") or DEFAULT_MODELS.get(provider, "")).strip()
    base_url = (os.environ.get("MATBAA_LLM_BASE_URL") or data.get("base_url") or "").strip()
    if provider not in ("openai", "anthropic") or not model or not (api_key or base_url):
        return None
    return Settings(provider, model, api_key, base_url)


def status() -> Dict:
    s = load_settings()
    return {"available": s is not None, "provider": s.provider if s else None, "model": s.model if s else None}


def _post(url: str, headers: Dict[str, str], body: Dict, timeout: int = 180) -> Dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - user-configured endpoint
        return json.loads(resp.read().decode("utf-8"))


def complete(system: str, prompt: str, max_tokens: int = 4000) -> str:
    s = load_settings()
    if s is None:
        raise LLMUnavailable("Dil modeli ayarlanmamış (~/.matbaa/llm.json ya da MATBAA_LLM_* ortam değişkenleri).")
    if s.provider == "anthropic":
        data = _post((s.base_url or "https://api.anthropic.com") + "/v1/messages",
                     {"x-api-key": s.api_key, "anthropic-version": "2023-06-01"},
                     {"model": s.model, "max_tokens": max_tokens, "system": system,
                      "messages": [{"role": "user", "content": prompt}]})
        return "".join(part.get("text", "") for part in data.get("content", []))
    headers = {"Authorization": f"Bearer {s.api_key}"} if s.api_key else {}
    data = _post((s.base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions", headers,
                 {"model": s.model, "max_tokens": max_tokens,
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]})
    return data["choices"][0]["message"]["content"]


SYSTEM = (
    "You check the text of a book that was extracted from a scanned or typeset PDF. "
    "You never rewrite, translate, modernise or summarise it. You only report two kinds of defect, "
    "as JSON, and nothing else:\n"
    '{"merge": [i, ...], "replace": [{"paragraph": i, "wrong": "...", "right": "..."}, ...]}\n'
    "- merge: indices of paragraphs that are not new paragraphs but the continuation of the one "
    "before them (a sentence cut where a page ended).\n"
    "- replace: a word or two the scanner misread (wrong letters, letters for digits, a lost initial), "
    "copied exactly as it appears in that paragraph, with its correct form. Only clear misreadings; "
    "never style, spelling reforms, or wording. If unsure, leave it out."
)


def split_html(html_text: str) -> List[str]:
    """A chapter's HTML as the pieces a model is shown and a proposal names.
    Joining them back gives the HTML exactly as it was."""
    return [p for p in re.split(r"(?<=</p>)|(?<=</h2>)|(?<=</h3>)|(?<=</div>)|(?<=</figure>)", html_text or "") if p]


def plain_paragraphs(paragraphs: List[str]) -> List[str]:
    return [" ".join(html.unescape(TAG.sub(" ", p)).split()) for p in paragraphs]


def build_prompt(paragraphs: List[str], language: str = "tr") -> str:
    lines = [f"Language of the book: {language}.", "Paragraphs, numbered:"]
    total = 0
    for i, t in enumerate(plain_paragraphs(paragraphs)):
        total += len(t)
        if total > MAX_CHAPTER_CHARS:
            break
        lines.append(f"[{i}] {t}")
    return "\n".join(lines)


def _parse_json(text: str) -> Dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except ValueError:
        return {}


def validate(raw: Dict, paragraphs: List[str]) -> Dict:
    """Keep only proposals that can be true of these paragraphs."""
    texts = plain_paragraphs(paragraphs)
    merges = sorted({int(i) for i in raw.get("merge", []) if str(i).isdigit() and 0 < int(i) < len(texts)})
    replaces = []
    for r in raw.get("replace", []) or []:
        try:
            i, wrong, right = int(r["paragraph"]), str(r["wrong"]), str(r["right"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (0 <= i < len(texts)) or not wrong or wrong == right or wrong not in texts[i]:
            continue
        if len(wrong) > 40 or not _small_correction(wrong, right):
            continue
        replaces.append({"paragraph": i, "wrong": wrong, "right": right})
    return {"merge": merges, "replace": replaces}


def propose(paragraphs: List[str], language: str = "tr") -> Dict:
    return validate(_parse_json(complete(SYSTEM, build_prompt(paragraphs, language))), paragraphs)


def _replace_in_text(html_text: str, wrong: str, right: str) -> str:
    """The proposal names plain text; the paragraph keeps "'" as "&#x27;"."""
    parts = re.split(r"(<[^>]+>)", html_text)
    for old, new in ((wrong, right), (html.escape(wrong), html.escape(right))):
        for k in range(0, len(parts), 2):
            if old in parts[k]:
                parts[k] = parts[k].replace(old, new, 1)
                return "".join(parts)
    return html_text


def apply(paragraphs: List[str], proposals: Dict) -> List[str]:
    out = list(paragraphs)
    for r in proposals.get("replace", []):
        i = r["paragraph"]
        if 0 <= i < len(out):
            out[i] = _replace_in_text(out[i], r["wrong"], r["right"])
    # merge from the end so earlier indices stay valid
    for i in sorted(proposals.get("merge", []), reverse=True):
        if not 0 < i < len(out):
            continue
        prev, cur = out[i - 1], out[i]
        pm = re.match(r"^(<p[^>]*>)(.*)</p>$", prev, re.S)
        cm = re.match(r"^<p[^>]*>(.*)</p>$", cur, re.S)
        if not (pm and cm):
            continue
        joint = pm.group(2).rstrip()
        if joint.endswith(("-", "­")):
            joint = joint.rstrip("-­") + cm.group(1).lstrip()
        else:
            joint = joint + " " + cm.group(1).lstrip()
        out[i - 1] = pm.group(1) + joint + "</p>"
        del out[i]
    return out


# --- the reader's settings, from the app ------------------------------------------

LOCAL_SERVER = os.environ.get("MATBAA_LOCAL_LLM", "http://127.0.0.1:11434")


def save_settings(provider: str, model: str, api_key: Optional[str] = None, base_url: str = "") -> Dict:
    """~/.matbaa/llm.json as the reader set it in the app. A key left empty
    keeps the one saved before; the key is never sent back to the page."""
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as fh:
            old = json.load(fh) or {}
    except (OSError, ValueError):
        old = {}
    data = {"provider": (provider or "").strip().lower(), "model": (model or "").strip(),
            "api_key": (api_key or "").strip() or old.get("api_key", ""), "base_url": (base_url or "").strip()}
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return status()


def clear_settings() -> Dict:
    try:
        os.remove(SETTINGS_FILE)
    except OSError:
        pass
    return status()


def settings_view() -> Dict:
    """What the page may show of the settings: everything but the key."""
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as fh:
            data = json.load(fh) or {}
    except (OSError, ValueError):
        data = {}
    return {"provider": data.get("provider") or "", "model": data.get("model") or "",
            "base_url": data.get("base_url") or "", "has_key": bool(data.get("api_key")),
            "available": status()["available"], "active": status()}


def local_models() -> Optional[List[str]]:
    """The models of a local Ollama server, if one is running (it answers
    OpenAI's API at /v1); None when there is none."""
    try:
        with urllib.request.urlopen(LOCAL_SERVER.rstrip("/") + "/api/tags", timeout=2) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return [m.get("name") for m in data.get("models") or [] if m.get("name")]
