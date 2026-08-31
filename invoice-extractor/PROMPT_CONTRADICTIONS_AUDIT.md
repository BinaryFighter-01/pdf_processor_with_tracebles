# Prompt Contradictions Audit

**Date**: Current  
**Status**: AUDIT ONLY — NO CHANGES MADE YET

This document identifies the exact contradictions in schema.py that GPT warned about.

---

## 🔴 CONTRADICTION #1: Value vs taxable_value (CRITICAL)

### Location: schema.py lines 1148 vs 1422-1427

**Rule A** (line 1148-1150):
```
- Never copy taxable_value into Value
- Never assume Value = taxable_value
```

**Rule B** (line 1422-1427):
```
If invoice has a TAXABLE column:
  1. Copy TAXABLE column value directly to BOTH Value and taxable_value
```

### Why this is dangerous

**Nitin Agency invoice pattern**:
```
AMOUNT column  = 701.55  (gross before discount)
DISC %         = 4%
TAXABLE column = 673.49  (after discount)
CGST + SGST    = 33.68
Final          = 707.17
```

If Rule B is followed:
```
Value = 673.49  (copied from TAXABLE)
taxable_value = 673.49  (copied from TAXABLE)
```

**Problem**: We lost the gross amount (701.55). Value should be 701.55, not 673.49.

### Correct behavior should be

**Pattern 1**: Invoice has BOTH Amount and Taxable columns
```
AMOUNT  → Value = 701.55
TAXABLE → taxable_value = 673.49
```

**Pattern 2**: Invoice has ONLY Taxable column (no gross amount shown)
```
TAXABLE → Value = 673.49
TAXABLE → taxable_value = 673.49
```

The distinction depends on whether invoice shows a pre-discount amount.

### Recommendation

**Replace lines 1421-1432** with:
```
⚠️ VALUE vs TAXABLE_VALUE DISTINCTION (CRITICAL):

Pattern 1: Invoice has BOTH "AMOUNT" and "TAXABLE" columns
  → Value = AMOUNT column (gross before discount)
  → taxable_value = TAXABLE column (after discount)
  
Pattern 2: Invoice has ONLY "TAXABLE" column (no separate AMOUNT)
  → Value = TAXABLE column
  → taxable_value = TAXABLE column
  
Pattern 3: Invoice has ONLY "AMOUNT" column (no discount, no TAXABLE)
  → Value = AMOUNT column
  → taxable_value = AMOUNT column

NEVER blindly copy TAXABLE to both fields when AMOUNT column exists.

Nitin Agency example:
  AMOUNT = 701.55, DISC 4%, TAXABLE = 673.49
  Correct: Value = 701.55, taxable_value = 673.49
  WRONG:   Value = 673.49, taxable_value = 673.49 (lost gross!)
```

**Status**: NOT FIXED YET — awaiting user approval

---

## 🔴 CONTRADICTION #2: total_price meaning (HIGH RISK)

### Location: schema.py line 1510

**Current prompt** (line 1510):
```
total_price = copy from AMOUNT column (not TAXABLE AMT)
```

### Why this is ambiguous

Some invoices use "AMOUNT" to mean:
- **Gross before discount** (Nitin Agency: AMOUNT = 701.55 → then discount applied → TAXABLE = 673.49)
- **Final line total** (other invoices: AMOUNT = final after GST)

The current rule doesn't distinguish these cases.

### What total_price actually means

According to downstream usage and schema:
```
total_price = Final line total INCLUDING GST
            = taxable_value + cgst + sgst + igst
```

**Nitin Agency example**:
```
AMOUNT column    = 701.55  (gross before discount)
TAXABLE column   = 673.49  (after discount)
CGST + SGST      = 33.68
Final line total = 707.17  ← This should be total_price

NOT 701.55 (that's pre-discount gross)
NOT 673.49 (that's pre-GST taxable)
```

### Recommendation

**Clarify line 1510**:
```
total_price = Final line total INCLUDING GST

Priority for extraction:
1. If invoice has explicit "LINE TOTAL" or "TOTAL" column → extract it
2. If invoice shows AMOUNT column that represents final (check if GST included) → extract it
3. If no explicit total → calculate: taxable_value + cgst + sgst + igst

IMPORTANT: Some invoices use "AMOUNT" for gross before discount.
           Check context. If TAXABLE column exists separately,
           AMOUNT is probably gross, not final.
           
Nitin Agency: AMOUNT = gross (701.55), final line = taxable + GST = 707.17
```

