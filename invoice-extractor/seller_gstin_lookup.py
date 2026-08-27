"""
Hardcoded Seller GSTIN Lookup
------------------------------
Because seller GSTINs are frequently hallucinated or mis-read by the OCR/AI model,
we override the extracted seller_gstin with the known-correct value whenever the
extracted seller_name matches one of our fixed sellers.

Matching is done case-insensitively on a normalised version of the name
(spaces collapsed, punctuation stripped) so minor OCR variations in the name
still resolve to the correct GSTIN.
"""

import re
from typing import Optional
from langsmith import traceable

# ──────────────────────────────────────────────────────────────────
# MASTER LOOKUP  –  key = normalised seller name, value = GSTIN
# ──────────────────────────────────────────────────────────────────
SELLER_GSTIN_MAP: dict[str, str] = {
    # ── Pharmacea / Pharmalink ──────────────────────────────────────
    "PHARMACEA LINK":                           "27AALFP5376P1ZA",
    "PHARMACEALINK":                            "27AALFP5376P1ZA",

    # ── Aadesh Pharmaceutical ──────────────────────────────────────
    "AADESH PHARMACEUTICAL":                    "27ABLFA7017P1ZX",
    "AADESH PHARMACEUUTICAL":                   "27ABLFA7017P1ZX",
    "AADESH PHARMACEUTICALS":                   "27ABLFA7017P1ZX",

    # ── Progress Healthcare ─────────────────────────────────────────
    "PROGRESS HEALTHCARE MEDICAL SERVICES LLP": "27AAVFP0728M1ZK",
    "PROGRESS HEALTHCARE & MEDICAL SERVICES LLP": "27AAVFP0728M1ZK",

    # ── Shloka Enterprises ──────────────────────────────────────────
    "SHLOKA ENTERPRISES":                       "27AIWPA8054A1ZA",

    # ── Critical Care Systems ────────────────────────────────────────
    "CRITICAL CARE SYSTEMS":                    "27AADFC3319B1Z1",

    # ── Healthcare Enterprises ───────────────────────────────────────
    "HEALTHCARE ENTERPRISES":                   "27AFTPK0484L1ZT",

    # ── Kalpak Marketing ─────────────────────────────────────────────
    "KALPAK MARKETING PVT LTD":                 "27AABCK2267K1ZD",
    "KALPAK MARKETING PRIVATE LIMITED":         "27AABCK2267K1ZD",

    # ── Avian Wellness ───────────────────────────────────────────────
    "AVIAN WELLNESS PVT LTD":                   "27AAOCA5119K1ZD",
    "AVIAN WELLNESS PVTLTD":                    "27AAOCA5119K1ZD",
    "AVIAN WELLNESS PRIVATE LIMITED":           "27AAOCA5119K1ZD",

    # ── New Salakshmi Medisales ───────────────────────────────────────
    "NEW SALAKSHMI MEDISALES LLP":              "27AAOFN3880H1ZT",

    # ── Tapadiya Distributors ────────────────────────────────────────
    "TAPADIYA DISTRIBUTORS":                    "27AABFT1696C1Z8",

    # ── Aakanksha Logistics ──────────────────────────────────────────
    "AAKANKSHA LOGISTICS PVT LTD":              "27AACCA2971K1ZJ",
    "AAKANKSHA LOGISTICS PRIVATE LIMITED":      "27AACCA2971K1ZJ",

    # ── Kanchan Drugs ────────────────────────────────────────────────
    "KANCHAN DRUGS PRIVATE LIMITED":            "27AAACK7501K1ZJ",
    "KANCHAN DRUGS PVT LTD":                    "27AAACK7501K1ZJ",

    # ── Sairaj Distributors ──────────────────────────────────────────
    "SAIRAJ DISTRIBUTORS":                      "27ADLFS9893D1ZC",

    # ── Milton Lifecare ──────────────────────────────────────────────
    "MILTON LIFECARE PRIVATE LIMITED":          "27AAFCM2670J1ZA",
    "MILTON LIFECARE PVT LTD":                  "27AAFCM2670J1ZA",

    # ── Kundan Distributors ──────────────────────────────────────────
    "KUNDAN DISTRIBUTORS PVT LTD":              "27AAHCK2490E1ZJ",
    "KUNDAN DISTRIBUTORS PRIVATE LIMITED":      "27AAHCK2490E1ZJ",

    # ── Nitin Agency Pharmaceutical Distributors ─────────────────────
    "NITIN AGENCY PHARMACEUTICAL DISTRIBUTORS": "27AACFN3926C1ZK",
    "NITIN AGENCY":                             "27AACFN3926C1ZK",

    # ── Yoga Enterprises ─────────────────────────────────────────────
    "YOGA ENTERPRISES":                         "27AAZPP8101A1ZL",

    # ── Scoria Incorporation ─────────────────────────────────────────
    "SCORIA INCORPORATION":                     "27AAUPD9798E1ZX",

    # ── Arihant Biopharma Corporation ────────────────────────────────
    "ARIHANT BIOPHARMA CORPORATION":            "27AAJFA9526G1ZA",

    # ── Chemsearch ───────────────────────────────────────────────────
    "CHEMSEARCH":                               "27AAIFC6533C1ZO",

    # ── Spandan Healthcare ───────────────────────────────────────────
    "SPANDAN HEALTHCARE":                       "27AFIPD4405P1ZA",

    # ── Matrix Biomedics ─────────────────────────────────────────────
    "MATRIX BIOMEDICS PVT LTD":                 "27AADCM2647P1ZZ",
    "MATRIX BIOMEDICS PRIVATE LIMITED":         "27AADCM2647P1ZZ",

    # ── Sanjeevani Enterprise ────────────────────────────────────────
    "SANJEEVANI ENTERPRISE 25 26":              "27ACDFS6564Q1Z9",
    "SANJEEVANI ENTERPRISE 2526":               "27ACDFS6564Q1Z9",
    "SANJEEVANI ENTERPRISE":                    "27ACDFS6564Q1Z9",

    # ── Arihant Chemist LLP ──────────────────────────────────────────
    "ARIHANT CHEMIST LLP":                      "27ABLFA7907J1Z2",

    # ── Tapadiya Life Sciences ───────────────────────────────────────
    "TAPADIYA LIFE SCIENCES":                   "27AAFFT4132P1ZS",

    # ── E Bioremedies ────────────────────────────────────────────────
    "E BIOREMEDIES LTD":                        "27AADCE3683M1Z7",
    "E BIOREMEDIES LIMITED":                    "27AADCE3683M1Z7",

    # ── Oneness Enterprises ──────────────────────────────────────────
    "ONENESS ENTERPRISES":                      "27BGMPM8256M1ZJ",
    "ONENESS ENTERPRISES FY 2025 26":           "27BGMPM8256M1ZJ",
    "ONENESS ENTERPRISES FY 202526":            "27BGMPM8256M1ZJ",

    # ── Vihaan Enterprises ───────────────────────────────────────────
    "VIHAAN ENTERPRISES":                       "27AAVPP4610L1Z4",

    # ── Pranav Medicare ──────────────────────────────────────────────
    "PRANAV MEDICARE 2025 2027":                "27AUVPS6762N1ZB",
    "PRANAV MEDICARE 2025 2026":                "27AUVPS6762N1ZB",
    "PRANAV MEDICARE":                          "27AUVPS6762N1ZB",

    # ── Deenanath Medical Stores ─────────────────────────────────────
    "DEENANATH MEDICAL STORES":                 "27AAATL1944N1ZA",

    # ── Ravi Medico ──────────────────────────────────────────────────
    "RAVI MEDICO":                              "27AAATL1944N1ZA",

    # ── Galaxy Alliance LLP ──────────────────────────────────────────
    "GALAXY ALLIANCE LLP":                      "27AAYFG6456C1ZY",

    # ── MIS Healthcare ───────────────────────────────────────────────
    "MIS HEALTHCARE PVT LTD":                   "27AAHCM2065M1Z5",
    "MIS HEALTHCARE PRIVATE LIMITED":           "27AAHCM2065M1Z5",

    # ── Healthline Private Limited ───────────────────────────────────
    "HEALTHLINE PRIVATE LIMITED":               "29AABCH3719P1ZU",
    "HEALTHLINE PVT LTD":                       "29AABCH3719P1ZU",

    # ── Associated Therapeutic Care ──────────────────────────────────
    "ASSOCIATED THERAPEUTIC CARE PVT LTD":      "27AALCA3876G1ZD",
    "ASSOCIATED THERAPEUTIC CARE PRIVATE LIMITED": "27AALCA3876G1ZD",

    # ── Shree Venkatesh Agencies ─────────────────────────────────────
    "SHREE VENKATESH AGENCIES":                 "27ACSFS1246C1Z2",

    # ── KDB Surgi-Pharma ─────────────────────────────────────────────
    "KDB SURGI PHARMA":                         "27AAIFK8419R1ZG",
    "KDB SURGIPHARMA":                          "27AAIFK8419R1ZG",
}


