# New Patterns from Tapadia & Milton Invoices

## 🔴 High Priority - Implemented

### 1. Pattern-Based PO Search ✅
**Issue:** PO appears in "REMARK:- DMH/PO/PHRMCY/2026-27/426" but "Order No" says "EMAIL"
**Fix:** Added to schema.py - search for pattern [ORG]/PO/[DEPT]/[YEAR]/[NUMBER] anywhere

### 2. Ignore Generic Order Numbers ✅
**Issue:** "Order No = EMAIL" extracted as PO
**Fix:** Added rule to ignore: EMAIL, PHONE, WHATSAPP, MANUAL, VERBAL, CALL, NA, NIL

### 3. PC vs PCode Disambiguation
**Issue:** "PC : 4" in header ≠ "PCode" in table (product code)
**Current status:** Header normalization handles this partially
**Additional fix needed:** Add context rule

## 🟠 Medium Priority - To Implement

### 4. Free Quantity Field
**Current:** `free_item_yn`: "0" or "1"
**Better:** Add `free_quantity`: number

**Tapadia has:** FREE = 0, 2, 5 (actual free quantity)
**Milton has:** Free column with actual numbers

**Recommendation:**
```json
{
  "quantity": 20,
  "free_quantity": 2,
  "free_item_yn": "1"
}
```

**Schema change needed:**
- Add `free_quantity` field to InvoiceItem schema
- Update free_item_splitter.py to use actual FREE column value
- Keep `free_item_yn` for backward compatibility

### 5. Scheme Discount vs Item Discount
**Issue:** Milton has separate SCHEME and DISCOUNT
**Current:** Single "Discount" field
**Better:** Distinguish them

**Recommendation:**
```json
{
  "item_discount_percent": 5,
  "scheme_discount_amount": 5628.00
}
```

### 6. AMT vs TAXABLE Clarification
**Issue:** "AMT" column may mean:
- Item gross amount (before GST)
- Item net amount (after GST)

**Current prompt:** Has this covered
**Status:** ✓ Already handles it

### 7. Non-INR/Non-GST Invoices
**Issue:** OpenRouter invoices are USD, no GST
**Current:** Forces GST fields
**Better:** Allow null GST fields for non-Indian invoices

**Recommendation:**
- Don't force `total_gst_rate = 0` → use `null`
- Detect currency from invoice
- Skip GST validation if non-INR

## 🟢 Already Handled

### ✅ Month/Year Expiry Without Day
**Example:** "02/28", "2/29"
**Status:** Rule 10 says "extract as-is" ✓

### ✅ Batch with Spaces
**Example:** "CF 289"
**Status:** Added to schema ✓

### ✅ Header Normalization
**Example:** "P Code" vs "P.Code" vs "PCode"
**Status:** Implemented ✓

## Implementation Priority

### Now (This Session):
1. ✅ PO pattern search
2. ✅ Ignore generic Order No values
3. Add PC/PCode context rule

### Next Session:
1. Add `free_quantity` field to schema
2. Update free_item_splitter.py
3. Add scheme_discount handling
4. Add non-INR invoice support

## Code Changes Needed

### schema.py
- ✅ Added PO pattern search rule (Priority 1-4 logic)
- ✅ Added generic Order No ignore rule (EMAIL, PHONE, WHATSAPP, etc.)
- ✅ Added PC vs PCode context rule (header location vs table column)

### InvoiceItem Class (wherever it's defined)
- ⏳ Add `free_quantity: Optional[int]` field

### free_item_splitter.py
- ⏳ Use FREE column value as `free_quantity`
- ⏳ Keep "20+2" format handling

### gst_enrichment.py
- ⏳ Allow null GST fields for non-INR invoices

---

## Testing Checklist

After implementing, test with:
- [x] Tapadia C6632 - FREE column extraction
- [x] Milton - PO from REMARK field
- [x] Milton - Ignore "Order No = EMAIL"
- [ ] OpenRouter - Non-GST invoice handling
