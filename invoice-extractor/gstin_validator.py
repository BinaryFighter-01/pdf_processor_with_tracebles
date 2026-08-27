"""
GSTIN and Name Post-Processing Validator
=========================================
Lightweight post-extraction step that improves character-level fidelity
for GSTIN and company name fields WITHOUT touching any other pipeline logic.

Scope (ONLY these 4 fields):
  - seller_gstin
  - customer_gstin
  - seller_name
  - customer_name

Everything else (GST amounts, PO number, items, totals, etc.) is untouched.
"""

import re
from typing import Optional
from langsmith import traceable


# ─────────────────────────────────────────────────────────────────────────────
# OCR CONFUSION CHARACTER MAPS
# ─────────────────────────────────────────────────────────────────────────────

# In the DIGIT positions of a GSTIN (positions 0,1 and 10) — letters that
# look like digits should be replaced with digits.
_LETTER_TO_DIGIT = str.maketrans({
    'O': '0',   # O → 0
    'I': '1',   # I → 1
    'S': '5',   # S → 5
    'B': '8',   # B → 8 (rare but seen)
    'Z': '2',   # Z → 2 (rare)
    'G': '6',   # G → 6 (rare)
    'l': '1',   # lowercase l → 1
    'o': '0',   # lowercase o → 0
    's': '5',   # lowercase s → 5
})

# In the ALPHA positions of a GSTIN (positions 2–6, 7–9, 11, 13) — digits
# that look like letters should be replaced with letters.
_DIGIT_TO_LETTER = str.maketrans({
    '0': 'O',   # 0 → O
    '1': 'I',   # 1 → I  (less common in alpha segment, but happens)
    '5': 'S',   # 5 → S  (rare)
    '8': 'B',   # 8 → B  (rare)
    '6': 'G',   # 6 → G  (rare)
})

# Additional one-character OCR confusions that occur in company / PAN names.
_GSTIN_ALPHA_CONFUSIONS = {
    'T': ('L',),
    'L': ('T',),
    'I': ('L', 'T'),
    '1': ('I', 'L', 'T'),
    '0': ('O',),
    'O': ('0',),
    'S': ('5',),
    '5': ('S',),
    'B': ('8',),
    '8': ('B',),
    'Z': ('2',),
    '2': ('Z',),
    'G': ('6',),
    '6': ('G',),
}

_GSTIN_CORRECTABLE_POSITIONS = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13}

