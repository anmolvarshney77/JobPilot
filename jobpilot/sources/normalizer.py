from __future__ import annotations

import html as html_module
import re

# ------------------------------------------------------------------
# Company name normalisation
# ------------------------------------------------------------------

_COMPANY_SUFFIX_RE = re.compile(
    r"\s*\b(inc\.?|ltd\.?|gmbh\.?|ag\.?|bv\.?|sas\.?|corp\.?|llc\.?|plc\.?|sarl\.?|srl\.?|nv\.?|oy\.?|ab\.?|as\.?)\s*$",
    re.IGNORECASE,
)
# "SE" is also a country code so we exclude it from generic suffix removal.


def normalize_company_name(name: str) -> str:
    name = name.strip()
    name = _COMPANY_SUFFIX_RE.sub("", name)
    name = name.lower()
    name = re.sub(r"[^\w\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


# ------------------------------------------------------------------
# HTML stripping
# ------------------------------------------------------------------


def strip_html(html: str) -> str:
    if not html:
        return ""
    text = html_module.unescape(html)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ------------------------------------------------------------------
# Title normalisation
# ------------------------------------------------------------------

_GENDER_MARKER_RE = re.compile(
    r"\s*[\(\[]\s*(?:m\s*/\s*w\s*/\s*d|f\s*/\s*m\s*/\s*x|f\s*/\s*m\s*/\s*d|m\s*/\s*f\s*/\s*d|"
    r"all\s+genders|alle\s+geschlechter|w\s*/\s*m\s*/\s*d|d\s*/\s*f\s*/\s*m|any\s+gender)\s*[\)\]]\s*",
    re.IGNORECASE,
)
_LEVEL_SUFFIX_RE = re.compile(
    r"\s+(?:i{1,3}|iv|v|1|2|3|4|5)\s*$",
    re.IGNORECASE,
)


def normalize_title(title: str) -> str:
    title = _GENDER_MARKER_RE.sub(" ", title)
    title = _LEVEL_SUFFIX_RE.sub("", title)
    title = title.lower()
    title = re.sub(r"[^\w\s]", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


# ------------------------------------------------------------------
# Location parsing
# ------------------------------------------------------------------

_CITY_TO_COUNTRY: dict[str, str] = {
    "berlin": "DE", "munich": "DE", "münchen": "DE", "hamburg": "DE",
    "frankfurt": "DE", "cologne": "DE", "köln": "DE", "düsseldorf": "DE",
    "stuttgart": "DE", "nuremberg": "DE", "nürnberg": "DE",
    "amsterdam": "NL", "rotterdam": "NL", "eindhoven": "NL", "utrecht": "NL", "hague": "NL",
    "dublin": "IE", "cork": "IE", "galway": "IE",
    "london": "GB", "manchester": "GB", "edinburgh": "GB", "birmingham": "GB",
    "bristol": "GB", "leeds": "GB", "glasgow": "GB",
    "stockholm": "SE", "gothenburg": "SE", "göteborg": "SE", "malmö": "SE",
    "copenhagen": "DK", "københavn": "DK", "aarhus": "DK",
    "warsaw": "PL", "warszawa": "PL", "kraków": "PL", "krakow": "PL",
    "wrocław": "PL", "wroclaw": "PL", "poznań": "PL", "gdansk": "PL",
    "madrid": "ES", "barcelona": "ES", "valencia": "ES", "seville": "ES", "bilbao": "ES",
    "lisbon": "PT", "lisboa": "PT", "porto": "PT",
    "dubai": "AE", "abu dhabi": "AE", "sharjah": "AE",
    "singapore": "SG",
    "new york": "US", "nyc": "US", "san francisco": "US", "sf": "US",
    "austin": "US", "seattle": "US", "boston": "US", "chicago": "US",
    "los angeles": "US", "la": "US", "new york city": "US", "palo alto": "US",
    "menlo park": "US", "mountain view": "US",
    "bengaluru": "IN", "bangalore": "IN", "mumbai": "IN", "delhi": "IN",
    "new delhi": "IN", "hyderabad": "IN", "pune": "IN", "chennai": "IN",
    "paris": "FR", "lyon": "FR", "toulouse": "FR", "marseille": "FR",
    "zurich": "CH", "zürich": "CH", "geneva": "CH", "bern": "CH",
    "vienna": "AT", "wien": "AT", "graz": "AT",
    "prague": "CZ", "praha": "CZ", "brno": "CZ",
    "budapest": "HU",
    "bucharest": "RO", "bucurești": "RO",
    "toronto": "CA", "vancouver": "CA", "montreal": "CA", "ottawa": "CA",
    "sydney": "AU", "melbourne": "AU", "brisbane": "AU",
    "tel aviv": "IL", "tel-aviv": "IL",
}

_COUNTRY_NAME_TO_ISO: dict[str, str] = {
    "germany": "DE", "deutschland": "DE",
    "netherlands": "NL", "holland": "NL", "the netherlands": "NL",
    "ireland": "IE",
    "united kingdom": "GB", "uk": "GB", "england": "GB", "great britain": "GB",
    "sweden": "SE", "sverige": "SE",
    "denmark": "DK", "danmark": "DK",
    "poland": "PL", "polska": "PL",
    "spain": "ES", "españa": "ES",
    "portugal": "PT",
    "united arab emirates": "AE", "uae": "AE",
    "singapore": "SG",
    "united states": "US", "usa": "US", "u.s.a.": "US", "u.s.": "US",
    "india": "IN",
    "france": "FR",
    "switzerland": "CH",
    "austria": "AT", "österreich": "AT",
    "czechia": "CZ", "czech republic": "CZ",
    "hungary": "HU",
    "romania": "RO",
    "canada": "CA",
    "australia": "AU",
    "israel": "IL",
    # Pass-through ISO codes
    "de": "DE", "nl": "NL", "ie": "IE", "gb": "GB", "se": "SE", "dk": "DK",
    "pl": "PL", "es": "ES", "pt": "PT", "ae": "AE", "sg": "SG", "in": "IN",
    "fr": "FR", "ch": "CH", "at": "AT", "cz": "CZ", "hu": "HU", "ro": "RO",
    "ca": "CA", "au": "AU", "il": "IL", "us": "US",
}


def parse_location(location_raw: str | None) -> tuple[list[str], str | None]:
    if not location_raw:
        return [], None

    loc = location_raw.lower()

    # Detect remote type (order matters: check hybrid before remote)
    remote_type: str | None = None
    if re.search(r"\bhybrid\b", loc):
        remote_type = "hybrid"
    elif re.search(r"\bremote\b|\bworldwide\b|\bwork from anywhere\b|\bfully distributed\b", loc):
        remote_type = "remote"
    elif re.search(r"\bonsite\b|\bon-site\b|\bon site\b|\bin-office\b|\bin office\b", loc):
        remote_type = "onsite"

    countries: list[str] = []

    # City lookup
    for city, iso in _CITY_TO_COUNTRY.items():
        if re.search(r"\b" + re.escape(city) + r"\b", loc):
            if iso not in countries:
                countries.append(iso)

    # Country name / ISO lookup (avoid re-adding cities that matched)
    for name, iso in _COUNTRY_NAME_TO_ISO.items():
        if len(name) == 2:
            # exact word match for ISO codes to avoid false positives
            if re.search(r"(?<![a-z])" + re.escape(name) + r"(?![a-z])", loc):
                if iso not in countries:
                    countries.append(iso)
        else:
            if re.search(r"\b" + re.escape(name) + r"\b", loc):
                if iso not in countries:
                    countries.append(iso)

    return countries, remote_type


# ------------------------------------------------------------------
# Salary parsing
# ------------------------------------------------------------------

_CURRENCY_SYMBOL_MAP: dict[str, str] = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "₹": "INR",
}
_CURRENCY_CODES = ["USD", "EUR", "GBP", "INR", "SEK", "DKK", "PLN", "AED", "SGD", "CHF", "CZK"]

_NUMBER_RE = re.compile(r"(\d[\d,.]*)[\s]*([kK]?)")


def parse_salary(
    raw: str | None, currency_hint: str | None = None
) -> tuple[float | None, float | None, str | None]:
    if not raw:
        return None, None, currency_hint

    currency = currency_hint
    for sym, code in _CURRENCY_SYMBOL_MAP.items():
        if sym in raw:
            currency = code
            break
    if currency is None:
        raw_upper = raw.upper()
        for code in _CURRENCY_CODES:
            if re.search(r"\b" + code + r"\b", raw_upper):
                currency = code
                break

    values: list[float] = []
    for m in _NUMBER_RE.finditer(raw):
        num_str = m.group(1).replace(",", "").replace(".", "")
        multiplier = 1000 if m.group(2) in ("k", "K") else 1
        try:
            values.append(float(num_str) * multiplier)
        except ValueError:
            pass

    if not values:
        return None, None, currency
    if len(values) == 1:
        return values[0], None, currency
    return min(values), max(values), currency


# ------------------------------------------------------------------
# Deduplication key
# ------------------------------------------------------------------


def build_dedupe_key(
    company_normalized: str, title_normalized: str, primary_country: str | None
) -> str:
    return f"{company_normalized}::{title_normalized}::{primary_country or 'any'}"


# ------------------------------------------------------------------
# Title filtering
# ------------------------------------------------------------------

_EXCLUDE_PATTERNS = [
    r"\bstaff\b",
    r"\bprincipal\b",
    r"\bdirector\b",
    r"\bmanager\b",
    r"\bhead of\b",
    r"\bintern\b",
    r"\bwerkstudent\b",
    r"\bpraktikum\b",
    r"\bworking student\b",
    r"\bpraktikant\b",
]


def is_title_excluded(title: str) -> bool:
    lower = title.lower()
    return any(re.search(p, lower) for p in _EXCLUDE_PATTERNS)


def is_title_match(title: str, target_titles: list[str]) -> bool:
    norm = normalize_title(title)
    title_words = set(norm.split())
    for target in target_titles:
        target_words = set(normalize_title(target).split())
        if title_words & target_words:
            return True
    return False
