# Prompt Updates for New Invoice Patterns

## Issues Found from 4 Test Invoices

### 1. New Column Names Not Recognized

#### COM Column (Manufacturer/Company)
**Invoice:** SCC169 (Kanchan Drugs)
**Issue:** "COM" column contains manufacturer name ("BECTO")
**Current:** Not mentioned in prompts
**Fix:** Add to item extraction: "COM → manufacturer/company name"

#### SCH AMT, TD AMT, CD AMT Columns  
**Invoice:** SI-S-135184 (Arihant Chemist)
**Issue:** Columns for Scheme Amount, Trade Discount Amount, Cash Discount Amount
**Current:** Not mentioned
**Fix:** Add note to IGNORE these columns (internal accounting, not item-level data)

### 2. Item Code Positioning Variations

#### Item Code at START of Description
**Invoice:** SH-26-27-3774 (Spandan Healthcare)
**Example:** "SR-01-0331 OPSITE POST-OP 15.5X8.5CM"
**Current:** Prompt searches for codes at end of description or in separate line
**Fix:** Add pattern: "Item code at START of description"

**Already added to schema.py ✅**

### 3. Expiry Date Format Variations

#### Single-Digit Day
**Invoice:** SH-26-27-3774
**Example:** "1-Dec-30" (not "01-Dec-30")
**Current:** Examples show "01-12-2030"
**Fix:** Add example with single-digit day

#### MM/YY Only (No Day)
**Invoice:** SI-S-135184
**Example:** "06/29" (MM/YY, no day at all)
**Current:** Covered in Rule 10
**Status:** ✅ Already handled

### 4. Batch Number Variations

#### Space in Middle
**Invoice:** LMMFMW262708031
**Example:** "CF 289" (space between letters and numbers)
**Current:** Prompt assumes no spaces
**Fix:** Add note: "Batch may contain spaces - copy exactly"

#### Pure Numeric (6 digits)
**Invoice:** SH-26-27-3774
**Example:** "202552" (no letters)
**Current:** Examples show alphanumeric
**Fix:** Add example with pure numeric batch

### 5. Manufacturer/Company Field

**Invoice:** SCC169
**Column:** "COM" contains "BECTO"
**Issue:** No field in schema for manufacturer
**Fix:** Either:
  - Add new field: `manufacturer` or `company`
  - OR document that we extract it but don't include in final JSON
  - OR ignore it entirely (not required by client)

**Decision needed:** Check if client needs manufacturer field

---

## Fixes Applied

### ✅ Completed
1. Added "COM" to column search pattern for item_code
2. Added "Item code at START of description" pattern
3. Added note about SCH AMT/TD AMT/CD AMT to IGNORE

### ⏳ Remaining
1. Add batch number space example
2. Add single-digit day expiry example  
3. Decide on manufacturer field (add or ignore)

---

## Test Results Expected After Fixes

### Invoice 1: SCC169
- ✅ 3 items extracted
- ✅ "BECTO" manufacturer recognized (if we add field)
- ✅ "Dis" column = 0.60% discount
- ✅ Expiry: "28-Feb-31" extracted as-is

### Invoice 2: LMMFMW262708031
- ✅ 1 item extracted (qty 8 boxes)
- ✅ Batch "CF 289" (with space) extracted correctly
- ✅ No item code (empty string)
- ✅ "OLD MRP" line ignored

### Invoice 3: SH-26-27-3774
- ✅ 3 items extracted
- ✅ Item codes from START of description: SR-01-0331, SR-01-0333, SR-02-0807
- ✅ Batch "202552" (pure numeric) extracted
- ✅ Expiry "1-Dec-30" (single digit) extracted

### Invoice 4: SI-S-135184
- ✅ 1 item extracted
- ✅ DMH column → item_code: AY-01-0004
- ✅ Expiry "06/29" (MM/YY only) extracted
- ✅ SCH AMT/TD AMT/CD AMT columns ignored
- ✅ Manufacturer "THE" extracted (if field added)