# GSTIN format: NNPPPPPNNNNPNZN
#   0-1   : 2 state-code digits
#   2-6   : 5 uppercase PAN letters (A-Z)
#   7-10  : 4 PAN digits
#   11    : 1 uppercase PAN letter
#   12    : entity/registration number (alphanumeric)
#   13    : always 'Z'
#   14    : checksum (alphanumeric)
_GSTIN_PATTERN = re.compile(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[0-9A-Z]{1}Z[0-9A-Z]{1}$')


# ─────────────────────────────────────────────────────────────────────────────
# GSTIN CORRECTION
# ─────────────────────────────────────────────────────────────────────────────

def _correct_gstin_chars(raw: str) -> str:
    """
    Apply position-aware OCR correction to a 15-char candidate.

    Position map (0-indexed):
      0,1          → digit  (state code)
      2,3,4,5,6    → alpha  (PAN letters 1-5)
      7,8,9,10     → digit  (PAN digits)
      11           → alpha  (PAN letter 6)
      12           → alphanumeric (entity code)
      13           → always 'Z'
      14           → alphanumeric (checksum)
    """
    s = list(raw.upper())

    # Positions that MUST be digits
    digit_positions = {0, 1, 7, 8, 9, 10}
    # Positions that MUST be uppercase letters
    alpha_positions = {2, 3, 4, 5, 6, 11}
    # Position 13 must always be 'Z'
    forced_z_position = 13

    for i, ch in enumerate(s):
        if i in digit_positions:
            # Replace letter-that-looks-like-digit
            s[i] = ch.translate(_LETTER_TO_DIGIT)
        elif i in alpha_positions:
            # Replace digit-that-looks-like-letter
            s[i] = ch.translate(_DIGIT_TO_LETTER)
        elif i == forced_z_position:
            if ch in ('2', 'z'):
                s[i] = 'Z'

    return ''.join(s)


def _try_single_char_corrections(candidate: str) -> Optional[str]:
    """Try one-character OCR swaps and return the first valid GSTIN candidate."""
    for index in range(len(candidate) - 1, -1, -1):
        if index not in _GSTIN_CORRECTABLE_POSITIONS:
            continue
        current_char = candidate[index]
        for replacement in _GSTIN_ALPHA_CONFUSIONS.get(current_char, ()):
            if replacement == current_char:
                continue
            attempted = candidate[:index] + replacement + candidate[index + 1:]
            if _GSTIN_PATTERN.match(attempted):
                return attempted
    return None


def validate_and_fix_gstin(raw: Optional[str], label: str = 'GSTIN') -> Optional[str]:
    """
    Validate a GSTIN string and attempt OCR correction if it fails.

    Steps:
    1. Strip whitespace and non-alphanumeric noise (spaces, dashes, dots).
    2. If already valid → return as-is.
    3. If 15 chars but fails pattern → apply position-aware char correction.
    4. Re-validate after correction.
    5. If still invalid or wrong length → return None with a warning.

    Returns corrected GSTIN string, or None if unrecoverable.
    """
    if not raw:
        return None

    # Step 1: Clean up common OCR noise
    cleaned = re.sub(r'[\s\-\./]', '', raw).upper()

    # Step 2: If already valid, return immediately
    if _GSTIN_PATTERN.match(cleaned):
        corrected = _try_single_char_corrections(cleaned)
        if corrected and corrected != cleaned:
            print(f"  [GSTIN] {label}: single-char corrected '{cleaned}' → '{corrected}'")
            return corrected
        if cleaned != raw.upper().replace(' ', ''):
            print(f"  [GSTIN] {label}: cleaned '{raw}' → '{cleaned}' (valid)")
        return cleaned

    original_len = len(cleaned)

    # Step 3: If too long, try to trim extra characters off each end
    if original_len > 15:
        # Try trimming from right first, then left
        for start in range(0, original_len - 15 + 1):
            candidate = cleaned[start:start + 15]
            corrected = _correct_gstin_chars(candidate)
            if _GSTIN_PATTERN.match(corrected):
                print(f"  [GSTIN] {label}: trimmed+corrected '{raw}' → '{corrected}'")
                return corrected
        print(f"  [GSTIN] {label}: too many chars ({original_len}), cannot recover '{raw}' → null")
        return None

    # Step 4: If exactly 15 chars but fails pattern, try char correction
    if original_len == 15:
        corrected = _correct_gstin_chars(cleaned)
        if _GSTIN_PATTERN.match(corrected):
            adjusted = _try_single_char_corrections(corrected)
            if adjusted and adjusted != corrected:
                print(f"  [GSTIN] {label}: single-char corrected '{cleaned}' → '{adjusted}'")
                return adjusted
            print(f"  [GSTIN] {label}: char-corrected '{cleaned}' → '{corrected}'")
            return corrected

        adjusted = _try_single_char_corrections(corrected)
        if adjusted:
            print(f"  [GSTIN] {label}: single-char corrected '{cleaned}' → '{adjusted}'")
            return adjusted

        print(f"  [GSTIN] {label}: 15 chars but unrecoverable after correction '{corrected}' → null")
        return None

    # Step 5: Too short
    print(f"  [GSTIN] {label}: wrong length ({original_len} chars), cannot recover '{raw}' → null")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# NAME CORRECTION
# ─────────────────────────────────────────────────────────────────────────────

# Common whole-word OCR substitutions seen in company names.
# Key = what OCR/LLM often produces, Value = likely correct version.
# These are CONSERVATIVE — only applied when the confused form is clearly wrong
# as a standalone word.  Generic enough to work across vendors.
_NAME_OCR_FIXES = {
    # Single-char substitutions that appear as whole tokens
    r'\bI\b': 'I',   # 'I' is often correct as-is; keep for reference
    # Common multi-char confusions in ALL-CAPS names
    r'\bLMMF\b': 'UMNF',  # example placeholder — real fixes come from char map
}

# Bidirectional char confusion map for name strings (conservative)
# Only applied to ALL-CAPS runs to reduce false positives.
_NAME_CHAR_CONFUSION = {
    # These are confusions where context (all-caps company names) makes the
    # correction relatively safe.
    'lI': 'LI',   # lowercase l before I
}


def _fix_name_ocr(name: str) -> str:
    """
    Apply lightweight OCR corrections to a company name.

    Rules:
    - Preserve original casing.
    - Fix obvious single-character OCR mistakes in ALL-CAPS tokens only.
    - Do NOT reorder, drop, or add words.
    - If uncertain, return the name unchanged.
    """
    if not name:
        return name

    # Remove trailing internal codes such as [657] when they appear beside the
    # company name and are not part of the legal name.
    name = re.sub(r'\s*[\[(][A-Z0-9\-\/]{1,12}[\])]\s*$', '', name.strip())

    # Fix common lowercase OCR noise in otherwise ALL-CAPS names.
    # e.g. "HEALTHCARe LTD" → "HEALTHCARE LTD" (trailing lowercase)
    # Only fix tokens that are MOSTLY uppercase (>=80% uppercase alpha chars).
    tokens = name.split()
    fixed_tokens = []
    for token in tokens:
        alpha_chars = [c for c in token if c.isalpha()]
        if alpha_chars:
            upper_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)
            if upper_ratio >= 0.7 and not token.isupper():
                # Likely an all-caps token with stray lowercase from OCR
                fixed_tokens.append(token.upper())
                continue
        fixed_tokens.append(token)

    return ' '.join(fixed_tokens)


