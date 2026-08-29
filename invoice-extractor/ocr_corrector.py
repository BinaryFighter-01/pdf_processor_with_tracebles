"""
OCR Corrector — Deterministic post-extraction fixes for structured fields.

Handles fields whose format is KNOWN (GSTIN, HSN, dates) so OCR character
confusion (0↔O, 1↔I, 5↔S, 8↔B, 2↔Z, 6↔G) can be resolved positionally
in code — no extra LLM call needed.

Fields handled:
  - GSTIN        : 15-char, known digit/letter positions
  - HSN/SAC codes: pure digits
  - Dates        : leap-year-aware clamping
"""

import re
import calendar
from datetime import datetime
from typing import Optional, Any


# ─────────────────────────────────────────────────────────────────────────────
# GSTIN correction
# ─────────────────────────────────────────────────────────────────────────────

# GSTIN structure (0-indexed):
#   Pos  0- 1 : State code         → DIGIT
#   Pos  2- 6 : PAN first 5 chars  → LETTER
#   Pos  7-10 : PAN next 4 chars   → DIGIT
#   Pos 11    : PAN last char      → LETTER
#   Pos 12    : Entity number      → DIGIT
#   Pos 13    : Check letter       → LETTER (usually Z)
#   Pos 14    : Check digit/letter → DIGIT or LETTER (often 'Z' → keep)
GSTIN_POSITION_TYPES = [
    'D','D',          # 0-1  state code digits
    'L','L','L','L','L',  # 2-6  PAN letters
    'D','D','D','D',  # 7-10 PAN digits
    'L',              # 11   PAN letter
    'D',              # 12   entity number digit
    'L',              # 13   check letter
    'X',              # 14   can be digit or letter — leave as-is
]

# OCR confusion maps
_DIGIT_FOR_LETTER = {'O': '0', 'I': '1', 'l': '1', 'S': '5',
                     'B': '8', 'Z': '2', 'G': '6', 'A': '4'}
_LETTER_FOR_DIGIT = {'0': 'O', '1': 'I', '5': 'S',
                     '8': 'B', '2': 'Z', '6': 'G', '4': 'A'}


def _fix_gstin_char(char: str, expected_type: str) -> str:
    """Fix a single GSTIN character given its expected position type."""
    c = char.upper()
    if expected_type == 'D':
        return _DIGIT_FOR_LETTER.get(c, c)
    elif expected_type == 'L':
        return _LETTER_FOR_DIGIT.get(c, c)
    return c  # 'X' — leave as-is


def correct_gstin(value: Any) -> Optional[str]:
    """
    Apply position-aware OCR correction to a GSTIN string.

    Returns the corrected GSTIN, or None if the input is None/empty.
    Does NOT validate the checksum — only corrects obvious OCR confusion.
    """
    if not value:
        return value

    raw = str(value).strip().replace(' ', '').upper()

    if len(raw) != 15:
        # Can't apply positional fix if length is wrong — return as-is
        return raw

    corrected = ''.join(
        _fix_gstin_char(raw[i], GSTIN_POSITION_TYPES[i])
        for i in range(15)
    )

    if corrected != raw:
        print(f"[OCR-FIX] GSTIN: '{raw}' → '{corrected}'")

    return corrected


# ─────────────────────────────────────────────────────────────────────────────
# HSN / SAC code correction
# ─────────────────────────────────────────────────────────────────────────────

_HSN_DIGIT_FIXES = str.maketrans('OIlSBZG', '0115826')


def correct_hsn(value: Any) -> Optional[str]:
    """
    Fix OCR character confusion in HSN/SAC codes (pure digit fields).
    Replaces O→0, I/l→1, S→5, B→8, Z→2, G→6.
    """
    if not value:
        return value

    raw = str(value).strip()
    corrected = raw.translate(_HSN_DIGIT_FIXES)

    if corrected != raw:
        print(f"[OCR-FIX] HSN: '{raw}' → '{corrected}'")

    return corrected


# ─────────────────────────────────────────────────────────────────────────────
# Date correction — leap-year-aware
# ─────────────────────────────────────────────────────────────────────────────

_DATE_FORMATS_IN = [
    '%d-%b-%y',   # 28-Feb-25
    '%d-%b-%Y',   # 28-Feb-2025
    '%d-%m-%Y',   # 28-02-2025
    '%d/%m/%Y',   # 28/02/2025
    '%d-%m-%y',   # 28-02-25 (Indian invoices)
    '%d/%m/%y',   # 28/02/25 (Indian invoices)
    '%Y-%m-%d',   # 2025-02-28 (ISO)
    '%m/%Y',      # 02/2025  → last day of month (pharma expiry)
    '%m/%y',      # 02/25    → last day of month (pharma expiry)
    '%b-%y',      # Feb-28   → last day of month (pharma expiry, very common)
    '%b-%Y',      # Feb-2028 → last day of month
    '%b/%y',      # Feb/28   → last day of month
    '%b/%Y',      # Feb/2028 → last day of month
]

