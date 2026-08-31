# Invoice Financial Semantics and Regression Rules

**Purpose**: Permanent reference document defining the exact meaning of each financial field and protecting against future calculation bugs.

**Rule**: This document is authoritative. Never change field meanings without updating this document first.

---

## 🔴 CRITICAL FIELD DEFINITIONS

### `Value` vs `taxable_value`

**Current contradiction in prompt**: Some rules say `Value ≠ taxable_value`, other rules say "copy TAXABLE column to both Value and taxable_value"

**Authoritative definition**:
```
Value          = Gross line amount BEFORE discount (if invoice shows AMOUNT column)
taxable_value  = Net taxable amount AFTER discount, BEFORE GST

Value ≠ taxable_value (except when invoice has no discount)
```

**Invoice pattern example (Nitin Agency)**:
```
Rate × Qty = AMOUNT     → Value = 701.55
Apply discount 4%
Result = TAXABLE        → taxable_value = 673.49
```

**Rule for extraction**:
- If invoice has separate `AMOUNT` and `TAXABLE` columns → extract both to their correct fields
- If invoice has only `TAXABLE` → both fields may be the same (no gross amount column exists)
- NEVER copy taxable_value into Value when invoice explicitly shows both

**Regression test requirement**: Any change to Value/taxable_value calculation must pass Nitin Agency invoice pattern

---

### `total_price` — THE MOST DANGEROUS FIELD

**Current contradiction**: Prompt says "copy from AMOUNT column" AND "recalculate as taxable + GST"

**Authoritative definition**:
```
total_price = Final line total INCLUDING GST

Calculation (for validation only):
total_price = taxable_value + cgst_amount + sgst_amount + igst_amount
```

**Critical rule**:
```
IF invoice prints explicit line total (AMOUNT / TOTAL / LINE TOTAL column):
    total_price = extracted printed value
    
IF invoice does NOT print line total:
    total_price = calculate from taxable + GST
    
NEVER overwrite extracted total_price just because calculation differs by ₹0.01
```

**Invoice pattern example (Nitin Agency)**:
```
AMOUNT (printed)  = 701.55  ← This is GROSS (before discount)
TAXABLE (printed) = 673.49
CGST + SGST       = 33.68
Final line total  = 707.17  ← This should be total_price

NOT 701.55 (that's the AMOUNT column, which is pre-discount gross)
```

**Danger**: Some invoices use "AMOUNT" to mean gross (before discount), others use "AMOUNT" to mean final line total. Context matters.

**Regression test requirement**: Nitin Agency pattern must never show total_price = 701.55 when actual final is 707.17

---

### `invoice_amount` — Final Payable Amount

**Current risk**: Prompt treats "Invoice Amount" label as final payable, but some invoices have BOTH:
```
Invoice Amt  = 1370.93  (intermediate subtotal)
TOPAY        = 1371.00  (final payable after round-off)
```

**Authoritative definition**:
```
invoice_amount = Final amount customer must pay

Priority order for extraction:
1. TOPAY / TO PAY
2. NET PAYABLE
3. GRAND TOTAL
4. Invoice Amount (only if no higher-priority field exists)
```

**Rule**: Never extract intermediate subtotal when explicit final payable exists

**Regression test**: Nitin Agency must show invoice_amount = 1371.00, not 1370.93

---

### `Discount` and `Discount_type`

**Current risk**: Formula assumes percentage discount. Future invoices have amount-based discount.

**Authoritative definition**:
```
Discount      = Numeric value of discount
Discount_type = "percent" | "amount" | null
```

**Calculation (only when taxable_value is missing)**:
```
IF Discount_type == "percent":
    discount_amount = round(Value × Discount / 100)
    taxable_value = Value - discount_amount

IF Discount_type == "amount":
    discount_amount = Discount
    taxable_value = Value - discount_amount
```

**Critical rule**:
```
IF invoice prints TAXABLE column:
    taxable_value = printed value
    DO NOT calculate from discount
```