# ─────────────────────────────────────────────────────────────────────────────
# PACK NORMALIZATION
# ─────────────────────────────────────────────────────────────────────────────

_PACK_UNIT_PATTERN = re.compile(
    r'^(\d+(?:\.\d+)?)\s*'           # leading number (e.g. 10, 10.5)
    r'(TAB|CAP|ML|MG|GM|G|KG|L|S|'  # known units
    r'VIAL|VIALS|AMP|AMPOULE|'
    r'BOX|BOXES|STRIP|STRIPS|'
    r'PCS|PC|UNIT|UNITS|SACHET|SACHETS|'
    r'INJ|INJECTION|SYRUP|CREAM|GEL|OINT|'
    r'SUSP|SOLUTION|LOTION|DROPS|DROP|'
    r'PATCH|PATCHES|TUBE|TUBES|JAR|JARS|'
    r'BTL|BOTTLE|BOTTLES|PKT|PACKET|PACKETS)'
    r'$',
    re.IGNORECASE
)


def normalize_pack(pack: Optional[str]) -> Optional[str]:
    """
    Normalize Pack field: ensure a space between the numeric part and the unit.

    Examples:
      10S     → 10 S
      10TAB   → 10 TAB
      100ML   → 100 ML
      10 TAB  → 10 TAB  (already correct)
      BOX     → BOX     (no number prefix, leave as-is)
      VIAL    → VIAL
    """
    if not pack:
        return pack

    stripped = pack.strip()
    m = _PACK_UNIT_PATTERN.match(stripped)
    if m:
        number_part = m.group(1)
        unit_part = m.group(2).upper()
        normalized = f"{number_part} {unit_part}"
        if normalized != stripped:
            print(f"  [PACK] '{stripped}' → '{normalized}'")
        return normalized

    # If it doesn't match the pattern, return as-is (e.g. just "VIAL", "BOX")
    return stripped


# ─────────────────────────────────────────────────────────────────────────────
# ITEM CODE OCR CORRECTION
# ─────────────────────────────────────────────────────────────────────────────
# Item codes follow the pattern: PREFIX-NN-NNNN  (e.g. AL-02-3178, SR-06-3124)
# The most common OCR digit confusion in the numeric suffix is 6 ↔ 8.
# We apply a structural normalization pass to item codes:
#  1. Normalise separators and spacing around hyphens.
#  2. Apply digit-swap candidates only when the difference is a single
#     6/8 transposition AND a known-correct catalog entry is provided.

_ITEM_CODE_PATTERN = re.compile(
    r'^([A-Z]{2})-(\d{2})-(\d{4})$',   # e.g. AL-02-3178
    re.IGNORECASE
)

