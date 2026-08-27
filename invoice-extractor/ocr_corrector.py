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

    return data
