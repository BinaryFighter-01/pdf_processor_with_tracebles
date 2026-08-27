"""
Consistency Checker — Math-based validation of extracted invoice data.

Checks that extracted numbers are internally consistent:
  - Per-item  : GST_AMT ≈ Value × Gst% / 100
  - Per-item  : cgst_amount + sgst_amount + igst_amount ≈ GST_AMT
  - Invoice   : sum(item GST_AMTs) ≈ total_gst_amount
  - Invoice   : sum(item Values)   ≈ invoice_amount − total_gst_amount (rough check)

Does NOT fix values — only adds a '_needs_review' flag and a
'_review_reasons' list to suspicious items/invoice so the caller
(or a human) knows exactly which rows to double-check.

Zero extra API calls. Pure Python maths.
"""

from typing import Any, Dict, List, Optional, Tuple
from decimal import Decimal, ROUND_HALF_UP


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _f(value: Any) -> Optional[float]:
    """Safe float conversion; returns None on failure."""
    if value is None or value == '':
        return None
    try:
        return float(str(value).replace(',', '').replace('₹', '').strip())
    except (ValueError, TypeError):
        return None


def _decimal_round(value: float, decimals: int = 2) -> float:
    """Round using Decimal with ROUND_HALF_UP (financial rounding)."""
    d = Decimal(str(value))
    quantizer = Decimal('0.01') if decimals == 2 else Decimal(10) ** -decimals
    return float(d.quantize(quantizer, rounding=ROUND_HALF_UP))


def _close(a: float, b: float, tol: float = 1.0) -> bool:
    """True if |a - b| <= tol."""
    return abs(a - b) <= tol


# ─────────────────────────────────────────────────────────────────────────────
# Per-item checks
# ─────────────────────────────────────────────────────────────────────────────

def _check_item(item: Dict[str, Any], idx: int) -> List[str]:
    """
    Return a list of reason strings for a suspicious item.
    Empty list means the item passes all checks.
    """
    reasons = []

    gst_amt   = _f(item.get('GST_AMT'))
    gst_pct   = _f(item.get('Gst%'))
    value     = _f(item.get('Value')) or _f(item.get('taxable_value')) or _f(item.get('total_price'))
    cgst_amt  = _f(item.get('cgst_amount'))
    sgst_amt  = _f(item.get('sgst_amount'))
    igst_amt  = _f(item.get('igst_amount'))
    cgst_rate = _f(item.get('cgst_rate'))
    sgst_rate = _f(item.get('sgst_rate'))
    qty       = _f(item.get('quantity')) if not isinstance(item.get('quantity'), str) else None
    unit_price = _f(item.get('unit_price'))
    total_price = _f(item.get('total_price'))

    # Check 1: GST_AMT vs taxable_value × Gst% (DISCOUNT-AWARE)
    # CRITICAL: GST is calculated on taxable_value (after discount), NOT on Value (before discount)
    if gst_amt is not None and value is not None and gst_pct is not None:
        # Check if item has a discount percentage
        discount_pct = _f(item.get('Discount'))
        if discount_pct is not None and discount_pct > 0:
            # Apply discount: taxable_value = Value × (1 - Discount/100)
            taxable_value = _decimal_round(value * (1 - discount_pct / 100))
        else:
            # No discount, taxable_value = Value
            taxable_value = value
            
        expected_gst = _decimal_round(taxable_value * gst_pct / 100)
        if not _close(gst_amt, expected_gst, tol=1.0):
            reasons.append(
                f"GST_AMT mismatch: extracted={gst_amt}, "
                f"expected={expected_gst} (taxable_value={taxable_value} × Gst%={gst_pct}/100, "
                f"Value={value}, Discount={discount_pct}%)"
            )

    # Check 2: CGST + SGST + IGST ≈ GST_AMT
    if gst_amt is not None:
        components = []
        if cgst_amt is not None:
            components.append(cgst_amt)
        if sgst_amt is not None:
            components.append(sgst_amt)
        if igst_amt is not None:
            components.append(igst_amt)
        if components:
            component_sum = round(sum(components), 2)
            if not _close(gst_amt, component_sum, tol=0.5):
                reasons.append(
                    f"GST component sum mismatch: CGST({cgst_amt})+SGST({sgst_amt})"
                    f"+IGST({igst_amt})={component_sum} ≠ GST_AMT={gst_amt}"
                )

    # Check 3: CGST rate = SGST rate (intra-state rule)
    if cgst_rate is not None and sgst_rate is not None:
        if not _close(cgst_rate, sgst_rate, tol=0.01):
            reasons.append(
                f"CGST rate ({cgst_rate}%) ≠ SGST rate ({sgst_rate}%) — "
                f"intra-state split should be equal"
            )

    # Check 4: Gst% = CGST rate + SGST rate (when both exist)
    if gst_pct is not None and cgst_rate is not None and sgst_rate is not None:
        expected_rate = round(cgst_rate + sgst_rate, 2)
        if not _close(gst_pct, expected_rate, tol=0.01):
            reasons.append(
                f"Gst% ({gst_pct}) ≠ CGST({cgst_rate})+SGST({sgst_rate})={expected_rate}"
            )

    # Check 5: qty × unit_price ≈ total_price (when all three present)
    if qty is not None and unit_price is not None and total_price is not None:
        expected_total = round(qty * unit_price, 2)
        # Allow 2% tolerance for rounding on large quantities
        tol = max(1.0, round(expected_total * 0.02, 2))
        if not _close(total_price, expected_total, tol=tol):
            reasons.append(
                f"qty×unit_price mismatch: {qty}×{unit_price}={expected_total} "
                f"≠ total_price={total_price} (tol={tol})"
            )

    return reasons