# Formats where no day is given — use last day of month (pharma expiry convention)
_MONTH_ONLY_FORMATS = {'%m/%Y', '%m/%y', '%b-%y', '%b-%Y', '%b/%y', '%b/%Y'}

_DATE_FORMAT_OUT = '%d/%m/%Y'


def _clamp_date(day: int, month: int, year: int) -> datetime:
    """Return a datetime with day clamped to the max valid day for month/year."""
    max_day = calendar.monthrange(year, month)[1]
    return datetime(year, month, min(day, max_day))


def correct_date(value: Any) -> Optional[str]:
    """
    Parse a date string and return it in DD/MM/YYYY format.

    - Handles multiple input formats.
    - Clamps impossible days (e.g. 29-Feb in non-leap years → 28-Feb).
    - Converts 2-digit years to 20XX.
    - For MM/YY or MM/YYYY inputs, uses last day of that month (pharma expiry convention).
    - Returns original string unchanged if parsing fails completely.
    """
    if not value:
        return value

    date_str = str(value).strip()

    # Try standard formats first
    for fmt in _DATE_FORMATS_IN:
        try:
            dt = datetime.strptime(date_str, fmt)

            # For month-only formats → use last day of that month (pharma expiry convention)
            if fmt in _MONTH_ONLY_FORMATS:
                max_day = calendar.monthrange(dt.year, dt.month)[1]
                dt = dt.replace(day=max_day)

            return dt.strftime(_DATE_FORMAT_OUT)
        except ValueError:
            continue

    # Fallback: regex extraction + leap-year clamping
    # Matches DD-MM-YYYY, DD/MM/YYYY, DD-MM-YY, DD/MM/YY
    m = re.match(r'^(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})$', date_str)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 2000
        if 1 <= month <= 12:
            try:
                dt = _clamp_date(day, month, year)
                corrected = dt.strftime(_DATE_FORMAT_OUT)
                if corrected != date_str:
                    print(f"[OCR-FIX] Date clamped: '{date_str}' → '{corrected}'")
                return corrected
            except ValueError:
                pass

    # Nothing worked — return as-is, don't silently drop the value
    print(f"[OCR-FIX] Date unparseable, kept as-is: '{date_str}'")
    return date_str


# ─────────────────────────────────────────────────────────────────────────────
# Batch code: ambiguity detection and known-batch correction
# ─────────────────────────────────────────────────────────────────────────────

# Characters that are visually ambiguous in small compressed JPEG text
_BATCH_AMBIGUOUS_PAIRS = [
    ('W', 'V'),   # most common — W misread as V
    ('M', 'N'),   # second most common
    ('1', 'J'),   # digit 1 vs letter J  (J→1 when surrounded by digits)
    ('1', 'I'),   # digit 1 vs letter I
    ('0', 'O'),   # digit 0 vs letter O
    ('8', 'B'),   # rare but happens
    ('5', 'S'),   # rare
]

# Only swap these pairs when both neighbours suggest the same type
# (digit-only neighbours → must be digit; letter-only neighbours → must be letter)
# For W/V and M/N we always swap — they're both letters, context doesn't help
_CONTEXT_SENSITIVE_PAIRS = {
    ('1', 'J'), ('1', 'I'),   # digit vs letter — use neighbours
    ('0', 'O'),               # digit vs letter — use neighbours
    ('8', 'B'),               # digit vs letter — use neighbours
    ('5', 'S'),               # digit vs letter — use neighbours
}
_ALWAYS_SWAP_PAIRS = {
    ('W', 'V'), ('V', 'W'),
    ('M', 'N'), ('N', 'M'),
}
_AMBIGUOUS_CHARS = set()
for a, b in _BATCH_AMBIGUOUS_PAIRS:
    _AMBIGUOUS_CHARS.add(a.upper())
    _AMBIGUOUS_CHARS.add(b.upper())

# Per-invoice batch registry: built from the first pass, used to cross-check
# subsequent items on the same invoice. For example if batch "ABWG0002" appears
# on invoice/seller X, and later we see "ABVG0002" for the same seller, we know
# W/V confusion happened.
#
# This is populated dynamically by apply_ocr_corrections() at call time.
# It does NOT persist across invoices.