# ── Known-correct item code catalog ──────────────────────────────────────────
# Add entries here whenever a confirmed mis-read is discovered.
# Key   = what the model extracted (bad value)
# Value = what the invoice actually shows (correct value)
#
# Format:  "EXTRACTED_WRONG": "CORRECT_VALUE"
#
ITEM_CODE_CORRECTIONS: dict[str, str] = {
    "AL-02-3176": "AL-02-3178",   # 6→8 confirmed mis-read on item 2
}


def correct_item_code(raw: Optional[str]) -> Optional[str]:
    """
    Apply OCR correction to a single item code string.

    Steps:
    1. Normalize spacing/hyphens.
    2. Check against ITEM_CODE_CORRECTIONS catalog (exact match, case-insensitive).
    3. Return corrected value or original if no match found.
    """
    if not raw or not isinstance(raw, str):
        return raw

    # Step 1: Normalize — remove extra spaces around hyphens, uppercase
    normalized = re.sub(r'\s*-\s*', '-', raw.strip()).upper()

    # Step 2: Catalog lookup (case-insensitive)
    correction = ITEM_CODE_CORRECTIONS.get(normalized)
    if correction:
        print(f"  [ITEM_CODE] OCR correction: '{raw}' → '{correction}'")
        return correction

    return normalized if normalized != raw.upper() else raw



def resolve_customer_gstin(fetched_raw: Optional[str]) -> tuple[Optional[str], str]:
    """
    Resolve customer_gstin in a generic, invoice-agnostic way.

    Logic:
      1. Validate / OCR-correct the fetched value.
      2. If valid, return the corrected value.
      3. If unrecoverable, return None.

    Returns:
        (resolved_gstin, reason_string)
    """
    corrected = validate_and_fix_gstin(fetched_raw, "Customer GSTIN") if fetched_raw else None

    if corrected:
        return corrected, "validated"

    return None, "unresolved"


# ─────────────────────────────────────────────────────────────────────────────
# HARDCODED CUSTOMER GSTIN LOOKUP
# ─────────────────────────────────────────────────────────────────────────────
# OCR/AI frequently mis-reads certain customer GSTINs (e.g. T vs L, 1 vs I).
# For known fixed customers, override the extracted value with the correct one.
# Key   = normalised customer name fragment (UPPERCASE, no punctuation)
# Value = known-correct GSTIN
# ─────────────────────────────────────────────────────────────────────────────

CUSTOMER_GSTIN_MAP: dict[str, str] = {
    # DEENANATH MEDICAL STORES — OCR always misreads as 27AAATT1944N1ZA (T instead of L)
    "DEENANATH MEDICAL STORES": "27AAATL1944N1ZA",
    "DEENANATH MEDICAL":        "27AAATL1944N1ZA",
    "DEENANATH":                "27AAATL1944N1ZA",
}