**Multi-discount pattern protection**:
```
Some invoices have:
- Trade Discount (TD)
- Cash Discount (CD)
- Scheme Discount (SCH)

Current schema has only ONE Discount field.

Rule: When multiple discounts exist and TAXABLE is printed,
      trust printed TAXABLE.
      Do NOT try to reverse-engineer individual discounts.
```

**Regression test**: Any discount calculation change must work for both percent and amount types

---

### `round_off` — Sign Preservation Critical

**Current status**: Already correctly preserves sign

**Authoritative definition**:
```
round_off = Amount added to pre-rounding total to reach final payable

Can be positive: +0.07
Can be negative: -0.35
Can be zero: 0.00
```

**Validation formula**:
```
pre_rounding_total + round_off ≈ invoice_amount
```

**Critical rule**: NEVER change sign of round_off to force totals to match

**Regression test**: Preserve existing sign-handling logic unchanged

---

### GST fields — Line-level vs Invoice-level

**Current risk**: Line-by-line rounding vs bulk calculation can differ by ₹0.01

**Authoritative definition**:
```
Item level:
  cgst_amount = Line CGST (printed or calculated)
  sgst_amount = Line SGST (printed or calculated)
  igst_amount = Line IGST (printed or calculated)
  GST_AMT     = cgst + sgst + igst for this line

Invoice level:
  total_cgst_amount = Sum of all line CGST
  total_sgst_amount = Sum of all line SGST  
  total_igst_amount = Sum of all line IGST
  total_gst_amount  = Sum of all line GST_AMT
```

**Extraction priority**:
```
1. If line GST amounts are printed → use them → sum for totals
2. If only invoice total GST is printed → use it → derive line-level if needed
3. Calculate only when both are missing
```

**Rule**: Line-by-line rounding takes precedence over bulk calculation

**Example**:
```
Line 1 CGST = round(taxable₁ × 2.5%) = 16.84
Line 2 CGST = round(taxable₂ × 2.5%) = 15.80
Total CGST  = 16.84 + 15.80 = 32.64

NOT: round((taxable₁ + taxable₂) × 2.5%)
```

---

### `total_gst_rate` — Single vs Mixed Slabs

**Current risk**: Prompt assumes single GST rate. Future invoices may have 5%, 12%, 18% on different items.

**Authoritative definition**:
```
IF all items have same GST rate:
    total_gst_rate = that rate

IF multiple GST rates exist:
    total_gst_rate = null OR extract from invoice header if printed

NEVER calculate:
    total_gst_rate = (total_gst_amount / total_taxable_value) × 100
    
That would be weighted effective rate, not an actual GST slab.
```

**Regression protection**: Do not break existing single-rate invoices when adding multi-rate support

---

## 🟠 MEDIUM PRIORITY RULES

### `total_quantity` — Paid vs Free

**Current definition**: Sum of paid quantities only (excludes free items)

**Rule preserved**:
```
total_quantity = sum(item.quantity where free_item_yn == "0")

Free quantity patterns to detect:
- "10+2" → 10 paid, 2 free
- "10/1" → 10 paid, 1 free  
- Separate "Free" column
- "Scheme" column
```

**Regression protection**: Do not accidentally include free quantities in total

---

### Tax field semantics: `null` vs `0.00`

**Current pattern**:
```json
Item level:
  "igst_amount": null  ← field not applicable (intra-state invoice)

Invoice level:  
  "total_igst_amount": "0.00"  ← explicitly zero total
```

**Rule**: Preserve this distinction
```
null   = not applicable / not present in source
"0.00" = explicitly zero monetary value
```

**Regression protection**: Do not normalize all nulls to zero or vice versa without schema change approval

---

### HSN/SAC Length

**Current prompt says**: "8-digit HSN"

**Actual invoices have**: `300215` (6 digits), `90189099` (8 digits)

**Rule**: Copy printed HSN/SAC exactly. Do not enforce fixed length unless downstream schema requires padding.

---

### MRP vs unit_price vs Rate Including GST

**Current prompt**: Already distinguishes these

