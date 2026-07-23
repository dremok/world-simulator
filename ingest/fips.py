"""FIPS 10-4 country codes (used by GDELT ActionGeo) to ISO 3166-1 alpha-2.

The two standards agree for many countries but diverge dangerously for others
(FIPS GM is Germany, ISO GM is Gambia). Unmapped codes return None rather than
passing through, so a wrong-but-plausible ISO code never reaches the DB.
"""

FIPS_TO_ISO = {
    "AF": "AF", "AL": "AL", "AG": "DZ", "AN": "AD", "AO": "AO", "AC": "AG",
    "AR": "AR", "AM": "AM", "AS": "AU", "AU": "AT", "AJ": "AZ", "BF": "BS",
    "BA": "BH", "BG": "BD", "BB": "BB", "BO": "BY", "BE": "BE", "BH": "BZ",
    "BN": "BJ", "BT": "BT", "BL": "BO", "BK": "BA", "BC": "BW", "BR": "BR",
    "BX": "BN", "BU": "BG", "UV": "BF", "BM": "MM", "BY": "BI", "CB": "KH",
    "CM": "CM", "CA": "CA", "CV": "CV", "CT": "CF", "CD": "TD", "CI": "CL",
    "CH": "CN", "CO": "CO", "CN": "KM", "CF": "CG", "CG": "CD", "CS": "CR",
    "IV": "CI", "HR": "HR", "CU": "CU", "CY": "CY", "EZ": "CZ", "DA": "DK",
    "DJ": "DJ", "DO": "DM", "DR": "DO", "EC": "EC", "EG": "EG", "ES": "SV",
    "EK": "GQ", "ER": "ER", "EN": "EE", "ET": "ET", "FJ": "FJ", "FI": "FI",
    "FR": "FR", "GB": "GA", "GA": "GM", "GG": "GE", "GM": "DE", "GH": "GH",
    "GR": "GR", "GJ": "GD", "GT": "GT", "GV": "GN", "PU": "GW", "GY": "GY",
    "HA": "HT", "HO": "HN", "HU": "HU", "IC": "IS", "IN": "IN", "ID": "ID",
    "IR": "IR", "IZ": "IQ", "EI": "IE", "IS": "IL", "IT": "IT", "JM": "JM",
    "JA": "JP", "JO": "JO", "KZ": "KZ", "KE": "KE", "KR": "KI", "KN": "KP",
    "KS": "KR", "KU": "KW", "KG": "KG", "LA": "LA", "LG": "LV", "LE": "LB",
    "LT": "LS", "LI": "LR", "LY": "LY", "LS": "LI", "LH": "LT", "LU": "LU",
    "MK": "MK", "MA": "MG", "MI": "MW", "MY": "MY", "MV": "MV", "ML": "ML",
    "MT": "MT", "RM": "MH", "MR": "MR", "MP": "MU", "MX": "MX", "FM": "FM",
    "MD": "MD", "MN": "MC", "MG": "MN", "MJ": "ME", "MO": "MA", "MZ": "MZ",
    "WA": "NA", "NR": "NR", "NP": "NP", "NL": "NL", "NZ": "NZ", "NU": "NI",
    "NG": "NE", "NI": "NG", "NO": "NO", "MU": "OM", "PK": "PK", "PS": "PW",
    "PM": "PA", "PP": "PG", "PA": "PY", "PE": "PE", "RP": "PH", "PL": "PL",
    "PO": "PT", "QA": "QA", "RO": "RO", "RS": "RU", "RW": "RW", "SC": "KN",
    "ST": "LC", "VC": "VC", "WS": "WS", "SM": "SM", "TP": "ST", "SA": "SA",
    "SG": "SN", "RI": "RS", "SE": "SC", "SL": "SL", "SN": "SG", "LO": "SK",
    "SI": "SI", "BP": "SB", "SO": "SO", "SF": "ZA", "OD": "SS", "SP": "ES",
    "CE": "LK", "SU": "SD", "NS": "SR", "WZ": "SZ", "SW": "SE", "SZ": "CH",
    "SY": "SY", "TW": "TW", "TI": "TJ", "TZ": "TZ", "TH": "TH", "TT": "TL",
    "TO": "TG", "TN": "TO", "TD": "TT", "TS": "TN", "TU": "TR", "TX": "TM",
    "TV": "TV", "UG": "UG", "UP": "UA", "AE": "AE", "UK": "GB", "US": "US",
    "UY": "UY", "UZ": "UZ", "NH": "VU", "VT": "VA", "VE": "VE", "VM": "VN",
    "YM": "YE", "ZA": "ZM", "ZI": "ZW",
    # Territories that show up in news often enough to matter
    "HK": "HK", "MC": "MO", "GZ": "PS", "WE": "PS", "RQ": "PR", "VQ": "VI",
    "GL": "GL", "NC": "NC", "FP": "PF", "AA": "AW", "UC": "CW", "KV": "XK",
}


def fips_to_iso(code: str | None) -> str | None:
    if not code:
        return None
    return FIPS_TO_ISO.get(code.upper())