def _batch_has_ambiguous_chars(batch: str) -> list[int]:
    """Return list of positions in batch string that contain ambiguous characters."""
    return [i for i, c in enumerate(batch.upper()) if c in _AMBIGUOUS_CHARS]


def _batch_alternatives(batch: str) -> list[str]:
    """
    Generate 1-char substitution variants of a batch string using the confusion
    pair map, filtered by neighbour context for digit/letter ambiguous pairs.

    Rules:
    - W/V and M/N: always generate the swap (both are letters)
    - 1/J, 1/I, 0/O, 8/B, 5/S: only swap when both adjacent characters
      suggest the replacement type (digit neighbours → use digit form,
      letter neighbours → use letter form)

    Returns list of corrected variants (may be empty).
    """
    variants = []
    upper = batch.upper()
    n = len(upper)

    # Build pair map: char → its confusion partner
    pair_map: dict[str, str] = {}
    for a, b in _BATCH_AMBIGUOUS_PAIRS:
        pair_map[a.upper()] = b.upper()
        pair_map[b.upper()] = a.upper()

    def _is_digit(c: str) -> bool:
        return c.isdigit()

    def _is_letter(c: str) -> bool:
        return c.isalpha()

    for i, char in enumerate(upper):
        if char not in pair_map:
            continue

        partner = pair_map[char]
        pair_key_fwd = (char, partner)
        pair_key_rev = (partner, char)

        # Always-swap pairs (W↔V, M↔N)
        if pair_key_fwd in _ALWAYS_SWAP_PAIRS or pair_key_rev in _ALWAYS_SWAP_PAIRS:
            swapped = list(upper)
            swapped[i] = partner
            variants.append(''.join(swapped))
            continue

        # Context-sensitive pairs: apply neighbour rule
        # Look at left and right neighbours (skip if at boundary)
        left  = upper[i - 1] if i > 0     else None
        right = upper[i + 1] if i < n - 1 else None

        neighbours = [c for c in [left, right] if c is not None]
        n_digits  = sum(1 for c in neighbours if _is_digit(c))
        n_letters = sum(1 for c in neighbours if _is_letter(c))

        # Partner is a digit: only propose if both neighbours are digits
        if _is_digit(partner) and n_digits == len(neighbours) and len(neighbours) > 0:
            swapped = list(upper)
            swapped[i] = partner
            variants.append(''.join(swapped))

        # Partner is a letter: only propose if both neighbours are letters
        elif _is_letter(partner) and n_letters == len(neighbours) and len(neighbours) > 0:
            swapped = list(upper)
            swapped[i] = partner
            variants.append(''.join(swapped))

        # Mixed or boundary — generate the swap (conservative: let registry decide)
        else:
            swapped = list(upper)
            swapped[i] = partner
            variants.append(''.join(swapped))

    return variants


def correct_batch_with_registry(batch: str, registry: set[str]) -> tuple[str, bool]:
    """
    Try to correct a batch code by checking if any 1-char swap matches a
    previously seen batch on this invoice.

    Args:
        batch    : The batch string to check (may contain OCR error).
        registry : Set of batches already confirmed on this invoice.

    Returns:
        (corrected_batch, was_corrected)

    This handles the case where ABWG0002 appears on item 3 correctly, then
    ABVG0002 appears on item 7 for the same product family. The registry
    contains ABWG0002, so when we see ABVG0002 we generate variant ABWG0002,
    find it in the registry, and correct.
    """
    if not batch or not registry:
        return batch, False

    upper = batch.upper()
    if upper in registry:
        return batch, False   # already correct, already in registry

    for variant in _batch_alternatives(upper):
        if variant in registry:
            print(f"[OCR-FIX] Batch '{batch}' corrected to '{variant}' (registry match)")
            return variant, True

    return batch, False