**Rule to preserve**:
```
MRP              = Maximum Retail Price (regulatory)
unit_price       = Actual selling price per unit (before GST)
Rate Incl. GST   = Selling price including GST

MRP ≠ unit_price (usually MRP > unit_price due to discounts)
```

**Danger**: Do not select highest rate value assuming it's the selling price

---

### Expiry Date Normalization

**Current formats handled**:
```
11/27        → 30/11/2027
03-29        → 31/03/2029
30-Jun-30    → 30/06/2030
31/12/2027   → 31/12/2027
```

**Rule**: Preserve source expiry value interpretation. Do not fail extraction if date parsing is ambiguous.

---

### Due Date — Extracted vs Calculated

**Current prompt**: Extracts due_date if present

**Rule**:
```
IF invoice prints "Due Date":
    due_date = extracted value
ELSE:
    due_date = null

Do NOT auto-calculate from invoice_date + payment_terms
unless project explicitly requires that business logic.
```

---

## 🔴 EXTRACTION ARCHITECTURE (NEVER CHANGE)

### Layer 1 — Extraction
```
Extract what is physically printed on invoice
Never "correct" printed values because they look wrong
```

### Layer 2 — Normalization
```
Remove commas from numbers
Normalize dates to DD/MM/YYYY
Preserve signs for round_off
Convert strings to appropriate types
```

### Layer 3 — Validation
```
Check if extracted values reconcile:
  Rate × Qty ≈ Gross
  Gross - Discount ≈ Taxable  
  Taxable + GST ≈ Line Total
  Sum line totals + Round Off ≈ Invoice Amount
```

### Layer 4 — Fallback
```
Calculate ONLY when value is genuinely missing
NEVER overwrite extracted value with calculated value
  unless validation shows extracted value is clearly OCR error
```

**CRITICAL RULE**: 
```
Never follow this pattern:
  Extract → Recalculate Everything → Overwrite Invoice

Always follow:
  Extract → Validate → Fill Missing → Flag Discrepancies
```

---

## 🚨 REGRESSION TEST REQUIREMENTS

Every bug fix must demonstrate:

1. **The exact bug**: Show actual failing invoice + wrong output
2. **Root cause**: Identify exact line/function causing wrong output
3. **Minimal fix**: Show diff of proposed change
4. **Backward compatibility**: Verify fix does not break existing test cases
5. **New test case**: Add failing invoice to regression suite

**Before any code change**:
- Run all existing invoices through current system
- Save outputs as baseline
- Apply fix
- Re-run all invoices
- Diff outputs
- Any changed output for previously-correct invoice = REGRESSION BUG

---

## 📋 KNOWN INVOICE PATTERNS (REGRESSION TEST SUITE)

### Pattern 1: Nitin Agency (Discount + Round-off)
```
AMOUNT = gross before discount
DISCOUNT % applied
TAXABLE = after discount  
CGST + SGST applied to taxable
Invoice Amt = intermediate subtotal
Round Off = +0.07
TOPAY = final payable
```

**Test**: Must correctly distinguish AMOUNT ≠ TAXABLE ≠ TOPAY

---

### Pattern 2: Medica (Multiple discounts)
```
AMOUNT
- Trade Discount
- Cash Discount  
- Scheme Discount
= TAXABLE
+ GST
= Line Total
```

**Test**: Must not try to reconstruct individual discounts when TAXABLE is printed

---

### Pattern 3: E Bioremedies (Simple calculation)
```
Rate × Qty = AMOUNT
CGST + SGST on AMOUNT
= Line Total
Sum line totals = Invoice Amount
```

**Test**: Baseline for simple invoice without discounts

---

### Pattern 4: Matrix Biomedics (Multi-line product cell)
```
Product cell contains:
  Line 1: Product name
  Line 2: Batch : CF 289
  Line 3: Expiry : 30-Jun-30
  Line 4: Code : AL-02-1234
  Line 5: OLD MRP : 31584.00
```

**Test**: Description must contain ONLY product name, other fields extracted correctly

