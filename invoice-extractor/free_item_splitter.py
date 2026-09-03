"""
Free Item Splitter - Splits items with free quantities into separate records
"""

from typing import List, Dict, Any
import copy
from langsmith import traceable


@traceable(name="split_free_items", tags=["items", "splitting"])
def split_free_items(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Split items with free quantities into TWO separate records:
    - Record 1: Paid item (free_item_yn="0", with proportional prices/taxes)
    - Record 2: Free item (free_item_yn="1", with proportional prices/taxes based on free quantity)
    
    Handles both patterns:
    1. Combined format: quantity="20+2"
    2. Separate columns: quantity=20, free_quantity=2
    3. Two-row format: row with qty=0+free_qty, followed by paid row → merged first
    
    All product-identifying fields are copied unchanged to both records.
    Only quantity-dependent monetary fields are recalculated proportionally.
    
    Args:
        data: Invoice data dict with items array
    
    Returns:
        Modified data dict with split items
    """
    items = data.get('items', [])
    if not items:
        return data

    # ── PRE-PASS: Merge two-row free item format ──────────────────────────────
    # Some invoices show free items as two consecutive rows for the same product:
    #   Row A: description="X", quantity=0, free_item_yn="1"  (free qty row)
    #   Row B: description="X", quantity=100, free_item_yn="0" (paid row)
    # Merge Row A's free info into Row B and drop Row A.
    merged_items = []
    skip_next = False

    for i, item in enumerate(items):
        if skip_next:
            skip_next = False
            continue

        qty = item.get('quantity', 0)

        # Normalise qty to a number for comparison (ignore "0+0" strings etc.)
        try:
            qty_num = float(qty) if not isinstance(qty, str) or '+' not in str(qty) else None
        except (TypeError, ValueError):
            qty_num = None

        is_zero_qty = (qty_num is not None and qty_num == 0)
        is_free_row = (item.get('free_item_yn') == "1")

        if is_zero_qty and is_free_row and i + 1 < len(items):
            next_item = items[i + 1]
            next_desc  = (next_item.get('description') or '').strip().lower()
            this_desc  = (item.get('description') or '').strip().lower()

            # Check if next row is the same product (paid row)
            if next_desc and this_desc and next_desc == this_desc:
                next_qty = next_item.get('quantity', 0)
                try:
                    next_qty_num = float(next_qty) if not isinstance(next_qty, str) or '+' not in str(next_qty) else None
                except (TypeError, ValueError):
                    next_qty_num = None

                if next_qty_num and next_qty_num > 0:
                    # Determine free quantity from this zero row
                    free_qty_value = item.get('free_quantity')
                    if not free_qty_value:
                        # No explicit free_quantity — the row itself IS the free record;
                        # but we have no free qty number to attach, so just drop the ghost
                        print(f"[FREE MERGE] Dropping zero-qty ghost row for: {item.get('description')}")
                        skip_next = False
                        continue  # drop Row A, keep Row B as-is

                    # Attach free_quantity to the paid row
                    merged = copy.deepcopy(next_item)
                    merged['free_quantity'] = float(free_qty_value)
                    merged['free_item_yn'] = "1"
                    print(f"[FREE MERGE] Merged two-row free item: '{this_desc}' "
                          f"qty={next_qty_num} free={free_qty_value}")
                    merged_items.append(merged)
                    skip_next = True  # skip Row B, already merged
                    continue

        # Drop standalone zero-quantity ghost records (qty=0, no free_quantity)
        if is_zero_qty and not item.get('free_quantity'):
            print(f"[FREE SPLIT] Dropping zero-qty ghost record: {item.get('description')}")
            continue

        merged_items.append(item)

    items = merged_items
    # ── END PRE-PASS ──────────────────────────────────────────────────────────

    new_items = []
    
    for item in items:
        quantity = item.get('quantity')
        free_quantity = item.get('free_quantity')
        
        # Case 1: Combined format (quantity="20+2")
        if isinstance(quantity, str) and '+' in quantity:
            try:
                # Parse "20+2" → paid=20, free=2
                parts = quantity.split('+')
                paid_qty = float(parts[0].strip())
                free_qty = float(parts[1].strip()) if len(parts) > 1 else 0
                
                if free_qty > 0:
                    # Create paid item
                    paid_item = create_proportional_item(item, paid_qty, is_free=False)
                    new_items.append(paid_item)
                    
                    # Create free item
                    free_item = create_proportional_item(item, free_qty, is_free=True)
                    new_items.append(free_item)
                else:
                    # No free qty, just add paid item
                    paid_item = copy.deepcopy(item)
                    paid_item['quantity'] = paid_qty
                    paid_item['free_item_yn'] = "0"
                    paid_item.pop('free_quantity', None)
                    new_items.append(paid_item)
            
            except (ValueError, IndexError) as e:
                # If parsing fails, keep original item
                print(f"[WARNING] Failed to parse quantity '{quantity}': {e}")
                item['free_item_yn'] = "0"
                item.pop('free_quantity', None)
                new_items.append(item)
        
        # Case 2: Separate columns (quantity=20, free_quantity=2)
        elif free_quantity is not None and free_quantity > 0:
            paid_qty = float(quantity) if quantity else 0
            free_qty = float(free_quantity)
            
            # Create paid item (recalculate based on paid quantity only)
            paid_item = create_proportional_item(item, paid_qty, is_free=False)
            new_items.append(paid_item)
            
            # Create free item (calculate based on free quantity)
            free_item = create_proportional_item(item, free_qty, is_free=True)
            new_items.append(free_item)
        
        # Case 3: No free items — OR already a standalone free item row
        # (free_item_yn="1" set by model, but no free_quantity to split)
        else:
            # If the model already flagged this item as free (free_item_yn="1")
            # with its own non-zero quantity, it is a standalone free item row
            # extracted directly from the invoice (e.g. a DISC QTY column row).
            # In that case keep the free flag and preserve invoice financials.
            #
            # Special case: model may have hallucinated a non-zero unit_price
            # while the invoice clearly shows Amount=0 and Taxable=0.
            # When total_price=0 AND taxable_value=0 (or both missing), zero out
            # all monetary fields and unit_price to match the invoice.
            if item.get('free_item_yn') == "1":
                tp_v  = None
                tv_v  = None
                try:
                    tp_v = float(str(item.get('total_price') or '0').replace(',', ''))
                except (ValueError, TypeError):
                    tp_v = None
                try:
                    tv_v = float(str(item.get('taxable_value') or '0').replace(',', ''))
                except (ValueError, TypeError):
                    tv_v = None

                if (tp_v is None or tp_v == 0.0) and (tv_v is None or tv_v == 0.0):
                    # Invoice shows explicit zeros — preserve them, zero out any
                    # hallucinated unit_price so downstream enrichment stays clean
                    zero_fields = ['total_price', 'Value', 'taxable_value',
                                   'cgst_amount', 'sgst_amount', 'igst_amount', 'GST_AMT']
                    for zf in zero_fields:
                        item[zf] = 0.0
                    item['unit_price'] = 0.0
                    print(f"[FREE SPLIT] Zero-price standalone free item: "
                          f"'{item.get('description','')[:40]}' qty={item.get('quantity')} "
                          f"— all monetary fields set to 0.00")
                item.pop('free_quantity', None)
                new_items.append(item)
            else:
                item['free_item_yn'] = "0"
                item.pop('free_quantity', None)
                new_items.append(item)
    
    data['items'] = new_items
    return data


def create_proportional_item(base_item: Dict[str, Any], new_qty: float, is_free: bool) -> Dict[str, Any]:
    """
    Create a proportional item record (paid or free) based on the new quantity.

    CRITICAL: Invoice monetary values correspond to PAID quantity only, not paid+free.

    UNCHANGED FIELDS (product-identifying):
    - description, Pack, Batch, hsn_sac, item_code
    - expiry_date, reference_number, Gst%, MRP, unit_price
    - cgst_rate, sgst_rate, igst_rate (rates remain the same)
    - Discount (percentage remains the same)

    RECALCULATED FIELDS (quantity-dependent):
    - quantity → new_qty
    - total_price → unit_price × new_qty (always recalculated from unit_price)
    - Value, taxable_value, GST_AMT, cgst_amount, sgst_amount, igst_amount
      → proportional to new_qty / paid_qty (not total_qty!)

    ZERO-PRICE FREE ITEMS:
    - Some invoices explicitly show 0.00 for Rate, Amount, and Taxable on the free row.
      This means the seller has gifted those units at no value — all monetary fields
      must remain 0.00 and unit_price must be set to 0 for the free record.
    - Detection: the base item has total_price == 0 AND taxable_value == 0
      (or both are null/missing). In that case ALL monetary fields → 0 and
      unit_price → 0.  We do NOT calculate unit_price × free_qty.

    Args:
        base_item: Original item dict
        new_qty: New quantity (paid or free)
        is_free: True if this is a free item, False if paid

    Returns:
        New item dict with proportional calculations
    """
    new_item = copy.deepcopy(base_item)

    # ── Helper ────────────────────────────────────────────────────────────────
    def _to_float(v) -> float | None:
        if v is None:
            return None
        try:
            return float(str(v).replace(',', '').replace('₹', '').strip())
        except (ValueError, TypeError):
            return None

    # ── Zero-price free item detection ───────────────────────────────────────
    # When the invoice explicitly shows 0 amounts for this row (e.g. Rate=0,
    # Amount=0, Taxable=0), we must preserve those zeros — do NOT compute
    # unit_price × free_qty, as unit_price may have been copied from the paid
    # row by the model even though the invoice printed 0.
    #
    # Condition: BOTH total_price and taxable_value are zero (or absent).
    # A row where only one of them is zero could be a data gap, but if both
    # are zero the invoice is unambiguous — the free units have no monetary value.
    tp_val  = _to_float(base_item.get('total_price'))
    tv_val  = _to_float(base_item.get('taxable_value'))
    val_val = _to_float(base_item.get('Value'))

    is_zero_price = (
        (tp_val is None or tp_val == 0.0)
        and (tv_val is None or tv_val == 0.0)
    )

    if is_free and is_zero_price:
        # Invoice explicitly priced free units at zero — preserve that
        zero_monetary = ['total_price', 'Value', 'taxable_value',
                         'cgst_amount', 'sgst_amount', 'igst_amount', 'GST_AMT']
        for field in zero_monetary:
            new_item[field] = 0.0
        new_item['unit_price']   = 0.0
        new_item['quantity']     = new_qty
        new_item['free_item_yn'] = "1"
        new_item.pop('free_quantity', None)
        print(f"[FREE SPLIT] Zero-price free item: '{base_item.get('description','')[:40]}' "
              f"qty={new_qty} — all monetary fields set to 0.00")
        return new_item

    # ── Standard proportional split ───────────────────────────────────────────
    # Get original quantity and determine paid quantity
    original_qty = base_item.get('quantity')
    free_qty_field = base_item.get('free_quantity')

    # Calculate PAID quantity (the denominator for proportional calculations)
    paid_qty = None

    if isinstance(original_qty, str) and '+' in original_qty:
        # Parse "20+2" → paid_qty = 20
        parts = original_qty.split('+')
        paid_qty = float(parts[0].strip())
    elif free_qty_field is not None and free_qty_field > 0:
        # Separate columns: paid_qty = quantity (not quantity + free_quantity!)
        paid_qty = float(original_qty) if original_qty else 1
    else:
        # No free items, use quantity as-is
        paid_qty = float(original_qty) if original_qty else 1

    # Calculate proportion based on PAID quantity (not total!)
    # This is the KEY fix: invoice values correspond to paid quantity
    proportion = new_qty / paid_qty if paid_qty > 0 else 0

    # Set new quantity and flag
    new_item['quantity'] = new_qty
    new_item['free_item_yn'] = "1" if is_free else "0"
    new_item.pop('free_quantity', None)  # Remove free_quantity field

    # Recalculate total_price from unit_price × quantity
    # Do NOT use proportional calculation for total_price
    if 'unit_price' in new_item and new_item['unit_price'] is not None:
        unit_price = float(new_item['unit_price']) if isinstance(new_item['unit_price'], str) else new_item['unit_price']
        new_item['total_price'] = round(unit_price * new_qty, 2)

    # Recalculate quantity-dependent monetary fields proportionally
    # These are proportional to paid quantity, not total quantity
    monetary_fields = [
        'Value',
        'taxable_value',
        'cgst_amount',
        'sgst_amount',
        'igst_amount',
        'GST_AMT'
    ]

    for field in monetary_fields:
        if field in new_item and new_item[field] is not None:
            original_value = float(new_item[field]) if isinstance(new_item[field], str) else new_item[field]
            new_item[field] = round(original_value * proportion, 2)

    # UNCHANGED FIELDS - keep exactly as they are:
    # - description, Pack, Batch, hsn_sac, item_code
    # - expiry_date, reference_number
    # - Gst%, cgst_rate, sgst_rate, igst_rate (rates don't change)
    # - MRP (per-unit price doesn't change)
    # - unit_price (per-unit price doesn't change)
    # - Discount (percentage doesn't change)

    return new_item


def get_free_item_stats(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get statistics about free items in the invoice.
    
    Returns:
        Dict with free item counts and details
    """
    items = data.get('items', [])
    
    total_items = len(items)
    free_items = [item for item in items if item.get('free_item_yn') == "1"]
    free_count = len(free_items)
    
    return {
        'total_items': total_items,
        'paid_items': total_items - free_count,
        'free_items': free_count,
        'has_free_items': free_count > 0
    }