# ─────────────────────────────────────────────────────────────────────────────
# Invoice-level checks
# ─────────────────────────────────────────────────────────────────────────────

def _check_invoice_totals(data: Dict[str, Any]) -> List[str]:
    """Return invoice-level inconsistency reasons."""
    reasons = []

    items = data.get('items', [])
    total_gst    = _f(data.get('total_gst_amount'))
    total_cgst   = _f(data.get('total_cgst_amount'))
    total_sgst   = _f(data.get('total_sgst_amount'))
    total_igst   = _f(data.get('total_igst_amount'))
    invoice_amt  = _f(data.get('invoice_amount'))

    # Check 1: sum of item GST_AMTs ≈ total_gst_amount
    if total_gst is not None and items:
        item_gst_values = [_f(i.get('GST_AMT')) for i in items]
        if all(v is not None for v in item_gst_values):
            item_gst_sum = round(sum(item_gst_values), 2)
            if not _close(item_gst_sum, total_gst, tol=2.0):
                reasons.append(
                    f"Invoice total_gst_amount={total_gst} ≠ "
                    f"sum of item GST_AMTs={item_gst_sum} "
                    f"(diff={round(abs(item_gst_sum - total_gst), 2)})"
                )

    # Check 2: total_cgst + total_sgst + total_igst ≈ total_gst_amount
    if total_gst is not None:
        components = []
        if total_cgst is not None:
            components.append(total_cgst)
        if total_sgst is not None:
            components.append(total_sgst)
        if total_igst is not None:
            components.append(total_igst)
        if components:
            component_sum = round(sum(components), 2)
            if not _close(total_gst, component_sum, tol=1.0):
                reasons.append(
                    f"total_gst_amount={total_gst} ≠ "
                    f"CGST({total_cgst})+SGST({total_sgst})+IGST({total_igst})={component_sum}"
                )

    # Check 3: CRITICAL - Discount-aware invoice total validation
    # Formula: Gross - Discount + GST = Grand Total
    # NOT: Gross + GST = Grand Total (this ignores discount!)
    if invoice_amt is not None and total_gst is not None and items:
        # Sum gross item Values (before discount)
        item_values = [_f(i.get('Value')) for i in items]
        if all(v is not None for v in item_values):
            gross_sum = round(sum(item_values), 2)
            
            # Get invoice-level discount OR calculate from items
            total_discount = _f(data.get('total_discount_amount'))
            if total_discount is None or total_discount == 0:
                # Calculate from item-level discounts
                item_discounts = []
                for item in items:
                    val = _f(item.get('Value'))
                    disc_pct = _f(item.get('Discount'))
                    if val and disc_pct and disc_pct > 0:
                        item_discounts.append(_decimal_round(val * disc_pct / 100))
                if item_discounts:
                    total_discount = round(sum(item_discounts), 2)
                else:
                    total_discount = 0.0
            
            # Calculate expected: Gross - Discount + GST
            taxable_sum = round(gross_sum - total_discount, 2)
            expected_invoice = round(taxable_sum + total_gst, 2)
            
            # 2% tolerance — invoices sometimes have rounding, extra charges etc.
            tol = max(5.0, round(invoice_amt * 0.02, 2))
            if not _close(invoice_amt, expected_invoice, tol=tol):
                reasons.append(
                    f"invoice_amount={invoice_amt} ≠ "
                    f"(Gross={gross_sum} - Discount={total_discount} + GST={total_gst})={expected_invoice} "
                    f"(diff={round(abs(invoice_amt - expected_invoice), 2)}, tol={tol})"
                )

    return reasons


