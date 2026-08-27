# Item Code OCR Correction Guide

## Overview

The system now includes **automatic OCR correction for item codes** to fix recurring digit misreads like `6` ↔ `8`.

## How It Works

1. After extraction, all item codes are normalized and checked against a correction catalog
2. If the extracted code matches a known mistake, it's automatically replaced with the correct value
3. The correction is logged in the processing output: `[ITEM_CODE] OCR correction: 'AL-02-3176' → 'AL-02-3178'`

## How to Add New Corrections

When you discover a new OCR mistake:

1. Open `gstin_validator.py`
2. Locate the `ITEM_CODE_CORRECTIONS` dictionary (around line 278)
3. Add a new entry in the format:

   ```python
   ITEM_CODE_CORRECTIONS: dict[str, str] = {
       "AL-02-3176": "AL-02-3178",   # 6→8 confirmed mis-read on item 2
       "SR-05-1234": "SR-05-1284",   # Add your new correction here
   }
   ```

4. Format: `"WHAT_MODEL_EXTRACTED": "CORRECT_VALUE"`
5. Add a comment explaining the mistake (e.g., `# 8→6 on batch X`)
6. Save the file — no server restart needed (changes apply on next extraction)

## Example Corrections

```python
ITEM_CODE_CORRECTIONS: dict[str, str] = {
    # Known 6↔8 confusions
    "AL-02-3176": "AL-02-3178",   # 6→8 confirmed mis-read
    "SR-06-3124": "SR-08-3124",   # 6→8 in middle segment
    
    # Known 0↔O confusions
    "AL-O2-3456": "AL-02-3456",   # O→0 in second segment
    
    # Other digit confusions
    "TL-01-2350": "TL-01-2850",   # 3→8 rare confusion
}
```

## Scope

- Only applies to the `item_code` field
- Case-insensitive matching
- Handles minor spacing/hyphen variations automatically
- Does **not** affect: item descriptions, batch numbers, PO numbers, or other fields

## When to Use

Add corrections when:
- The **same** item code is consistently misread across multiple invoices
- You have verified the correct value from the original invoice document
- The pattern is a simple character substitution (not a complex transformation)

**Don't add** corrections for:
- One-off mistakes that don't recur
- Codes where you're unsure of the correct value
- Structural differences (e.g., different prefixes or length changes)

## Clearing Cache

After adding corrections, clear the cache to re-process affected invoices:

**Windows (CMD):**
```cmd
del "c:\Users\Anil Abhange\Downloads\pdf-processor -no validation\invoice-extractor\uploads\.cache\*.json"
```

**Windows (PowerShell):**
```powershell
Remove-Item "c:\Users\Anil Abhange\Downloads\pdf-processor -no validation\invoice-extractor\uploads\.cache\*.json"
```

**Linux/Mac:**
```bash
rm -f uploads/.cache/*.json
```

## Monitoring

Watch the extraction logs for messages like:
```
[ITEM_CODE] OCR correction: 'AL-02-3176' → 'AL-02-3178'
```

This confirms the correction was applied successfully.
