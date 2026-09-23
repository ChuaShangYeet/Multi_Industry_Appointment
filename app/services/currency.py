"""
Currency conversion for customer-facing price display (PART 4.3 add-on).

Uses the European Central Bank's daily reference rates via
https://api.frankfurter.app - free, no API key required, and backed by a
named, well-established source rather than an anonymous "exchange rate
API", which is what "trusted" buys you here. Only stdlib is used to reach
it (no new HTTP-client dependency for one GET request), and a short
in-process cache keeps a page of service listings from triggering a fresh
external call per row.

A failed or slow lookup (network error, timeout, rate not published) must
never break the page that's asking for it - every function here degrades
to None so the caller just falls back to showing the business's own,
unconverted price.
"""
import json
import time
import urllib.error
import urllib.request
from typing import Optional

import phonenumbers

_RATE_CACHE: dict[tuple[str, str], tuple[float, float]] = {}  # (base, target) -> (rate, fetched_at_monotonic)
_CACHE_TTL_SECONDS = 300
_REQUEST_TIMEOUT_SECONDS = 3


def _fetch_frankfurter(base: str, target: str) -> Optional[float]:
    """European Central Bank reference rates - free, no key, first choice."""
    url = f"https://api.frankfurter.app/latest?from={base}&to={target}"
    try:
        with urllib.request.urlopen(url, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read())
        return float(payload["rates"][target])
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError, OSError):
        return None


def _fetch_open_er_api(base: str, target: str) -> Optional[float]:
    """open.er-api.com - free, no key, second choice if frankfurter.app is unreachable
    (a different host means a network policy or outage blocking one doesn't take out both)."""
    url = f"https://open.er-api.com/v6/latest/{base}"
    try:
        with urllib.request.urlopen(url, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read())
        if payload.get("result") != "success":
            return None
        return float(payload["rates"][target])
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError, OSError):
        return None


_PROVIDERS = (_fetch_frankfurter, _fetch_open_er_api)


def get_exchange_rate(base: str, target: str) -> Optional[float]:
    """How many units of `target` one unit of `base` buys - None if unavailable for any reason."""
    if base == target:
        return 1.0

    cache_key = (base, target)
    cached = _RATE_CACHE.get(cache_key)
    if cached is not None and (time.monotonic() - cached[1]) < _CACHE_TTL_SECONDS:
        return cached[0]

    rate = None
    for fetch in _PROVIDERS:
        rate = fetch(base, target)
        if rate is not None:
            break
    if rate is None:
        return None

    _RATE_CACHE[cache_key] = (rate, time.monotonic())
    return rate


def convert_amount(amount: Optional[float], *, base: str, target: str) -> Optional[float]:
    """Converts `amount` (in `base`) to `target`, or None if the amount or the rate is unavailable."""
    if amount is None:
        return None
    rate = get_exchange_rate(base, target)
    if rate is None:
        return None
    return round(amount * rate, 2)


# Mirrors frontend/src/countries.ts's per-country `currency` field - the
# server-side equivalent for an already-authenticated customer, where their
# phone number (and so their currency) is already on record, rather than
# something the browser has to detect and pass along itself.
_REGION_TO_CURRENCY = {
    "MY": "MYR", "SG": "SGD", "ID": "IDR", "TH": "THB", "PH": "PHP", "VN": "VND",
    "HK": "HKD", "CN": "CNY", "JP": "JPY", "KR": "KRW", "IN": "INR", "AU": "AUD",
    "NZ": "NZD", "AE": "AED", "SA": "SAR", "GB": "GBP", "IE": "EUR", "FR": "EUR",
    "DE": "EUR", "ES": "EUR", "IT": "EUR", "NL": "EUR", "SE": "SEK", "CH": "CHF",
    "US": "USD", "CA": "CAD", "BR": "BRL", "MX": "MXN", "ZA": "ZAR", "NG": "NGN",
}


def currency_for_phone_number(phone_number: Optional[str]) -> Optional[str]:
    """The currency implied by a phone number's country - None if there is no number, or its country isn't one we map."""
    if not phone_number:
        return None
    try:
        parsed = phonenumbers.parse(phone_number, None)
    except phonenumbers.NumberParseException:
        return None
    region = phonenumbers.region_code_for_number(parsed)
    return _REGION_TO_CURRENCY.get(region)