# ─────────────────────────────────────────────────────────────────────────────
# Top-level: run all checks and annotate data
# ─────────────────────────────────────────────────────────────────────────────

def run_consistency_checks(data: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Run all consistency checks on extracted invoice data.

    Annotates:
      - Suspicious items get  '_needs_review': True, '_review_reasons': [...]
      - Clean items get       '_needs_review': False
      - Invoice-level issues  stored in data['_invoice_review_reasons']

    Returns:
      (annotated_data, summary_dict)

    The summary_dict has:
      {
        'items_flagged': int,
        'items_clean': int,
        'invoice_issues': [...],
        'has_issues': bool
      }
    """
    if not data or not isinstance(data, dict):
        return data, {'items_flagged': 0, 'items_clean': 0,
                      'invoice_issues': [], 'has_issues': False}

    print("\n" + "=" * 70)
    print("CONSISTENCY CHECK")
    print("=" * 70)

    items_flagged = 0
    items_clean = 0

    # ── Per-item checks ───────────────────────────────────────────────────────
    for idx, item in enumerate(data.get('items', []), start=1):
        reasons = _check_item(item, idx)
        if reasons:
            item['_needs_review'] = True
            item['_review_reasons'] = reasons
            items_flagged += 1
            desc = (item.get('description') or '')[:40]
            batch = item.get('Batch') or 'N/A'
            print(f"  ⚠️  Item {idx} [{desc}] Batch={batch}:")
            for r in reasons:
                print(f"       → {r}")
        else:
            item['_needs_review'] = False
            items_clean += 1

    # ── Invoice-level checks ──────────────────────────────────────────────────
    invoice_issues = _check_invoice_totals(data)
    if invoice_issues:
        data['_invoice_review_reasons'] = invoice_issues
        print(f"\n  ⚠️  Invoice-level issues:")
        for issue in invoice_issues:
            print(f"       → {issue}")
    else:
        data['_invoice_review_reasons'] = []

    has_issues = items_flagged > 0 or len(invoice_issues) > 0

    print(f"\n  Items checked : {items_flagged + items_clean}")
    print(f"  Items flagged : {items_flagged}")
    print(f"  Items clean   : {items_clean}")
    print(f"  Invoice issues: {len(invoice_issues)}")
    print("=" * 70 + "\n")

    summary = {
        'items_flagged': items_flagged,
        'items_clean': items_clean,
        'invoice_issues': invoice_issues,
        'has_issues': has_issues,
    }

    return data, summary