---

### Pattern 5: Tapadiya C/6636 (GST rounding + TO PAY priority)
```
Qty × Rate = AMOUNT (gross)
Apply discount % → TAXABLE
CGST + SGST on TAXABLE (line-by-line rounding)
Sum line totals = Total Amount (59727.73)
Add Round Off (+0.27)
= TO PAY (59728.00)  ← This is invoice_amount, NOT Total Amount
```

**Test**: 
- GST_AMT must equal CGST + SGST (not direct calculation from taxable × rate%)
- invoice_amount must be TO PAY (59728.00), not Total Amount (59727.73)
- Component rounding: taxable=3987.78, rate=5% → CGST=99.69, SGST=99.69, GST_AMT=199.38 (NOT 199.39)

---

## 📝 CHANGE LOG

All changes to financial calculation logic must be documented here:

### [2024-XX-XX] Description field parsing
- **Bug**: Multi-line product cells dumped Batch/Expiry/Code into description
- **Fix**: Added explicit prompt rule + post-processing parser in ocr_corrector.py
- **Impact**: Description now clean, sub-fields extracted correctly
- **Regression**: No financial calculations changed

### [2024-XX-XX] GST_AMT component rounding consistency
- **Bug**: GST_AMT calculated as round(taxable × rate%) before calculating components, creating ₹0.01 mismatch
  - Example: taxable=3987.78, rate=5%
  - Direct: round(3987.78 × 5%) = 199.39
  - Components: CGST=round(3987.78 × 2.5%)=99.69, SGST=99.69 → sum=199.38
  - Mismatch: GST_AMT=199.39 but CGST+SGST=199.38
- **Root cause**: gst_enrichment.py line 219 calculated GST_AMT first, then components separately
- **Fix**: Recalculate GST_AMT as component sum after calculating CGST/SGST (line 229)
- **Impact**: GST_AMT now matches component sum (matches invoice line-by-line rounding)
- **Affected invoices**: Tapadiya C/6636 items 1, 3, 5 now correct
- **Regression**: Only affects calculated GST (when components not extracted). Extracted values unchanged.

### [2024-XX-XX] invoice_amount extraction priority
- **Bug**: Model sometimes extracted "Total Amount" (pre-round-off) instead of "TO PAY" (final payable)
  - Example: Tapadiya C/6636 shows Total Amount=59727.73, Round Off=0.27, TO PAY=59728.00
  - Wrong output: invoice_amount=59727.73
  - Correct: invoice_amount=59728.00
- **Root cause**: Prompt listed multiple labels but didn't specify extraction priority
- **Fix**: Added explicit priority order in schema.py line 801:
  1. TO PAY / TOPAY / TO-PAY (highest)
  2. NET PAYABLE / AMOUNT PAYABLE
  3. GRAND TOTAL (if after round-off)
  4. Invoice Amount (only if no higher field exists)
- **Impact**: Model now instructed to prefer TO PAY over intermediate totals
- **Regression**: No code changes, prompt clarification only

---

## ⚠️ FUTURE RISKS TO MONITOR

1. **Multi-GST-slab invoices**: Current schema assumes single rate
2. **Multiple discount types**: Schema has one Discount field, some invoices have 3+
3. **Extra charges**: Freight, packing, courier, TCS not in current schema
4. **Credit notes**: CN/DN amounts affect final payable
5. **TCS (Tax Collected at Source)**: Separate from GST, added to invoice total
6. **Line continuation across pages**: Multi-page invoice with item split across pages

These are not bugs yet, but will become bugs when such invoices arrive.

---

## 🔒 FIELDS LOCKED (NEVER RENAME WITHOUT DATABASE MIGRATION)

- `invoice_amount`
- `total_price`
- `Value`
- `taxable_value`
- `GST_AMT`
- `round_off`
- `Discount`
- `Discount_type`

Downstream systems depend on these exact names.

---

**Document owner**: Invoice extraction system maintainer  
**Last updated**: [Current date]  
**Version**: 1.0