def flag_ambiguous_batches(items: list[dict]) -> list[dict]:
    """
    Two-pass algorithm over all items in an invoice:

    Pass 1 — Build a registry of all batch strings that contain NO ambiguous
             characters (i.e. unambiguous batches we can trust as ground truth).

    Pass 2 — For each item whose batch HAS ambiguous characters, check if any
             1-char swap matches a registry entry. If yes → correct it.
             If no registry match → mark the item with _batch_ambiguous=True
             so the reviewer knows to double-check it.

    Also detects same-batch duplicates with 1-char difference (e.g. ABWG0002
    and ABVG0002 both appear on the invoice) and corrects the second to match
    the first.
    """
    if not items:
        return items

    # ── Pass 1: build registry of unambiguous batches ────────────────────────
    clean_registry: set[str] = set()
    for item in items:
        batch = str(item.get('Batch') or '').strip().upper()
        if not batch:
            continue
        ambig = _batch_has_ambiguous_chars(batch)
        if not ambig:
            clean_registry.add(batch)

    # ── Pass 2: correct or flag ambiguous batches ─────────────────────────────
    # Also build a running registry that grows as we confirm batches,
    # so later items can benefit from corrections made to earlier ones.
    full_registry = set(clean_registry)

    for item in items:
        batch = str(item.get('Batch') or '').strip().upper()
        if not batch:
            continue

        ambig_positions = _batch_has_ambiguous_chars(batch)
        if not ambig_positions:
            # No ambiguous chars — add to registry as ground truth
            full_registry.add(batch)
            continue

        # Try to correct via registry
        corrected, was_corrected = correct_batch_with_registry(batch, full_registry)

        if was_corrected:
            item['Batch'] = corrected
            full_registry.add(corrected)
            item.pop('_batch_ambiguous', None)
        else:
            # No registry match — flag for human review
            ambig_chars = [batch[i] for i in ambig_positions]
            item['_batch_ambiguous'] = True
            item['_batch_ambiguous_chars'] = ambig_positions
            alts = _batch_alternatives(batch)
            if alts:
                item['_batch_alternatives'] = alts
            print(f"[OCR-FLAG] Batch '{batch}' has ambiguous chars {ambig_chars} "
                  f"at positions {ambig_positions} — flagged for review. "
                  f"Alternatives: {alts}")
            full_registry.add(batch)   # add as-is so subsequent items can reference it

    return items


# ─────────────────────────────────────────────────────────────────────────────
# Top-level: apply all corrections to extracted invoice data
# ─────────────────────────────────────────────────────────────────────────────

def apply_ocr_corrections(data: dict) -> dict:
    """
    Apply all deterministic OCR corrections to an extracted invoice dict.

    Corrects in-place and returns the same dict.
    Prints a log line for every correction made.
    """
    if not data or not isinstance(data, dict):
        return data

    corrections_made = 0

    # ── GSTIN fields ──────────────────────────────────────────────────────────
    for field in ('seller_gstin', 'customer_gstin'):
        original = data.get(field)
        if original:
            fixed = correct_gstin(original)
            if fixed != str(original).strip().upper():
                data[field] = fixed
                corrections_made += 1

    # ── Header dates ──────────────────────────────────────────────────────────
    for field in ('invoice_date', 'due_date', 'DC_date'):
        original = data.get(field)
        if original:
            fixed = correct_date(original)
            if fixed != original:
                data[field] = fixed
                corrections_made += 1

    # ── Items ─────────────────────────────────────────────────────────────────
    for item in data.get('items', []):
        # HSN / SAC
        original_hsn = item.get('hsn_sac')
        if original_hsn:
            fixed = correct_hsn(original_hsn)
            if fixed != original_hsn:
                item['hsn_sac'] = fixed
                corrections_made += 1

        # Expiry date
        original_exp = item.get('expiry_date')
        if original_exp:
            fixed = correct_date(original_exp)
            if fixed != original_exp:
                item['expiry_date'] = fixed
                corrections_made += 1

        # Item code — normalize slashes to hyphens, strip surrounding dots/spaces
        # e.g. "SR/01/0451" → "SR-01-0451", "DG-01-3447." → "DG-01-3447"
        original_code = item.get('item_code')
        if original_code and isinstance(original_code, str):
            fixed_code = original_code.strip().rstrip('.')
            # Replace slashes with hyphens if the code has the XX/NN/NNNN pattern
            import re as _re
            fixed_code = _re.sub(r'([A-Za-z]{2})/(\d{2})/(\d{4})', r'\1-\2-\3', fixed_code)
            # Remove spaces around hyphens
            fixed_code = _re.sub(r'\s*-\s*', '-', fixed_code)
            if fixed_code != original_code:
                item['item_code'] = fixed_code
                corrections_made += 1
                print(f"[OCR-FIX] Item code normalized: '{original_code}' → '{fixed_code}'")

    if corrections_made:
        print(f"[OCR-FIX] Total corrections applied: {corrections_made}")
    else:
        print("[OCR-FIX] No corrections needed.")

    # ── Batch ambiguity detection and cross-item correction ───────────────────
    # Run AFTER all individual item corrections so HSN/code are already clean.
    # This pass cross-references batches across all items on the invoice to
    # catch W/V, M/N, 1/I confusion that neither the model nor zoom-recheck
    # can reliably resolve from a single ambiguous character's pixels alone.
    items = data.get('items', [])
    if items:
        data['items'] = flag_ambiguous_batches(items)

    return data