**Status**: NOT FIXED YET — awaiting user approval

---

## 🟠 CONTRADICTION #3: Discount calculation assumes percentage

### Location: Implied in calculation logic (not explicit in prompt yet)

**Current prompt**: Recognizes both "percent" and "amount" discount types

**Problem**: Calculation formulas in prompt/code assume:
```
discount_amount = Value × Discount / 100
```

This only works for percentage.

### What happens with amount-based discount

Example:
```
Value = 10,000
Discount = 500
Discount_type = "amount"
```

Percentage formula would calculate:
```
10,000 × 500 / 100 = 50,000  ❌ WRONG
```

Correct:
```
discount_amount = 500 (it's already the amount)
```

### Recommendation

**Add explicit calculation rules** (after line 1070 in Discount field definition):
```
Discount calculation (only when taxable_value is missing):

IF Discount_type == "percent":
    discount_amount = round(Value × Discount / 100)
    taxable_value = Value - discount_amount

IF Discount_type == "amount":
    discount_amount = Discount
    taxable_value = Value - discount_amount

CRITICAL: If invoice prints TAXABLE column, use printed value.
          Do NOT calculate from discount.
```

**Status**: NOT FIXED YET — awaiting user approval

---

## 🟠 ISSUE #4: invoice_amount priority ambiguous

### Location: Not explicit in current prompt

**Current prompt**: Says to extract "Invoice Amount" / "TO PAY" / "Net Amount"

**Problem**: Doesn't define priority when invoice has BOTH:
```
Invoice Amt = 1370.93  (intermediate subtotal)
Round Off   = 0.07
TOPAY       = 1371.00  (final payable)
```

Model might extract 1370.93 when correct answer is 1371.00.

### Recommendation

**Add explicit priority order**:
```
invoice_amount = Final amount customer must pay

Extraction priority (highest to lowest):
1. TOPAY / TO PAY
2. NET PAYABLE
3. GRAND TOTAL  
4. Invoice Total
5. Invoice Amount (only if no higher-priority field exists)

NEVER extract intermediate subtotal when explicit final payable exists.

Nitin Agency example:
  Invoice Amt = 1370.93 ❌ (this is before round-off)
  Round Off   = 0.07
  TOPAY       = 1371.00 ✓ (this is final payable)
```

**Status**: NOT FIXED YET — awaiting user approval

---

## 🟡 MINOR ISSUES (Lower priority)

### HSN length assumption
**Line**: HSN description says "8-digit"  
**Problem**: Some invoices have 6-digit HSN (e.g., 300215)  
**Fix**: Change to "6 or 8 digit HSN/SAC code"

### total_gst_rate for mixed slabs
**Current**: Assumes single rate  
**Future risk**: Invoices with 5%, 12%, 18% on different items  
**Fix**: Add note that total_gst_rate should be null if multiple slabs exist

### null vs 0.00 for tax fields
**Current**: Working correctly  
**Protection needed**: Document that null ≠ "0.00" (different semantics)

---

## 📋 FIXING PRIORITY

1. **🔴 Fix Value/taxable_value contradiction** — breaks Nitin Agency pattern
2. **🔴 Clarify total_price meaning** — high risk of wrong line totals
3. **🟠 Add discount type handling** — future bug when amount-based discounts arrive
4. **🟠 Add invoice_amount priority** — prevents wrong final payable extraction
5. **🟡 Minor clarifications** — low risk, can be done later

---

## ⚠️ BEFORE MAKING ANY CHANGES

1. Get user approval for each fix
2. Show exact diff
3. Explain impact
4. Test with Nitin Agency invoice
5. Test with all existing regression invoices
6. Verify no output changes for working invoices

---

## 🚨 DO NOT CHANGE WITHOUT USER APPROVAL

This is an audit only. The contradictions are real, but fixing them requires:
- User confirmation of the correct field semantics
- Regression testing against all existing invoices
- Verification that downstream systems expect the corrected behavior

**Status**: WAITING FOR USER DECISION

---

**Audited by**: Kiro  
**Date**: Current  
**Next step**: Present to user for approval to fix
