"""Send a finished EPUB to the reader's Kindle by e-mail.

Amazon's Send to Kindle accepts EPUB attachments mailed to the Kindle's
own address (name@kindle.com) from an address the owner has approved in
their Amazon account. E-mail is limited to 50 MB.

Settings live with the user, not the app: ~/.matbaa/kindle.json —

    {"kindle_email": "...@kindle.com", "from_email": "...",
     "smtp_host": "smtp.gmail.com", "smtp_port": 587, "smtp_user": "..."}

The SMTP password (an app password, not the account password) goes to the
operating system's credential store when the `keyring` package is
installed, otherwise into that same file, which only the user can read.
Nothing is sent except by an explicit, confirmed request.
"""
from __future__ import annotations

import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Dict, Optional

SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".matbaa", "kindle.json")
KEYRING_SERVICE = "matbaa-kindle-smtp"
EMAIL_LIMIT_MB = 50


class KindleNotConfigured(RuntimeError):
    pass


def _keyring():
    try:
        import keyring  # type: ignore
        return keyring
    except ImportError:
        return None


def load() -> Dict:
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as fh:
            settings = json.load(fh) or {}
    except (OSError, ValueError):
        return {}
    return _move_password_to_keyring(settings)


def _move_password_to_keyring(settings: Dict) -> Dict:
    """A password saved in the file before the credential store was there
    is moved into it, and the file rewritten without it."""
    if settings.get("password_in") != "file" or not settings.get("smtp_password"):
        return settings
    kr = _keyring()
    if kr is None:
        return settings
    try:
        kr.set_password(KEYRING_SERVICE, settings.get("smtp_user", ""), settings["smtp_password"])
    except Exception:  # noqa: BLE001
        return settings
    settings = {k: v for k, v in settings.items() if k != "smtp_password"}
    settings["password_in"] = "keyring"
    with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, ensure_ascii=False, indent=1)
    return settings


# which outgoing server goes with which address, for a warning when they differ
_PROVIDER_HOSTS = {
    "gmail.com": "gmail", "googlemail.com": "gmail",
    "hotmail.com": "outlook", "outlook.com": "outlook", "live.com": "outlook", "msn.com": "outlook",
    "icloud.com": "mail.me", "me.com": "mail.me", "mac.com": "mail.me",
    "yahoo.com": "yahoo", "yandex.com": "yandex", "yandex.com.tr": "yandex",
}


def _settings_warning(s: Dict) -> Optional[str]:
    domain = (s.get("from_email") or "").partition("@")[2].lower()
    host = (s.get("smtp_host") or "").lower()
    want = _PROVIDER_HOSTS.get(domain)
    problems = []
    if want and host and want not in host:
        problems.append(f"Gönderen adres {domain}, sunucu ise {host}; ikisi aynı sağlayıcıdan olmalı.")
    user = s.get("smtp_user") or ""
    if user and "@" not in user and domain:
        problems.append("SMTP kullanıcı adı çoğunlukla e-posta adresinin kendisidir.")
    return " ".join(problems) or None


def save(settings: Dict) -> Dict:
    """Store the settings; the password goes to the credential store when one exists."""
    current = load()
    password = settings.pop("smtp_password", None)
    current.update({k: v for k, v in settings.items() if v not in (None, "")})
    if password:
        kr = _keyring()
        if kr is not None:
            kr.set_password(KEYRING_SERVICE, current.get("smtp_user", ""), password)
            current.pop("smtp_password", None)
            current["password_in"] = "keyring"
        else:
            current["smtp_password"] = password
            current["password_in"] = "file"
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
        json.dump(current, fh, ensure_ascii=False, indent=1)
    return status()


def _password(settings: Dict) -> Optional[str]:
    if settings.get("password_in") == "keyring":
        kr = _keyring()
        return kr.get_password(KEYRING_SERVICE, settings.get("smtp_user", "")) if kr else None
    return settings.get("smtp_password")


def _mask(address: str) -> str:
    name, _, domain = (address or "").partition("@")
    return (name[:2] + "…@" + domain) if domain else ""


def status() -> Dict:
    s = load()
    ready = bool(s.get("kindle_email") and s.get("smtp_host") and s.get("smtp_user") and _password(s))
    return {
        "configured": ready,
        "kindle_email": _mask(s.get("kindle_email", "")),
        "from_email": s.get("from_email") or s.get("smtp_user", ""),
        "smtp_host": s.get("smtp_host", ""),
        "password_in": s.get("password_in"),
        "limit_mb": EMAIL_LIMIT_MB,
        "warning": _settings_warning(s),
    }


def send(epub_path: str, title: str, filename: str) -> Dict:
    s = load()
    password = _password(s)
    if not (s.get("kindle_email") and s.get("smtp_host") and s.get("smtp_user") and password):
        raise KindleNotConfigured("Kindle'a gönderme ayarlı değil.")
    size_mb = os.path.getsize(epub_path) / 1e6
    if size_mb > EMAIL_LIMIT_MB:
        raise ValueError(f"EPUB {size_mb:.0f} MB; e-postayla Kindle'a gönderme sınırı {EMAIL_LIMIT_MB} MB. "
                         "Amazon'un web yükleyicisini (200 MB'a kadar) kullanın.")
    msg = EmailMessage()
    msg["From"] = s.get("from_email") or s["smtp_user"]
    msg["To"] = s["kindle_email"]
    msg["Subject"] = title
    msg.set_content(f"{title} — Matbaa ile hazırlandı.")
    with open(epub_path, "rb") as fh:
        msg.add_attachment(fh.read(), maintype="application", subtype="epub+zip", filename=filename)
    port = int(s.get("smtp_port") or 587)
    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(s["smtp_host"], port, context=context, timeout=120) as smtp:
            smtp.login(s["smtp_user"], password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(s["smtp_host"], port, timeout=120) as smtp:
            smtp.starttls(context=context)
            smtp.login(s["smtp_user"], password)
            smtp.send_message(msg)
    return {"sent": True, "to": _mask(s["kindle_email"]), "size_mb": round(size_mb, 1)}
