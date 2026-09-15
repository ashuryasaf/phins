"""ISO 3166-1 country reference used for nationality capture.

One canonical list for every surface that asks a customer for a nationality
(registration, login identity gate, classic/chat apply, admin correction):
the browser autocompletes against ``search_countries`` and the server stores
only the resolved alpha-2 code, so "Israel", "israel", "IL", "ISR" and
"ישראל" all persist as ``IL`` and every downstream pipeline compares one
normalised value.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional, Tuple

# (alpha2, alpha3, English name, aliases)
_COUNTRIES: Tuple[Tuple[str, str, str, Tuple[str, ...]], ...] = (
    ("AF", "AFG", "Afghanistan", ()),
    ("AX", "ALA", "Åland Islands", ("Aland Islands",)),
    ("AL", "ALB", "Albania", ()),
    ("DZ", "DZA", "Algeria", ()),
    ("AS", "ASM", "American Samoa", ()),
    ("AD", "AND", "Andorra", ()),
    ("AO", "AGO", "Angola", ()),
    ("AI", "AIA", "Anguilla", ()),
    ("AQ", "ATA", "Antarctica", ()),
    ("AG", "ATG", "Antigua and Barbuda", ()),
    ("AR", "ARG", "Argentina", ("ארגנטינה",)),
    ("AM", "ARM", "Armenia", ()),
    ("AW", "ABW", "Aruba", ()),
    ("AU", "AUS", "Australia", ("אוסטרליה",)),
    ("AT", "AUT", "Austria", ("אוסטריה",)),
    ("AZ", "AZE", "Azerbaijan", ()),
    ("BS", "BHS", "Bahamas", ()),
    ("BH", "BHR", "Bahrain", ()),
    ("BD", "BGD", "Bangladesh", ()),
    ("BB", "BRB", "Barbados", ()),
    ("BY", "BLR", "Belarus", ()),
    ("BE", "BEL", "Belgium", ("בלגיה",)),
    ("BZ", "BLZ", "Belize", ()),
    ("BJ", "BEN", "Benin", ()),
    ("BM", "BMU", "Bermuda", ()),
    ("BT", "BTN", "Bhutan", ()),
    ("BO", "BOL", "Bolivia", ()),
    ("BQ", "BES", "Bonaire, Sint Eustatius and Saba", ("Caribbean Netherlands",)),
    ("BA", "BIH", "Bosnia and Herzegovina", ("Bosnia",)),
    ("BW", "BWA", "Botswana", ()),
    ("BV", "BVT", "Bouvet Island", ()),
    ("BR", "BRA", "Brazil", ("Brasil", "ברזיל")),
    ("IO", "IOT", "British Indian Ocean Territory", ()),
    ("BN", "BRN", "Brunei Darussalam", ("Brunei",)),
    ("BG", "BGR", "Bulgaria", ("בולגריה",)),
    ("BF", "BFA", "Burkina Faso", ()),
    ("BI", "BDI", "Burundi", ()),
    ("CV", "CPV", "Cabo Verde", ("Cape Verde",)),
    ("KH", "KHM", "Cambodia", ()),
    ("CM", "CMR", "Cameroon", ()),
    ("CA", "CAN", "Canada", ("קנדה",)),
    ("KY", "CYM", "Cayman Islands", ()),
    ("CF", "CAF", "Central African Republic", ()),
    ("TD", "TCD", "Chad", ()),
    ("CL", "CHL", "Chile", ()),
    ("CN", "CHN", "China", ("PRC", "סין")),
    ("CX", "CXR", "Christmas Island", ()),
    ("CC", "CCK", "Cocos (Keeling) Islands", ()),
    ("CO", "COL", "Colombia", ()),
    ("KM", "COM", "Comoros", ()),
    ("CG", "COG", "Congo", ("Republic of the Congo", "Congo-Brazzaville")),
    ("CD", "COD", "Congo, Democratic Republic of the", ("DR Congo", "DRC", "Congo-Kinshasa")),
    ("CK", "COK", "Cook Islands", ()),
    ("CR", "CRI", "Costa Rica", ()),
    ("CI", "CIV", "Côte d'Ivoire", ("Ivory Coast", "Cote d'Ivoire")),
    ("HR", "HRV", "Croatia", ()),
    ("CU", "CUB", "Cuba", ()),
    ("CW", "CUW", "Curaçao", ("Curacao",)),
    ("CY", "CYP", "Cyprus", ("קפריסין",)),
    ("CZ", "CZE", "Czechia", ("Czech Republic",)),
    ("DK", "DNK", "Denmark", ("דנמרק",)),
    ("DJ", "DJI", "Djibouti", ()),
    ("DM", "DMA", "Dominica", ()),
    ("DO", "DOM", "Dominican Republic", ()),
    ("EC", "ECU", "Ecuador", ()),
    ("EG", "EGY", "Egypt", ("מצרים",)),
    ("SV", "SLV", "El Salvador", ()),
    ("GQ", "GNQ", "Equatorial Guinea", ()),
    ("ER", "ERI", "Eritrea", ()),
    ("EE", "EST", "Estonia", ()),
    ("SZ", "SWZ", "Eswatini", ("Swaziland",)),
    ("ET", "ETH", "Ethiopia", ("אתיופיה",)),
    ("FK", "FLK", "Falkland Islands", ("Malvinas",)),
    ("FO", "FRO", "Faroe Islands", ()),
    ("FJ", "FJI", "Fiji", ()),
    ("FI", "FIN", "Finland", ()),
    ("FR", "FRA", "France", ("צרפת",)),
    ("GF", "GUF", "French Guiana", ()),
    ("PF", "PYF", "French Polynesia", ()),
    ("TF", "ATF", "French Southern Territories", ()),
    ("GA", "GAB", "Gabon", ()),
    ("GM", "GMB", "Gambia", ()),
    ("GE", "GEO", "Georgia", ("גאורגיה",)),
    ("DE", "DEU", "Germany", ("Deutschland", "גרמניה")),
    ("GH", "GHA", "Ghana", ()),
    ("GI", "GIB", "Gibraltar", ()),
    ("GR", "GRC", "Greece", ("Hellas", "יוון")),
    ("GL", "GRL", "Greenland", ()),
    ("GD", "GRD", "Grenada", ()),
    ("GP", "GLP", "Guadeloupe", ()),
    ("GU", "GUM", "Guam", ()),
    ("GT", "GTM", "Guatemala", ()),
    ("GG", "GGY", "Guernsey", ()),
    ("GN", "GIN", "Guinea", ()),
    ("GW", "GNB", "Guinea-Bissau", ()),
    ("GY", "GUY", "Guyana", ()),
    ("HT", "HTI", "Haiti", ()),
    ("HM", "HMD", "Heard Island and McDonald Islands", ()),
    ("VA", "VAT", "Holy See", ("Vatican", "Vatican City")),
    ("HN", "HND", "Honduras", ()),
    ("HK", "HKG", "Hong Kong", ()),
    ("HU", "HUN", "Hungary", ("הונגריה",)),
    ("IS", "ISL", "Iceland", ()),
    ("IN", "IND", "India", ("הודו",)),
    ("ID", "IDN", "Indonesia", ()),
    ("IR", "IRN", "Iran", ("Iran, Islamic Republic of",)),
    ("IQ", "IRQ", "Iraq", ()),
    ("IE", "IRL", "Ireland", ("אירלנד",)),
    ("IM", "IMN", "Isle of Man", ()),
    ("IL", "ISR", "Israel", ("ישראל", "Israeli")),
    ("IT", "ITA", "Italy", ("Italia", "איטליה")),
    ("JM", "JAM", "Jamaica", ()),
    ("JP", "JPN", "Japan", ("יפן",)),
    ("JE", "JEY", "Jersey", ()),
    ("JO", "JOR", "Jordan", ("ירדן",)),
    ("KZ", "KAZ", "Kazakhstan", ()),
    ("KE", "KEN", "Kenya", ()),
    ("KI", "KIR", "Kiribati", ()),
    ("KP", "PRK", "Korea, Democratic People's Republic of", ("North Korea", "DPRK")),
    ("KR", "KOR", "Korea, Republic of", ("South Korea", "Korea")),
    ("KW", "KWT", "Kuwait", ()),
    ("KG", "KGZ", "Kyrgyzstan", ()),
    ("LA", "LAO", "Lao People's Democratic Republic", ("Laos",)),
    ("LV", "LVA", "Latvia", ()),
    ("LB", "LBN", "Lebanon", ()),
    ("LS", "LSO", "Lesotho", ()),
    ("LR", "LBR", "Liberia", ()),
    ("LY", "LBY", "Libya", ()),
    ("LI", "LIE", "Liechtenstein", ()),
    ("LT", "LTU", "Lithuania", ()),
    ("LU", "LUX", "Luxembourg", ()),
    ("MO", "MAC", "Macao", ("Macau",)),
    ("MG", "MDG", "Madagascar", ()),
    ("MW", "MWI", "Malawi", ()),
    ("MY", "MYS", "Malaysia", ()),
    ("MV", "MDV", "Maldives", ()),
    ("ML", "MLI", "Mali", ()),
    ("MT", "MLT", "Malta", ()),
    ("MH", "MHL", "Marshall Islands", ()),
    ("MQ", "MTQ", "Martinique", ()),
    ("MR", "MRT", "Mauritania", ()),
    ("MU", "MUS", "Mauritius", ()),
    ("YT", "MYT", "Mayotte", ()),
    ("MX", "MEX", "Mexico", ("México", "מקסיקו")),
    ("FM", "FSM", "Micronesia", ()),
    ("MD", "MDA", "Moldova", ()),
    ("MC", "MCO", "Monaco", ()),
    ("MN", "MNG", "Mongolia", ()),
    ("ME", "MNE", "Montenegro", ()),
    ("MS", "MSR", "Montserrat", ()),
    ("MA", "MAR", "Morocco", ("מרוקו",)),
    ("MZ", "MOZ", "Mozambique", ()),
    ("MM", "MMR", "Myanmar", ("Burma",)),
    ("NA", "NAM", "Namibia", ()),
    ("NR", "NRU", "Nauru", ()),
    ("NP", "NPL", "Nepal", ()),
    ("NL", "NLD", "Netherlands", ("Holland", "The Netherlands", "הולנד")),
    ("NC", "NCL", "New Caledonia", ()),
    ("NZ", "NZL", "New Zealand", ()),
    ("NI", "NIC", "Nicaragua", ()),
    ("NE", "NER", "Niger", ()),
    ("NG", "NGA", "Nigeria", ()),
    ("NU", "NIU", "Niue", ()),
    ("NF", "NFK", "Norfolk Island", ()),
    ("MK", "MKD", "North Macedonia", ("Macedonia",)),
    ("MP", "MNP", "Northern Mariana Islands", ()),
    ("NO", "NOR", "Norway", ("נורווגיה",)),
    ("OM", "OMN", "Oman", ()),
    ("PK", "PAK", "Pakistan", ()),
    ("PW", "PLW", "Palau", ()),
    ("PS", "PSE", "Palestine, State of", ("Palestine",)),
    ("PA", "PAN", "Panama", ()),
    ("PG", "PNG", "Papua New Guinea", ()),
    ("PY", "PRY", "Paraguay", ()),
    ("PE", "PER", "Peru", ()),
    ("PH", "PHL", "Philippines", ()),
    ("PN", "PCN", "Pitcairn", ()),
    ("PL", "POL", "Poland", ("Polska", "פולין")),
    ("PT", "PRT", "Portugal", ("פורטוגל",)),
    ("PR", "PRI", "Puerto Rico", ()),
    ("QA", "QAT", "Qatar", ()),
    ("RE", "REU", "Réunion", ("Reunion",)),
    ("RO", "ROU", "Romania", ("רומניה",)),
    ("RU", "RUS", "Russian Federation", ("Russia", "רוסיה")),
    ("RW", "RWA", "Rwanda", ()),
    ("BL", "BLM", "Saint Barthélemy", ("Saint Barthelemy",)),
    ("SH", "SHN", "Saint Helena, Ascension and Tristan da Cunha", ("Saint Helena",)),
    ("KN", "KNA", "Saint Kitts and Nevis", ()),
    ("LC", "LCA", "Saint Lucia", ()),
    ("MF", "MAF", "Saint Martin (French part)", ("Saint Martin",)),
    ("PM", "SPM", "Saint Pierre and Miquelon", ()),
    ("VC", "VCT", "Saint Vincent and the Grenadines", ()),
    ("WS", "WSM", "Samoa", ()),
    ("SM", "SMR", "San Marino", ()),
    ("ST", "STP", "Sao Tome and Principe", ()),
    ("SA", "SAU", "Saudi Arabia", ()),
    ("SN", "SEN", "Senegal", ()),
    ("RS", "SRB", "Serbia", ()),
    ("SC", "SYC", "Seychelles", ()),
    ("SL", "SLE", "Sierra Leone", ()),
    ("SG", "SGP", "Singapore", ()),
    ("SX", "SXM", "Sint Maarten (Dutch part)", ("Sint Maarten",)),
    ("SK", "SVK", "Slovakia", ()),
    ("SI", "SVN", "Slovenia", ()),
    ("SB", "SLB", "Solomon Islands", ()),
    ("SO", "SOM", "Somalia", ()),
    ("ZA", "ZAF", "South Africa", ("דרום אפריקה",)),
    ("GS", "SGS", "South Georgia and the South Sandwich Islands", ()),
    ("SS", "SSD", "South Sudan", ()),
    ("ES", "ESP", "Spain", ("España", "ספרד")),
    ("LK", "LKA", "Sri Lanka", ()),
    ("SD", "SDN", "Sudan", ()),
    ("SR", "SUR", "Suriname", ()),
    ("SJ", "SJM", "Svalbard and Jan Mayen", ()),
    ("SE", "SWE", "Sweden", ("שוודיה",)),
    ("CH", "CHE", "Switzerland", ("שווייץ",)),
    ("SY", "SYR", "Syrian Arab Republic", ("Syria",)),
    ("TW", "TWN", "Taiwan", ()),
    ("TJ", "TJK", "Tajikistan", ()),
    ("TZ", "TZA", "Tanzania", ()),
    ("TH", "THA", "Thailand", ("תאילנד",)),
    ("TL", "TLS", "Timor-Leste", ("East Timor",)),
    ("TG", "TGO", "Togo", ()),
    ("TK", "TKL", "Tokelau", ()),
    ("TO", "TON", "Tonga", ()),
    ("TT", "TTO", "Trinidad and Tobago", ()),
    ("TN", "TUN", "Tunisia", ()),
    ("TR", "TUR", "Türkiye", ("Turkey", "Turkiye", "טורקיה")),
    ("TM", "TKM", "Turkmenistan", ()),
    ("TC", "TCA", "Turks and Caicos Islands", ()),
    ("TV", "TUV", "Tuvalu", ()),
    ("UG", "UGA", "Uganda", ()),
    ("UA", "UKR", "Ukraine", ("אוקראינה",)),
    ("AE", "ARE", "United Arab Emirates", ("UAE", "Emirates")),
    ("GB", "GBR", "United Kingdom", ("UK", "Great Britain", "Britain", "England", "Scotland", "Wales", "בריטניה")),
    ("US", "USA", "United States", ("USA", "United States of America", "America", "U.S.", "U.S.A.", "ארה\"ב", "ארצות הברית")),
    ("UM", "UMI", "United States Minor Outlying Islands", ()),
    ("UY", "URY", "Uruguay", ()),
    ("UZ", "UZB", "Uzbekistan", ()),
    ("VU", "VUT", "Vanuatu", ()),
    ("VE", "VEN", "Venezuela", ()),
    ("VN", "VNM", "Viet Nam", ("Vietnam",)),
    ("VG", "VGB", "Virgin Islands (British)", ("British Virgin Islands",)),
    ("VI", "VIR", "Virgin Islands (U.S.)", ("US Virgin Islands",)),
    ("WF", "WLF", "Wallis and Futuna", ()),
    ("EH", "ESH", "Western Sahara", ()),
    ("YE", "YEM", "Yemen", ()),
    ("ZM", "ZMB", "Zambia", ()),
    ("ZW", "ZWE", "Zimbabwe", ()),
)

COUNTRIES: List[Dict[str, object]] = [
    {"code": a2, "alpha3": a3, "name": name, "aliases": list(aliases)}
    for a2, a3, name, aliases in _COUNTRIES
]
COUNTRY_BY_CODE: Dict[str, Dict[str, object]] = {c["code"]: c for c in COUNTRIES}  # type: ignore[misc]


def _fold(value: str) -> str:
    """Case/accents/punctuation-insensitive key for matching."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9\u0590-\u05ff]+", " ", text)
    return " ".join(text.split())


