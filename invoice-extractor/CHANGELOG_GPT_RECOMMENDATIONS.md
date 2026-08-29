# Changelog: GPT Recommendations Implementation

## Session Date: 2026-08-27

### Summary
Implemented ALL high-priority recommendations from ChatGPT's analysis of Tapadia, Milton, and OpenRouter invoices. Focus: semantic ambiguity, pattern-based extraction, context-aware field recognition.

---

## ✅ Changes Implemented

### 1. Header Normalization (GPT's #1 Recommendation)
**Location:** `schema.py` lines 47-78

**Before:**
```
Column names: ITEM CODE, PCode, P.Code, Product Code, Prod Code...
(had to list every variation)
```

**After:**
```
Normalize headers before matching:
1. Convert to UPPERCASE
2. Remove ALL spaces
3. Remove ALL punctuation (. - _ /)
4. Compare against normalized patterns

Examples that NOW all match:
"Item Code" → ITEMCODE
"Item-Code" → ITEMCODE
"P Code"    → PCODE
"P.Code"    → PCODE
"Prod Code" → PRODCODE
```

**Why:** One rule handles infinite variations instead of maintaining 100+ aliases.

---

### 2. PC vs PCode Context Disambiguation  
**Location:** `schema.py` lines 69-78

**Issue:** Tapadia invoice has `PC : 4` in header (location code) AND `PCode` in table (product code)

**Solution:**
```
⚠️ CONTEXT-DEPENDENT AMBIGUITY:

In invoice HEADER (near seller/customer):
"PC : 4" → Location/Branch code (NOT product code)

In item TABLE (as column header):
"PCode" → Product/Item code

Rule: Only use PC/PCode as item_code when it's a TABLE COLUMN,
NOT when near header/customer/seller details.
```

---

### 3. PO Pattern-Based Search
**Location:** `schema.py` lines 633-670

**Issue:** Milton has `Order No: EMAIL` but real PO hidden in `REMARK:- DMH/PO/PHRMCY/2026-27/426`

**Solution:**
```
1️⃣ Search for pattern [ORG]/PO/[DEPT]/[YEAR]/[NUMBER] ANYWHERE
   Even without "PO Number" label
   
Examples:
"REMARK:- DMH/PO/PHRMCY/2026-27/426" → Extract "DMH/PO/PHRMCY/2026-27/426"
"Narration: DMH/PO/STORE/2026-27/789" → Extract "DMH/PO/STORE/2026-27/789"

Extraction Priority:
1. PO pattern anywhere → HIGHEST
2. Order No with real code → use it
3. Order No with generic value → IGNORE
4. Nothing found → null
```

---

### 4. Ignore Generic Order Numbers
**Location:** `schema.py` lines 633-670

**Issue:** Generic placeholders extracted as PO numbers

**Solution:**
```
If Order No contains:
EMAIL, PHONE, WHATSAPP, MANUAL, VERBAL, CALL, NA, N/A, NIL

→ IGNORE these values
→ Search Remarks/References/Narration for actual PO pattern
```

---

### 5. Due Date with Payment Terms
**Location:** `schema.py` lines 482-490

**Issue:** `Due Dt : 06/10/2026    CR` being extracted as "06/10/2026 CR"

**Solution:**
```
⚠️ ADJACENT PAYMENT TERMS:
"Due Dt : 06/10/2026    CR"
"Due Date: 15/01/2027 (NET 30)"

→ Extract ONLY the date: "06/10/2026"
→ Ignore: CR, NET 30, CASH, CREDIT
→ Do NOT concatenate payment terms with date
```

---

### 6. New Label Aliases from Tapadia
**Location:** `schema.py` lines 468-479

**Added:**
```
invoice_number → "Inv No" (new)
invoice_date   → "Inv Dt", "Invoice Dt" (new)
due_date       → "Due Dt" (new)
```

---

### 7. GSTIN Alias "IN GST" from OpenRouter
**Location:** `schema.py` line 500

**Added:**
```
customer_gstin → "IN GST", "Tax ID" (new)
```

---

### 8. Pack Field - Don't Over-Normalize
**Location:** `schema.py` lines 1584-1586

**Issue:** ChatGPT warned: "1.2 ML" contains volume info, don't normalize to just "1"

**Before:**
```
PACK: Normalize — add space (10S→10 S, 10TAB→10 TAB)
```

**After:**
```
PACK: Extract as-is, preserve volume/dosage
Examples: '1.2 ML', '15 CAP', '10 TAB'
Don't aggressively normalize: '1.2 ML' stays '1.2 ML' (not just '1')
```

---

## 🟠 Deferred to Next Session (Require Schema Changes)

### 1. Free Quantity Field
- Add `free_quantity: number` alongside `free_item_yn`
- Tapadia/Milton have actual FREE column with numbers (0, 2, 5)

### 2. Scheme Discount Separation
- Distinguish scheme discount from item discount
- Milton has separate SCHEME and DISCOUNT fields

### 3. Non-INR/Non-GST Invoice Support
- Allow null GST fields for non-Indian invoices
- OpenRouter uses USD, no GST

---

## Impact Summary

### Robustness Improvements:
1. **Column matching**: Handles any variation of spacing/punctuation automatically
2. **PO extraction**: Finds PO even when mislabeled or hidden in remarks
3. **Context awareness**: Same label (PC) means different things in different locations
4. **Data quality**: Ignores generic placeholders, preserves meaningful formats

### New Invoice Types Supported:
- ✅ Tapadia-style compact format (Inv No, Inv Dt, PCode)
- ✅ Milton-style with hidden PO in remarks
- ⏳ OpenRouter USD invoices (partial support, GST handling deferred)

### Prompt Size:
- **Reduced** by consolidating 100+ column aliases into normalization rules
- **Increased** by adding pattern-based search and priority logic
- **Net:** Cleaner, more maintainable

---

## Testing Required

Test with uploaded invoices:
- [ ] Tapadia C6632, C6634 - compact format, FREE column
- [ ] Milton - PO from REMARK, ignore "Order No: EMAIL"
- [ ] Kanchan SCC169 - verify existing patterns still work
- [ ] Matrix LMMFMW262708031 - batch with spaces
- [ ] Spandan SH-26-27-3774 - item codes in description
- [ ] Arihant SI-S-135184 - DMH column, month/year expiry

---

## Files Modified
1. `schema.py` - 8 targeted improvements
2. `NEW_PATTERNS_FROM_TAPADIA_MILTON.md` - tracking document
3. `CHANGELOG_GPT_RECOMMENDATIONS.md` - this file

## Server Status
Running at http://localhost:8001 with all changes active.
