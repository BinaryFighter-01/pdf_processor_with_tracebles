"""
Comprehensive GST Enrichment for Variable Invoice Formats
Handles GST derivation for mixed invoice layouts and vendors.
"""

from typing import Dict, List, Any, Optional
from langsmith import traceable
from decimal import Decimal, ROUND_HALF_UP


def round_to_2(value: float) -> float:
    """Round to 2 decimal places using financial rounding (ROUND_HALF_UP)."""
    if value is None:
        return 0.0
    d = Decimal(str(value))
    return float(d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        return float(value)
    try:
        cleaned = str(value).replace(',', '').replace('₹', '').replace('%', '').strip()
        return float(cleaned)
    except (TypeError, ValueError):
        return None


def _pick_first_float(item: Dict[str, Any], keys: List[str]) -> Optional[float]:
    for key in keys:
        value = _to_float(item.get(key))
        if value is not None:
            return value
    return None


def _derive_item_base(item: Dict[str, Any]) -> Optional[float]:
    explicit_taxable = _pick_first_float(item, ['taxable_value', 'Value'])
    if explicit_taxable is not None:
        return explicit_taxable

    quantity = _to_float(item.get('quantity'))
    unit_price = _pick_first_float(item, ['unit_price', 'total_price'])
    if quantity is not None and unit_price is not None:
        return round_to_2(quantity * unit_price)

    return _pick_first_float(item, ['total_price'])


def _determine_item_rate(item: Dict[str, Any]) -> Optional[float]:
    rate = _pick_first_float(item, ['Gst%', 'gst_percent', 'total_gst_rate'])
    if rate is not None:
        return rate

    cgst_rate = _to_float(item.get('cgst_rate'))
    sgst_rate = _to_float(item.get('sgst_rate'))
    igst_rate = _to_float(item.get('igst_rate'))

    if cgst_rate is not None and sgst_rate is not None:
        return round_to_2(cgst_rate + sgst_rate)
    if igst_rate is not None:
        return igst_rate
    return None


def _allocate_taxable_totals(items: List[Dict[str, Any]], invoice_taxable_total: Optional[float]) -> List[Optional[float]]:
    raw_bases = [_derive_item_base(item) for item in items]
    if invoice_taxable_total is None or invoice_taxable_total <= 0:
        return raw_bases

    numeric_bases = [base for base in raw_bases if base is not None and base > 0]
    if not numeric_bases:
        return raw_bases

    total_raw = sum(numeric_bases)
    if total_raw <= 0:
        return raw_bases

    if abs(total_raw - invoice_taxable_total) <= 0.02:
        return [round_to_2(base) if base is not None else None for base in raw_bases]

    allocated = []
    for base in raw_bases:
        if base is None or base <= 0:
            allocated.append(None)
            continue
        allocated.append(round_to_2(invoice_taxable_total * (base / total_raw)))
    return allocated


def enrich_item_gst(item: Dict[str, Any], is_intra_state: bool = True) -> Dict[str, Any]:
    """
    Enrich item-level GST fields.

    PRIORITY RULE:
    1. If printed cgst_amount / sgst_amount / igst_amount exist → KEEP THEM EXACTLY.
       Never replace printed values with recalculated ones.
       Only fill GST_AMT if it is missing (sum of components).
    2. Ensure taxable_value is present (for consistency checks) — use the
       item's own taxable_value if available; never recalculate from discount.
    3. If component amounts are absent → calculate from taxable_value × rate.
    4. If taxable_value is also absent → derive from Value - Discount, then calculate.
    """

    cgst_amt_existing  = _to_float(item.get('cgst_amount'))
    sgst_amt_existing  = _to_float(item.get('sgst_amount'))
    igst_amt_existing  = _to_float(item.get('igst_amount'))
    cgst_rate_existing = _to_float(item.get('cgst_rate'))
    sgst_rate_existing = _to_float(item.get('sgst_rate'))
    igst_rate_existing = _to_float(item.get('igst_rate'))
    gst_percent        = _determine_item_rate(item)

    # ── Case 1: Printed component amounts exist → KEEP THEM ──────────────
    has_printed_components = (
        cgst_amt_existing is not None or
        sgst_amt_existing is not None or
        igst_amt_existing is not None
    )

    if has_printed_components:
        # Fill GST_AMT if missing
        if _to_float(item.get('GST_AMT')) is None:
            item['GST_AMT'] = round_to_2(
                (cgst_amt_existing or 0) +
                (sgst_amt_existing or 0) +
                (igst_amt_existing or 0)
            )
        # Ensure taxable_value is present using the item's own printed value.
        # DO NOT derive from Value-Discount here — that produces wrong numbers
        # when the invoice shows a post-discount taxable directly.
        if item.get('taxable_value') is None:
            # Try the existing fields in priority order
            tv = _to_float(item.get('taxable_value')) or _to_float(item.get('Value'))
            if tv:
                item['taxable_value'] = tv
        item['_gst_source'] = 'invoice'
        return item

    # ── Case 2 / 3: No printed components — calculate ────────────────────
    taxable_value = _to_float(item.get('taxable_value'))

    if taxable_value is None or taxable_value <= 0:
        base_value   = _derive_item_base(item)
        discount_pct = _to_float(item.get('Discount'))
        discount_type = str(item.get('Discount_type') or '').lower()
        if base_value and base_value > 0:
            # Only apply discount if it's a percentage type
            if discount_pct and discount_pct > 0 and discount_type in ('percent', 'percentage', ''):
                disc_amt      = round_to_2(base_value * discount_pct / 100)
                taxable_value = round_to_2(base_value - disc_amt)
            else:
                taxable_value = base_value
            item['taxable_value'] = taxable_value
        else:
            item['_gst_source'] = 'not_calculated'
            return item

    if gst_percent is None or gst_percent <= 0:
        item['_gst_source'] = 'not_calculated'
        return item

    gst_amt = round_to_2(taxable_value * gst_percent / 100)
    item['GST_AMT'] = gst_amt

    if is_intra_state:
        cgst_rate = cgst_rate_existing if cgst_rate_existing is not None else round_to_2(gst_percent / 2)
        sgst_rate = sgst_rate_existing if sgst_rate_existing is not None else round_to_2(gst_percent / 2)
        item['cgst_rate']   = cgst_rate
        item['sgst_rate']   = sgst_rate
        item['cgst_amount'] = round_to_2(taxable_value * cgst_rate / 100)
        item['sgst_amount'] = round_to_2(taxable_value * sgst_rate / 100)
        item['igst_rate']   = None
        item['igst_amount'] = None
    else:
        igst_rate = igst_rate_existing if igst_rate_existing is not None else gst_percent
        item['igst_rate']   = igst_rate
        item['igst_amount'] = gst_amt
        item['cgst_rate']   = None
        item['cgst_amount'] = None
        item['sgst_rate']   = None
        item['sgst_amount'] = None

    item['_gst_source'] = 'calculated_from_taxable'
    return item


def enrich_totals_gst(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrich invoice-level totals GST fields.
    
    Fixes common issues:
    - total_gst_rate = 10 when it should be 5 (confusion between total and component)
    - CGST/SGST rates should be HALF of total GST rate
    
    Args:
        data: Invoice data dictionary
    
    Returns:
        Enriched data dictionary
    """
    total_gst_rate = data.get('total_gst_rate', 0) or 0
    total_cgst_rate = data.get('total_cgst_rate', 0) or 0
    total_sgst_rate = data.get('total_sgst_rate', 0) or 0
    total_igst_rate = data.get('total_igst_rate', 0) or 0
    
    # Detect and fix common error: total_gst_rate = 10, cgst = 5, sgst = 5
    # This is wrong: total should be 5, cgst should be 2.5, sgst should be 2.5
    if total_cgst_rate > 0 and total_sgst_rate > 0:
        # Intra-state transaction
        if total_cgst_rate + total_sgst_rate != total_gst_rate:
            # Rates don't add up - likely cgst and sgst are correctly half each
            # So total_gst_rate should be cgst + sgst
            corrected_total = total_cgst_rate + total_sgst_rate
            if corrected_total != total_gst_rate:
                print(f"⚠️  Correcting total_gst_rate: {total_gst_rate} → {corrected_total}")
                print(f"   CGST: {total_cgst_rate}%, SGST: {total_sgst_rate}%")
                data['total_gst_rate'] = corrected_total
                data['_gst_rate_corrected'] = True
    
    elif total_igst_rate > 0:
        # Inter-state transaction
        if total_gst_rate != total_igst_rate:
            print(f"⚠️  Correcting total_gst_rate: {total_gst_rate} → {total_igst_rate}")
            data['total_gst_rate'] = total_igst_rate
            data['_gst_rate_corrected'] = True
    
    return data


def determine_transaction_type(data: Dict[str, Any]) -> str:
    """
    Determine if transaction is intra-state or inter-state.

    Logic:
    1. Check for explicit IGST evidence → inter-state.
    2. Check for explicit CGST/SGST evidence → intra-state.
    3. Fallback: intra-state when the invoice does not state otherwise.
    
    Returns:
        'intra-state' or 'inter-state'
    """
    # Check totals
    if (_to_float(data.get('total_igst_amount')) or 0) > 0:
        return 'inter-state'
    if (_to_float(data.get('total_cgst_amount')) or 0) > 0 or (_to_float(data.get('total_sgst_amount')) or 0) > 0:
        return 'intra-state'
    
    # Check item-level evidence
    items = data.get('items', [])
    if items:
        for first_item in items:
            if (_to_float(first_item.get('igst_amount')) or 0) > 0 or (_to_float(first_item.get('igst_rate')) or 0) > 0:
                return 'inter-state'
            if (_to_float(first_item.get('cgst_amount')) or 0) > 0 or (_to_float(first_item.get('sgst_amount')) or 0) > 0:
                return 'intra-state'
    
    # Default to intra-state
    return 'intra-state'


@traceable(name="enrich_gst_comprehensive", tags=["gst", "enrichment"])
def enrich_gst_comprehensive(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Comprehensive GST enrichment for all invoice types.
    
    Process:
    1. Determine transaction type (intra/inter state)
    2. Fix totals GST rates if needed
    3. Enrich each item's GST fields
    4. Add transparency markers
    
    Args:
        data: Raw extracted invoice data
    
    Returns:
        Enriched data with calculated GST fields
    """
    print("\n" + "="*80)
    print("GST ENRICHMENT")
    print("="*80)
    
    # Step 1: Determine transaction type
    transaction_type = determine_transaction_type(data)
    is_intra_state = (transaction_type == 'intra-state')
    
    print(f"Transaction type: {transaction_type}")
    print(f"GST split: {'CGST + SGST' if is_intra_state else 'IGST'}")
    
    # Step 2: Fix totals GST rates
    data = enrich_totals_gst(data)

    # Step 3: Allocate taxable values proportionally when only invoice-level
    # totals are available.
    items = data.get('items', [])
    allocated_taxables = _allocate_taxable_totals(items, _to_float(data.get('taxable_amount')))

    # Step 4: Enrich each item
    if items:
        print(f"\nEnriching {len(items)} items...")
        for idx, item in enumerate(items, 1):
            if idx - 1 < len(allocated_taxables):
                allocated_taxable = allocated_taxables[idx - 1]
                if allocated_taxable is not None:
                    if item.get('taxable_value') is None:
                        item['taxable_value'] = allocated_taxable
                    if item.get('Value') is None:
                        item['Value'] = allocated_taxable
            item = enrich_item_gst(item, is_intra_state)
            items[idx - 1] = item
            
            # Log enrichment source
            source = item.get('_gst_source', 'unknown')
            if source != 'invoice':
                gst_amt = item.get('GST_AMT', 0) or 0
                print(f"  Item {idx}: {source} (GST: ₹{gst_amt:.2f})")
    
    print("="*80 + "\n")
    
    return data