_LOOKUP: Dict[str, str] = {}
for _a2, _a3, _name, _aliases in _COUNTRIES:
    _LOOKUP[_fold(_a2)] = _a2
    _LOOKUP[_fold(_a3)] = _a2
    _LOOKUP[_fold(_name)] = _a2
    for _alias in _aliases:
        _LOOKUP.setdefault(_fold(_alias), _a2)


def resolve_country(value: object) -> Optional[str]:
    """Resolve free text / alpha-2 / alpha-3 / alias to an alpha-2 code.

    Returns None when nothing matches unambiguously; callers must treat that
    as invalid input rather than guessing.
    """
    key = _fold(str(value or ""))
    if not key:
        return None
    if key in _LOOKUP:
        return _LOOKUP[key]
    # A unique prefix match on the English name ("united arab" -> AE) is
    # accepted; ambiguous prefixes ("united") are not.
    matches = {code for folded, code in _LOOKUP.items() if folded.startswith(key)}
    return matches.pop() if len(matches) == 1 else None


def country_name(code: object) -> Optional[str]:
    entry = COUNTRY_BY_CODE.get(str(code or "").upper())
    return str(entry["name"]) if entry else None


def search_countries(query: object, limit: int = 12) -> List[Dict[str, str]]:
    """Autocomplete: rank exact code/alias hits, then name prefixes, then substrings."""
    key = _fold(str(query or ""))
    ranked: List[Tuple[int, str, Dict[str, str]]] = []
    for entry in COUNTRIES:
        code = str(entry["code"])
        name = str(entry["name"])
        haystacks = [_fold(code), _fold(str(entry["alpha3"])), _fold(name)] + [
            _fold(a) for a in entry["aliases"]  # type: ignore[union-attr]
        ]
        if not key:
            score = 3
        elif key in (haystacks[0], haystacks[1]) or key in haystacks[2:]:
            score = 0
        elif any(h.startswith(key) for h in haystacks):
            score = 1
        elif any(key in h for h in haystacks):
            score = 2
        else:
            continue
        ranked.append((score, name, {"code": code, "name": name}))
    ranked.sort(key=lambda r: (r[0], r[1]))
    return [r[2] for r in ranked[: max(1, min(int(limit or 12), 50))]]