def _normalise(name: str) -> str:
    """
    UPPERCASE, strip diacritics (ä→a, ë→e, etc.), collapse whitespace,
    strip punctuation so minor OCR variations still match.
    e.g. "Pharmaceä Link" → "PHARMACEA LINK"
    e.g. "Kalpak Marketing Pvt. Ltd." → "KALPAK MARKETING PVT LTD"
    """
    if not name:
        return ""
    import unicodedata
    # Decompose to base + combining marks, then strip combining marks
    name = unicodedata.normalize('NFKD', name)
    name = ''.join(c for c in name if not unicodedata.combining(c))
    name = name.upper()
    # Remove common punctuation
    name = re.sub(r"[.\-,&'/\\]", " ", name)
    # Collapse multiple spaces
    name = re.sub(r"\s+", " ", name).strip()
    return name


def lookup_seller_gstin(seller_name: str) -> Optional[str]:
    """
    Return the known-correct GSTIN for *seller_name*, or None if not in the
    lookup table.

    Matching strategy (most-specific first):
      1. Exact normalised match
      2. Substring: lookup key is contained in the supplied name
      3. Substring: supplied name is contained in a lookup key
    """
    if not seller_name:
        return None

    normalised = _normalise(seller_name)

    # 1 – exact match
    if normalised in SELLER_GSTIN_MAP:
        return SELLER_GSTIN_MAP[normalised]

    # 2 – look for any key that is a substring of the extracted name
    for key, gstin in SELLER_GSTIN_MAP.items():
        if key in normalised:
            return gstin

    # 3 – look for an extracted name that is a substring of a key
    for key, gstin in SELLER_GSTIN_MAP.items():
        if normalised in key:
            return gstin

    return None


@traceable(name="apply_seller_gstin_override", tags=["override", "seller-gstin"])
def apply_seller_gstin_override(data: dict) -> dict:
    """
    If the extracted seller_name matches a known seller, replace seller_gstin
    with the hardcoded correct value.

    Logs a message so the change is visible in the server console.
    """
    seller_name = data.get("seller_name") or ""
    if not seller_name:
        return data

    known_gstin = lookup_seller_gstin(seller_name)
    if known_gstin is None:
        print(f"[SELLER GSTIN] No hardcoded entry for seller: '{seller_name}'")
        return data

    extracted_gstin = data.get("seller_gstin") or ""
    if extracted_gstin == known_gstin:
        print(f"[SELLER GSTIN] ✅ Already correct for '{seller_name}': {known_gstin}")
    else:
        print(f"[SELLER GSTIN] 🔧 Overriding seller_gstin for '{seller_name}'")
        print(f"               Extracted : '{extracted_gstin}'")
        print(f"               Hardcoded : '{known_gstin}'")
        data["seller_gstin"] = known_gstin

    return data