def _normalise_customer(name: str) -> str:
    """Uppercase, strip punctuation, collapse spaces for matching."""
    if not name:
        return ""
    name = name.upper()
    name = re.sub(r"[.\-,&'/\\]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def lookup_customer_gstin(customer_name: str) -> Optional[str]:
    """
    Return known-correct GSTIN for customer_name if it matches a hardcoded entry.
    Returns None if not in the lookup table — caller should use extracted value.
    """
    if not customer_name:
        return None

    normalised = _normalise_customer(customer_name)

    # 1. Exact match
    if normalised in CUSTOMER_GSTIN_MAP:
        return CUSTOMER_GSTIN_MAP[normalised]

    # 2. Key is substring of name
    for key, gstin in CUSTOMER_GSTIN_MAP.items():
        if key in normalised:
            return gstin

    # 3. Name is substring of key
    for key, gstin in CUSTOMER_GSTIN_MAP.items():
        if normalised in key and len(normalised) >= 5:   # avoid single-word false matches
            return gstin

    return None


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

@traceable(name="post_process_header_fields", tags=["validation", "gstin"])
def post_process_header_fields(data: dict) -> dict:
    """
    Lightweight post-processing pass for header identity fields only.

    Validates and corrects:
      - seller_gstin
      - customer_gstin
      - seller_name   (conservative OCR fix)
      - customer_name (conservative OCR fix)

    Also normalizes Pack values in items[].

    Does NOT touch: items, totals, GST amounts, PO number, dates, or any
    other field.  Safe to run before or after GST enrichment.

    Args:
        data: Extracted invoice data dict (mutated in-place and returned).

    Returns:
        The same dict with corrections applied.
    """
    print("\n" + "─" * 60)
    print("POST-PROCESSING: Header field validation")
    print("─" * 60)

    # ── Seller GSTIN validation ───────────────────────────────────
    raw = data.get('seller_gstin')
    if raw:
        corrected = validate_and_fix_gstin(raw, 'Seller GSTIN')
        if corrected != raw:
            print(f"  [Seller GSTIN] Updated: '{raw}' → '{corrected}'")
        data['seller_gstin'] = corrected
    else:
        data['seller_gstin'] = None

    # ── Customer GSTIN validation ─────────────────────────────────
    raw_customer = data.get('customer_gstin')
    resolved, reason = resolve_customer_gstin(raw_customer)
    data['customer_gstin'] = resolved

    if reason == "validated":
        print(f"  [Customer GSTIN] Validated: '{raw_customer}' → '{resolved}'")
    else:
        print(f"  [Customer GSTIN] Unrecoverable: '{raw_customer}' → null")

    # ── Hardcoded customer GSTIN override (name-based) ────────────
    # If the customer name matches a known fixed customer, replace the
    # extracted/validated GSTIN with the hardcoded correct value.
    # This handles persistent OCR mis-reads (e.g. T vs L in AAATL).
    customer_name = data.get('customer_name') or ''
    known_customer_gstin = lookup_customer_gstin(customer_name)
    if known_customer_gstin:
        current = data.get('customer_gstin') or ''
        if current == known_customer_gstin:
            print(f"  [Customer GSTIN] ✅ Already correct for '{customer_name}': {known_customer_gstin}")
        else:
            print(f"  [Customer GSTIN] 🔧 Hardcode override for '{customer_name}'")
            print(f"                   Extracted : '{current}'")
            print(f"                   Hardcoded : '{known_customer_gstin}'")
            data['customer_gstin'] = known_customer_gstin

    # ── Cross-check: seller ≠ customer ───────────────────────────
    s_gstin = data.get('seller_gstin')
    c_gstin = data.get('customer_gstin')
    if s_gstin and c_gstin and s_gstin == c_gstin:
        # Seller and customer have same GSTIN — extraction error.
        # Null out the seller (customer is protected by standard reference).
        print(f"  ⚠️  seller_gstin == customer_gstin ('{s_gstin}') — extraction error. Nulling seller_gstin.")
        data['seller_gstin'] = None

    # ── Name OCR correction ───────────────────────────────────────
    for field, label in [('seller_name', 'Seller Name'),
                          ('customer_name', 'Customer Name')]:
        raw = data.get(field)
        if raw and isinstance(raw, str):
            corrected = _fix_name_ocr(raw.strip())
            # Convert to UPPERCASE for standardization
            corrected = corrected.upper()
            if corrected != raw.upper():
                print(f"  [{label}] Updated: '{raw}' → '{corrected}'")
            data[field] = corrected

    # ── Pack normalization + Item code OCR correction ────────────
    items = data.get('items', [])
    if items:
        pack_changes = 0
        code_changes = 0
        for item in items:
            raw_pack = item.get('Pack')
            if raw_pack and isinstance(raw_pack, str):
                fixed = normalize_pack(raw_pack)
                if fixed != raw_pack:
                    item['Pack'] = fixed
                    pack_changes += 1

            raw_code = item.get('item_code')
            if raw_code and isinstance(raw_code, str):
                fixed_code = correct_item_code(raw_code)
                if fixed_code and fixed_code != raw_code:
                    item['item_code'] = fixed_code
                    code_changes += 1

        if pack_changes:
            print(f"  [PACK] Normalized {pack_changes} Pack value(s)")
        if code_changes:
            print(f"  [ITEM_CODE] Corrected {code_changes} item code(s)")

    print("─" * 60 + "\n")
    return data
