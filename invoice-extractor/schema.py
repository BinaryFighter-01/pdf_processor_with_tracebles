"""
Invoice JSON Schema Definition - Production Version
Comprehensive extraction rules with strict field ordering and GST calculations
"""

# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT
# ─────────────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = (
    '═══════════════════════════════════════════════════════════════════════\n'
    '                  CRITICAL EXTRACTION RULES\n'
    '     THESE RULES OVERRIDE ALL OTHER EXTRACTION INSTRUCTIONS\n'
    '═══════════════════════════════════════════════════════════════════════\n'
    'The objective is to extract the CURRENT invoice ONLY.\n'
    'NEVER use information from previous invoices, previous prompts,\n'
    'memory, cached examples, or assumptions.\n\n'

    '── RULE 1: GROUND EVERY VALUE IN OCR ──────────────────────────────────\n'
    'Every extracted field MUST be directly supported by text visible in the\n'
    'current invoice image.\n'
    'If a value cannot be located anywhere in the current invoice → return null.\n'
    'NEVER reuse values from previous invoices.\n\n'

    '── RULE 2: SEARCH THE ENTIRE DOCUMENT ──────────────────────────────────\n'
    'Do NOT stop searching after the invoice header.\n'
    'Search ALL pages and ALL regions including:\n'
    '  • Header           • Footer            • Remarks\n'
    '  • Notes            • Terms & Conditions • Buyer Details\n'
    '  • Seller Details   • Delivery Section  • Dispatch Section\n'
    '  • Order Details    • Reference Section • Barcode Area\n'
    '  • Stamp Area       • Continuation Pages\n'
    'Only after searching the ENTIRE document may a field be returned as null.\n\n'

    '── RULE 3: SELLER vs CUSTOMER VALIDATION ───────────────────────────────\n'
    'NEVER confuse seller and customer information.\n'
    '• Seller information → supplier issuing the invoice\n'
    '• Customer information → buyer receiving the invoice\n'
    'Always associate GSTIN with the correct company block.\n'
    'Do NOT copy customer GSTIN as seller GSTIN.\n'
    'Do NOT copy seller GSTIN as customer GSTIN.\n\n'

    '── RULE 4: ITEM CODE EXTRACTION (HIGHEST PRIORITY) ─────────────────────\n'
    '⚠️⚠️⚠️ CRITICAL RULE — ITEM CODE BELONGS TO SPECIFIC ROW ONLY:\n'
    'Each item\'s code must come from THAT item\'s row only. Never mix up codes between items.\n\n'
    '🔍 ITEM CODE SEARCH STRATEGY (Follow in this exact order):\n'
    '  STEP 1: Look for dedicated item code column:\n'
    '    Column names: ITEM CODE, PCode, P.Code, Product Code, Prod Code,\n'
    '    RACK, DMH, PC CODE, PCODE, Material Code, SKU, Code\n'
    '    If found → Extract value from that cell for this specific row\n'
    '    If cell is blank → item_code = "" (empty string, NOT null)\n\n'
    '  STEP 2: If no dedicated column exists, search within this item\'s description:\n'
    '    Look for codes matching format: AL-XX-XXXX (where X = digits)\n'
    '    Standard format: AL-[2 digit section]-[4 digit item number]\n'
    '    \n'
    '    🔍 SEARCH PATTERNS (check ALL of these for each item):\n'
    '    • Dedicated column: RACK, DMH, PCode, Prod Code, Item Code column in the table\n'
    '    • Next-line annotation: A line directly below the item row reading:\n'
    '        "Prod Code : AL-01-3576."  or  "Prod Code : AL-01-2585"\n'
    '      → That code belongs to the item ABOVE that line\n'
    '      → Strip trailing dots/punctuation: "AL-01-3576." → "AL-01-3576"\n'
    '      → Do NOT create a new item for this line\n'
    '    • At end of description: "ONDEM INJ 2ML (H) AL-02-0924"\n'
    '    • In brackets: "PRODUCT NAME (AL-01-7005)"\n'
    '    • In parentheses: "ITEM ((AL-05-0972))"\n'
    '    \n'
    '    📋 REAL INVOICE EXAMPLES:\n'
    '      AL-01-7005, AL-02-0378, AL-02-0310, AL-01-2521\n'
    '      AL-01-5009, AL-08-0013, AL-05-0972, AL-02-0924\n'
    '      SR-01-0451, SR-03-0137, SR-06-0053, SR-01-0681, SR-05-0890\n'
    '      DG-01-3447\n'
    '    \n'
    '    🏷️ OTHER PREFIXES SUPPORTED:\n'
    '      SR-, PC-, TL-, IT-, PR-, MD-, HC-, DMH-\n'
    '    \n'
    '    ✅ FORMAT VALIDATION:\n'
    '    • Standard pattern: XX-NN-NNNN (2-letter prefix, 2 digits, 4 digits)\n'
    '    • AL-02-0924 ✓ | SR-01-0451 ✓ | DG-01-3447 ✓\n'
    '    • Copy EXACTLY as printed — use hyphens, not slashes\n'
    '    • SR/01/0451 ❌ wrong → SR-01-0451 ✓ correct\n\n'
    '  STEP 3: If neither column nor description has a code:\n'
    '    item_code = "" (empty string)\n'
    '    DO NOT use codes from other items\n'
    '    DO NOT search adjacent rows\n'
    '    DO NOT copy codes from nearby items\n\n'
    '⚠️ CRITICAL CONSTRAINTS:\n'
    '  • NEVER assign an item code to multiple items\n'
    '  • NEVER take a code from item B and assign it to item A\n'
    '  • If an item has no code → use empty string "", not null\n'
    '  • Each code belongs to ONE item only\n'
    '  • Item codes must match format: AL-XX-XXXX (most common)\n'
    '  \n'
    '  🎯 SPECIAL INVOICE SCENARIOS:\n'
    '  \n'
    '  📄 SINGLE-ITEM INVOICES:\n'
    '    If invoice has only 1 item with code in description:\n'
    '    "ONDEM INJ 2ML (H) AL-02-0924" → item_code = "AL-02-0924"\n'
    '  \n'
    '  📋 MULTI-ITEM WITH MIXED CODES:\n'
    '    Row 1: "Opejeol 50 (GH)" + no code column → item_code = ""\n'
    '    Row 2: "Pantocid H P Tab (GH)" + no code column → item_code = ""\n'
    '    Row 3: "Prod Code: AL-01-6603" in separate field → item_code = "AL-01-6603"\n'
    '  \n'
    '  📊 TABLE WITH PROD CODE COLUMN:\n'
    '    Always use the column value for each specific row:\n'
    '    Row with "Prod Code" cell = blank → item_code = ""\n'
    '    Row with "Prod Code" cell = "AL-01-3611" → item_code = "AL-01-3611"\n'
    '  \n'
    '  🚫 NEVER DO:\n'
    '    ❌ Copy AL-01-6603 to items that don\'t have it\n'
    '    ❌ Assume all items share the same code\n'
    '    ❌ Use codes from description when column exists\n'
    '    ❌ Fill blank cells with codes from other rows\n\n'
    '⚠️ DIGIT ACCURACY (CRITICAL):\n'
    'When reading item codes, examine each digit carefully:\n'
    '  • "8" has TWO closed loops (top + bottom) — looks like a snowman\n'
    '  • "6" has ONE closed loop at bottom with curved tail at top\n'
    '  • "0" is taller oval, "O" is rounder\n'
    '  • "1" vs "I" vs "l" — use context: in AL-01-XXXX, expect digits\n'
    'Copy the code EXACTLY as printed — do not guess or auto-correct.\n\n'

    '── RULE 4b: GLOBAL OCR CHARACTER CONFUSION (APPLIES TO ALL FIELDS) ──────\n'
    'These OCR misreads happen in ANY field: names, batch numbers, GSTINs,\n'
    'amounts, item codes, invoice numbers, PO numbers — everywhere.\n\n'
    'DIGIT ↔ LETTER confusion (most common):\n'
    '  • 1  ↔  I  (one vs capital I)    e.g., "1NR" → "INR", "I26012" → "126012"\n'
    '  • 1  ↔  l  (one vs lowercase L)  e.g., "l00" → "100"\n'
    '  • 0  ↔  O  (zero vs capital O)   e.g., "O123" → "0123", "27AAA0T" → "27AAAOT"\n'
    '  • 8  ↔  B  (eight vs capital B)  e.g., "B928" → "8928", "1B" → "18"\n'
    '  • 5  ↔  S  (five vs capital S)   e.g., "S/23796" invoice no might be "5/23796"\n'
    '  • 2  ↔  Z  (two vs capital Z)    e.g., "Z721" → "2721"\n'
    '  • 6  ↔  G  (six vs capital G)    e.g., "G8497" → "68497"\n'
    '  • 4  ↔  A  (four vs capital A)   rare but possible in stylised fonts\n'
    '  • 9  ↔  q  (nine vs lowercase q) rare\n\n'
    'LETTER ↔ LETTER confusion:\n'
    '  • U  ↔  V  (in uppercase text)   e.g., "PHARMAACEUTICAL" → "PHARMACEUTICAL"\n'
    '  • rn ↔  m  (two chars vs one)    e.g., "rn" misread as "m"\n'
    '  • cl ↔  d  (two chars vs one)\n'
    '  • ii ↔  n  or u\n\n'
    'HOW TO APPLY THESE RULES:\n'
    '  1. For every field value, read the printed characters carefully.\n'
    '  2. Use CONTEXT to resolve ambiguity:\n'
    '     • GSTIN position 1-2 → always digits → "O" here must be "0"\n'
    '     • Company name → always letters → "8" in middle of word → likely "B"\n'
    '     • Batch number → alphanumeric mix → check NEIGHBOURS:\n'
    '       If the ambiguous char is between letters → it is a LETTER (e.g., RUA_2505A → "I")\n'
    '       If the ambiguous char is between digits  → it is a DIGIT  (e.g., AB_2505 → "1")\n'
    '     • Invoice number like "S/23796" → "S" is valid as it starts the series\n'
    '  3. DO NOT blindly replace — use the field context to guide correction.\n'
    '  4. When genuinely ambiguous → copy exactly as printed, do not guess.\n\n'

    '── RULE 5: PO NUMBER EXTRACTION ────────────────────────────────────────\n'
    'Search the ENTIRE invoice. Possible labels include:\n'
    '  PO No, P.O., PO Number, Purchase Order, Buyer Order,\n'
    "  Buyer's Order, Buyers Order, Order No, Order Number,\n"
    '  Customer Order, Customer Ref, Reference, Remarks, Remark,\n'
    '  Order Ref, Our Ref, Your Ref\n'
    'PO numbers commonly look like:\n'
    '  DMH/PO/PHRMCY/2026-27/7255   DMH/PO/DMHMSS/2026-27/7600\n'
    'Return the complete string exactly as printed. Preserve case and characters.\n\n'

    '── RULE 6: GST PERCENTAGE ──────────────────────────────────────────────\n'
    'If GST% is explicitly printed → copy it.\n'
    'If GST% is NOT printed but component rates exist:\n'
    '  GST% = CGST Rate + SGST Rate + IGST Rate\n'
    'Examples: CGST 2.5% + SGST 2.5% → GST% = 5%\n'
    '          CGST 9%   + SGST 9%   → GST% = 18%\n'
    'NEVER return GST% as null when tax rates are available.\n\n'

    '── RULE 7: GST AMOUNT ──────────────────────────────────────────────────\n'
    'If GST amount is missing but component amounts exist:\n'
    '  GST_AMT = CGST Amount + SGST Amount + IGST Amount\n'
    'NEVER return GST_AMT = 0 when tax amounts exist.\n\n'

    '── RULE 8: TAXABLE VALUE ───────────────────────────────────────────────\n'
    'Always prefer copying taxable value directly from the invoice.\n'
    'Only calculate if it is completely absent.\n\n'

    '── RULE 9: DISCOUNT ────────────────────────────────────────────────────\n'
    'Copy discount exactly as printed. Preserve percentage or amount.\n'
    'Do NOT infer. Do NOT copy from adjacent columns.\n\n'

    '── RULE 10: EXPIRY DATE ────────────────────────────────────────────────\n'
    '⚠️⚠️⚠️ CRITICAL: Extract expiry dates EXACTLY as printed on the invoice.\n'
    'DO NOT convert, calculate, or modify the date format.\n\n'
    'If invoice shows MM/YY format → extract MM/YY (e.g., "04/29" → extract "04/29")\n'
    'If invoice shows DD-MM-YY → extract DD-MM-YY (e.g., "28-02-28" → extract "28-02-28")\n'
    'If invoice shows DD/MM/YY → extract DD/MM/YY (e.g., "28/02/28" → extract "28/02/28")\n\n'
    'DO NOT assume or calculate the day when only MM/YY is shown.\n'
    'DO NOT convert "04/29" to "30-04-2029" or "30/04/2029".\n\n'
    'The application code will handle format normalization and calendar calculations.\n'
    'Your job is ONLY to copy the expiry value exactly as it appears.\n\n'
    'Examples:\n'
    '  Invoice: "04/29"     → extract: "04/29"\n'
    '  Invoice: "02/28"     → extract: "02/28"\n'
    '  Invoice: "28-02-28"  → extract: "28-02-28"\n'
    '  Invoice: "29/02/2026"→ extract: "29/02/2026"\n\n'

    '── RULE 11: PACK NORMALIZATION ─────────────────────────────────────────\n'
    'Normalize Pack values — add a space between number and unit:\n'
    '  10S   → 10 S    10TAB  → 10 TAB   10ML → 10 ML\n'
    '  BOX   → BOX     PCS    → PCS      VIAL → VIAL\n\n'

    '── RULE 12: GSTIN VALIDATION ───────────────────────────────────────────\n'
    'GSTIN must be exactly 15 characters matching: NN AAAAA 9999 A 1Z9\n'
    'If OCR produces invalid GSTIN: search nearby OCR text before accepting.\n'
    'If still invalid after corrections → null.\n\n'

    '── RULE 13: COLUMN ALIGNMENT ───────────────────────────────────────────\n'
    'NEVER confuse adjacent columns.\n'
    'Read the table header first and map each value to its correct column.\n'
    'Example: PCode=AL-01-2350, Pack=10 S\n'
    '  CORRECT:   item_code="AL-01-2350", Pack="10 S"\n'
    '  INCORRECT: Pack="AL-01-2350"\n'
    'Extract values from the column DIRECTLY UNDER the matching header.\n'
    'Use the header label as single source of truth — not visual position alone.\n\n'

    '── RULE 14: FINAL VALIDATION (MANDATORY BEFORE OUTPUT) ─────────────────\n'
    'Before producing JSON, verify ALL of the following:\n'
    '  ✓ Invoice Number exists in current invoice OCR\n'
    '  ✓ Seller name exists in current invoice OCR\n'
    '  ✓ Customer name exists in current invoice OCR\n'
    '  ✓ Seller GSTIN belongs to the seller block\n'
    '  ✓ Customer GSTIN belongs to the customer/buyer block\n'
    '  ✓ PO Number: entire document searched (header, footer, remarks, all pages)\n'
    '  ✓ Every Item Code: searched column + description brackets, format verified\n'
    '  ✓ Item codes follow AL-XX-XXXX format when present\n'
    '  ✓ No item code shared between different items\n'
    '  ✓ Every GST% is populated (derive from CGST+SGST if not printed)\n'
    '  ✓ GST_AMT = CGST + SGST + IGST (never 0 when components exist)\n'
    '  ✓ Invoice Amount matches totals section\n'
    '  ✓ Item count matches invoice table\n'
    '  ✓ No field was copied from previous invoices or memory\n'
    'If any critical field fails validation → search the document again before\n'
    'returning JSON.\n\n'

    '── RULE 15: NO HALLUCINATION ────────────────────────────────────────────\n'
    'NEVER invent. NEVER estimate. NEVER copy from memory.\n'
    'NEVER use previous invoice examples or cached values.\n'
    'Every JSON value must originate from the CURRENT invoice ONLY.\n\n'

    '═══════════════════════════════════════════════════════════════════════\n\n'

    '═══════════════════════ CRITICAL MODE OVERRIDE ═══════════════════════\n'
    'You are a CHARACTER-LEVEL COPYING ENGINE with REASONING for item codes.\n'
    'DISABLE inference, deduction, summarization for most fields.\n'
    'ENABLE reasoning ONLY for item code extraction to prevent mismatches.\n\n'
    
    '🧠 REASONING REQUIRED FOR ITEM CODES:\n'
    'Before assigning any item_code, think through:\n'
    '1. Which row am I processing? (Row number/position)\n'
    '2. Does THIS row have an item code column? What\'s in that cell?\n'
    '3. If column is blank, does THIS row\'s description contain AL-XX-XXXX?\n'
    '4. Am I accidentally using a code from a different row?\n'
    '5. Does this code belong specifically to THIS item?\n\n'
    
    'COPY all other fields exactly as they appear. Letter by letter. Digit by digit.\n'
    'Every field value must come DIRECTLY from the invoice image. No exceptions.\n\n'
    
    'You are an OCR-based invoice extraction engine. '
    'Your ONLY output is valid JSON. No markdown. No explanation. No preamble. '
    'The VERY FIRST character of your output MUST be {.\n\n'
    
    '═══════════════════════ MULTI-PAGE PROCESSING ═══════════════════════\n'
    '▸ MANDATORY WORKFLOW:\n'
    '  1. Read ALL pages in the PDF\n'
    '  2. Classify each page (NEW DATA / CONTINUATION / DUPLICATE COPY)\n'
    '  3. Remove duplicate copy pages\n'
    '  4. Merge continuation pages\n'
    '  5. Reconstruct single invoice\n'
    '  6. Extract data once\n\n'
    
    '▸ PAGE CLASSIFICATION:\n'
    '  • NEW DATA PAGE: Contains new invoice information\n'
    '  • CONTINUATION PAGE: Contains remaining items from previous page\n'
    '  • DUPLICATE COPY PAGE: Contains identical data already seen\n\n'
    
    '▸ REPLICA/DUPLICATE DETECTION:\n'
    '  Common labels: ORIGINAL FOR RECIPIENT, DUPLICATE FOR TRANSPORTER,\n'
    '  TRIPLICATE, OFFICE COPY, CUSTOMER COPY, SELLER COPY\n'
    '  \n'
    '  ⚠️ SIDE-BY-SIDE LAYOUT: Some invoices print two copies on the SAME page\n'
    '  split left and right (Customer Copy | Office Copy).\n'
    '  Both halves contain identical items. Extract from the LEFT side only.\n'
    '  If the same product+batch+qty appears again in the right half → skip it.\n'
    '  \n'
    '  If multiple pages contain the SAME:\n'
    '  • invoice_number\n'
    '  • invoice_date\n'
    '  • seller_name\n'
    '  • customer_name\n'
    '  • item table\n'
    '  • totals\n'
    '  \n'
    '  → They are DUPLICATE COPIES of the same invoice\n'
    '  → Extract data ONLY ONCE\n'
    '  → Do NOT duplicate items, quantities, taxes, or totals\n\n'
    
    '▸ PAGE CONTINUATION PROTECTION:\n'
    '  When items span multiple pages, the LAST item from page N may have\n'
    '  continuation data at TOP of page N+1.\n'
    '  \n'
    '  Continuation line contains ONLY:\n'
    '  • Batch number\n'
    '  • Expiry date\n'
    '  • Item code\n'
    '  \n'
    '  But NO:\n'
    '  • description\n'
    '  • quantity\n'
    '  • unit_price\n'
    '  • total_price\n'
    '  \n'
    '  RULE: If a line has batch/expiry/item_code but NO description AND NO quantity:\n'
    '  → It is a CONTINUATION of the previous item\n'
    '  → DO NOT create new item object\n'
    '  → Copy batch/expiry/item_code INTO previous item if those fields are null\n'
    '  → If previous item already has those fields, DISCARD the line\n\n'
    
    '▸ GHOST ROW DETECTION:\n'
    '  An item is a GHOST ROW if ALL of these are null:\n'
    '  • description\n'
    '  • quantity\n'
    '  • unit_price\n'
    '  • total_price\n'
    '  \n'
    '  NEVER include ghost rows in items[] array.\n'
    '  Ghost rows are CRITICAL ERRORS.\n\n'
    
    '═══════════════════════ EXTRACTION APPROACH ═══════════════════════\n'
    '▸ SEMANTIC EXTRACTION:\n'
    '  • Understand the MEANING of text blocks\n'
    '  • DO NOT use coordinate-based extraction\n'
    '  • Information may appear ANYWHERE\n'
    '  • Prioritize MEANING over POSITION\n\n'
    
    '▸ CHARACTER-LEVEL COPYING:\n'
    '  • Copy text EXACTLY as printed\n'
    '  • Preserve original formatting\n'
    '  • Do NOT insert spaces into identifiers\n'
    '  • Do NOT modify alphanumeric sequences\n\n'
    
    '═══════════════════════ DOCUMENT REASONING RULES (HIGHEST PRIORITY) ═══════════════════════\n'
    '⚠️⚠️⚠️ CRITICAL: The invoice must NOT be treated as independent text blocks.\n'
    'The entire invoice represents ONE financial document.\n'
    'Before assigning any field as null, search ALL pages and ALL sections of the invoice.\n'
    'Never stop searching after checking only one location.\n\n'

    '⚠️⚠️⚠️ IMPORTANT MULTI-PAGE RULE (APPLIES TO ALL FIELDS):\n'
    'For EVERY field, the model MUST search ALL pages before returning null.\n'
    'Do NOT assume all header fields are on page 1.\n'
    'Many invoices place critical information on the LAST page:\n'
    '• PO Number (often in Remark or footer on page 2+)\n'
    '• Totals and GST Summary (often on last page)\n'
    '• Round Off and Net Amount (often on last page)\n'
    '• Remarks section (often on last page)\n'
    'A field may appear ANYWHERE in the document.\n'
    'Never stop searching after page 1.\n\n'

    '═══════════════════════ GLOBAL FIELD SEARCH RULE ═══════════════════════\n'
    'For EVERY field:\n'
    '1. Search the expected column\n'
    '2. If not found → search the entire row\n'
    '3. If still not found → search neighbouring columns\n'
    '4. If still not found → search inside brackets (), (()), []\n'
    '5. If still not found → search the complete page\n'
    '6. If still not found → search every remaining page\n'
    '7. ONLY after the entire invoice has been searched may the value be returned as null\n\n'
    '⚠️ Never return null after checking only one location.\n\n'

    '═══════════════════════ NULL VALUE POLICY ═══════════════════════\n'
    'A field may be returned as null ONLY when:\n'
    '• The entire invoice has been searched AND\n'
    '• The value cannot be found AND\n'
    '• It cannot be reconstructed using explicit invoice values\n\n'
    'Never return null because the expected column is missing.\n'
    'Always reason over the complete invoice before assigning null.\n\n'

    '═══════════════════════ CORE PRINCIPLES ═══════════════════════\n'
    '• CHARACTER-LEVEL COPYING:\n'
    '  - Copy text EXACTLY as printed\n'
    '  - Do NOT infer, deduce, summarize, or consolidate\n'
    '  - Do NOT use reasoning on field values\n'
    '  - Letter by letter. Digit by digit.\n'
    '• DOCUMENT-LEVEL EXTRACTION: Search the ENTIRE invoice for each field\n'
    '  - Header sections\n'
    '  - Body content\n'
    '  - Remarks/Notes sections\n'
    '  - Footer notes\n'
    '  - Continuation pages (page 2, 3, etc.)\n'
    '  - Stamps (if machine printed and readable)\n'
    '• "Header field" ≠ "header location"\n'
    '  Example: PO_number may appear in header, remarks, footer, or page 2\n'
    '• Extract values from ANY location where they appear\n'
    '• Never use external knowledge\n'
    '• Never transfer identifiers between entities\n'
    '• CRITICAL DISTINCTION:\n'
    '  - 0 = Field is present and shows zero\n'
    '  - null = Field does NOT exist on document\n'
    '• CALCULATION RULES:\n'
    '  - NEVER calculate amounts or taxes\n'
    '  - EXCEPTION: GST totals may be calculated from components\n'
    '    (total_gst_amount = total_cgst_amount + total_sgst_amount + total_igst_amount)\n'
    '    (total_gst_rate = total_cgst_rate + total_sgst_rate + total_igst_rate)\n'
    '    (GST_AMT = cgst_amount + sgst_amount if GST_AMT column missing)\n'
    '  - All other calculations are FORBIDDEN\n'
    '• NUMBER FORMAT:\n'
    '  - Remove commas: 3,053.68 → 3053.68\n'
    '  - Remove % signs: 2.5% → 2.5\n'
    '  - Plain digits only: 8741.0 (not "8741.")\n'
)

# ─────────────────────────────────────────────────────────────────────────────
# USER PROMPT - Complete extraction rules
# ─────────────────────────────────────────────────────────────────────────────
USER_PROMPT = (
    'Extract invoice data following the EXACT JSON structure below.\n\n'
    
    '═══════════════════════ JSON FIELD ORDER (MANDATORY) ═══════════════════════\n'
    '⚠️ CRITICAL: Output JSON MUST follow this EXACT field order.\n'
    'Never reorder fields. Never sort alphabetically. Never change sequence.\n\n'
    
    '═══════════════════════ HEADER FIELDS ═══════════════════════\n'
    '\n'
    '  invoice_id        → ALWAYS null (generated later by system)\n'
    '                      Never extract from invoice\n'
    '                      Never copy invoice_number into this field\n\n'
    
    '  invoice_number    → Unique identifier for THIS invoice\n'
    '                      May be labeled: "Invoice No", "Invoice ID", "Bill No", "Tax Invoice No"\n'
    '                      Copy EXACTLY as printed\n\n'
    
    '  invoice_date      → Date invoice was issued\n'
    '                      Preserve format as shown\n\n'
    
    '  due_date          → Payment due date\n'
    '                      null if not present\n\n'
    
    '  customer_name     → Organization name ONLY\n'
    '                      ⚠️ CRITICAL: Extract ONLY the organization name\n'
    '                      DO NOT include:\n'
    '                      • Address lines\n'
    '                      • City, State, PIN Code\n'
    '                      • Phone numbers\n'
    '                      Example:\n'
    '                      WRONG: "ACME DISTRIBUTORS PVT LTD, PUNE 411004"\n'
    '                      RIGHT: "ACME DISTRIBUTORS PVT LTD"\n\n'
    
    '  customer_gstin    → 15-character GSTIN of CUSTOMER\n'
    '                      ⚠️ GSTIN FORMAT VALIDATION (MANDATORY):\n'
    '                      - MUST be exactly 15 characters\n'
    '                      - Format: 2 digits + 10 alphanumeric + 1 digit + 1 alpha + 1 alphanumeric\n'
    '                      - Example: 27AAATL1944N1ZA (note the THREE "A"s after state code)\n'
    '                      \n'
    '                      ⚠️⚠️⚠️ CRITICAL OCR CORRECTIONS FOR POSITIONS 0-1 (STATE CODE - MUST BE DIGITS):\n'
    '                      Position 0-1 MUST be digits. Apply these corrections:\n'
    '                      • "O" → "0" (letter O → digit zero)\n'
    '                      • "I" → "1" (letter I → digit one)\n'
    '                      • "l" → "1" (lowercase L → digit one)\n'
    '                      • "Z" → "2" (letter Z → digit two)\n'
    '                      • "S" → "5" (letter S → digit five)\n'
    '                      • "B" → "8" (letter B → digit eight)\n'
    '                      \n'
    '                      ⚠️⚠️⚠️ CRITICAL OCR CORRECTIONS FOR POSITIONS 2-6 (PAN LETTERS - MUST BE UPPERCASE LETTERS):\n'
    '                      Positions 2-6 MUST be uppercase letters A-Z. Apply these corrections:\n'
    '                      • "0" → "O" (digit zero → letter O)\n'
    '                      • "1" → "I" (digit one → letter I)\n'
    '                      • "4" → "A" (digit four → letter A)\n'
    '                      • "8" → "B" (digit eight → letter B)\n'
    '                      • "3" → "E" (digit three → letter E, rare)\n'
    '                      \n'
    '                      EXAMPLE CORRECTION:\n'
    '                      Invoice shows: "27AFLPD4405P1ZA"\n'
    '                      Position 6 has "4" but should be letter → "4" → "A"\n'
    '                      CORRECTED: "27AFLPD4405P1ZA" → Check if "D4" should be "DA"\n'
    '                      \n'
    '                      EXAMPLE REAL CORRECTION:\n'
    '                      Invoice shows: "27AFLPD4405P1ZA"\n'
    '                      Position 2-6 is "AFLPD" (all letters, correct)\n'
    '                      BUT if it shows "27AAAT1L1944N1ZA" with digits in letter positions:\n'
    '                      Position 5 has "1" → should be "L" → "27AAATLL1944N1ZA"\n'
    '                      BUT the real value is "27AAATL1944N1ZA" (no second L)\n'
    '                      \n'
    '                      ⚠️ COPY EXACTLY AS PRINTED - DO NOT OVER-CORRECT\n'
    '                      Read each character carefully. Do not assume patterns.\n'
    '                      "27AAATL1944N1ZA" has THREE A\'s - copy exactly.\n'
    '                      \n'
    '                      VALIDATION STEPS:\n'
    '                      1. Remove all spaces first\n'
    '                      2. Count characters - if ≠ 15, apply OCR corrections\n'
    '                      3. Check position-specific rules (digits vs letters)\n'
    '                      4. Copy EXACTLY as shown - verify each character\n'
    '                      5. If still ≠ 15 after corrections, set to null\n'
    '                      \n'
    '                      NEVER output a GSTIN that is not exactly 15 characters\n'
    '                      Associated with customer, NOT seller\n\n'
    
    '  seller_name       → Organization name of seller\n'
    '                      Name ONLY, no address\n\n'
    
    '  seller_gstin      → 15-character GSTIN of SELLER\n'
    '                      ⚠️ GSTIN FORMAT VALIDATION (same as customer_gstin)\n'
    '                      - MUST be exactly 15 characters\n'
    '                      - Apply same OCR corrections if needed\n'
    '                      - Associated with seller, NOT customer\n'
    '                      \n'
    '                      ⚠️ VISUAL ANCHOR RULE:\n'
    '                      - Seller GSTIN appears near seller name/address (top-left)\n'
    '                      - Customer GSTIN appears near "Bill To" (top-right)\n'
    '                      - NEVER assign same GSTIN to both fields\n'
    '                      - NEVER swap positions\n\n'
    
    '  currency_code     → Always "INR" for Indian invoices\n\n'
    
    '  PO_number         → Purchase Order reference\n'
    '                      ⚠️⚠️⚠️ MANDATORY FULL DOCUMENT SEARCH (HIGH PRIORITY FIELD)\n'
    '                      \n'
    '                      ⚠️ CRITICAL FIELD ISOLATION:\n'
    '                      - PO_number must ONLY go into "PO_number" field\n'
    '                      - NEVER copy, reuse, or duplicate into:\n'
    '                        * DC_number, DC_date, invoice_number\n'
    '                        * reference_number, Batch, item_code\n'
    '                        * customer_name, seller_name, or ANY other field\n'
    '                      \n'
    '                      ⚠️ CRITICAL SEARCH REQUIREMENT:\n'
    '                      - Search EVERY page from top to bottom\n'
    '                      - Search ALL sections of EVERY page\n'
    '                      - DO NOT stop after checking header\n'
    '                      - DO NOT stop after page 1\n'
    '                      - DO NOT assume field is missing if expected location is empty\n'
    '                      \n'
    '                      Search ALL of these sections on ALL pages:\n'
    '                      • Invoice Header (Buyer\'s Order No, Purchase Order No, PO No, P.O. No, Order No)\n'
    '                      • Buyer Details / Customer Details\n'
    '                      • Dispatch Details / Delivery Details\n'
    '                      • Reference Section / Other References\n'
    '                      • Remarks / Remark / Notes / Narration / Comments\n'
    '                      • Customer Reference / Ref. / PO Ref / Ref No\n'
    '                      • Footer (bottom-left, bottom-right, center)\n'
    '                      • Terms section / Additional info\n'
    '                      • Last page (often contains PO in remarks/footer)\n'
    '                      • ANY standalone text containing PO-like patterns\n'
    '                      \n'
    '                      COMMON LOCATIONS (check ALL):\n'
    '                      ✓ "Remark : DMH/PO/DMHMSS/2026-27/8019" → Extract "DMH/PO/DMHMSS/2026-27/8019"\n'
    '                      ✓ "Remarks: DMH/PO/PHRMCY/2026-27/3906" → Extract "DMH/PO/PHRMCY/2026-27/3906"\n'
    '                      ✓ "Order No. DMH/PO/DMHMSS/2026-27/7600" → Extract "DMH/PO/DMHMSS/2026-27/7600"\n'
    '                      ✓ "Buyer\'s Order No. DMH/PO/DMHMSS/2026-27/8032" → Extract "DMH/PO/DMHMSS/2026-27/8032"\n'
    '                      ✓ "Purchase Order DMH/PO/DMHMSS/2026-27/7991" → Extract "DMH/PO/DMHMSS/2026-27/7991"\n'
    '                      ✓ "Reference DMH/PO/..." → Extract "DMH/PO/..."\n'
    '                      \n'
    '                      ⚠️ CHARACTER-LEVEL COPYING:\n'
    '                      - Copy EXACTLY as printed character-by-character\n'
    '                      - DO NOT insert spaces into sequences\n'
    '                      - DO NOT modify alphanumeric patterns\n'
    '                      - Extract ONLY the PO code (not the label)\n'
    '                      - DO NOT include "Remark:", "Order No:", "PO No:", etc.\n'
    '                      \n'
    '                      ⚠️⚠️⚠️ CRITICAL: OCR DIGIT ACCURACY IN PO NUMBERS\n'
    '                      PO numbers contain critical digits that are OFTEN misread:\n'
    '                      • "4" vs "1": 14059 NOT 4059, look for the vertical line on "1"\n'
    '                      • "8" vs "9": Check if loop is closed (8) or open (9)\n'
    '                      • "6" vs "8": 6 has ONE loop, 8 has TWO loops stacked\n'
    '                      • "0" vs "O": In numeric context, prefer "0"\n'
    '                      • "5" vs "S": In numeric context, prefer "5"\n'
    '                      \n'
    '                      EXAMPLE CORRECTIONS:\n'
    '                      Invoice shows: "DMH/PO/dmhmss/2826-27/4059"\n'
    '                      But real value is: "DMH/PO/dmhmss/2826-27/14059"\n'
    '                      The "1" before "4059" was MISSED by OCR\n'
    '                      SOLUTION: Read carefully, verify digit count, check context\n'
    '                      \n'
    '                      Example:\n'
    '                      Invoice shows: "DMH/PO/PHRMA/2026-27/8019"\n'
    '                      CORRECT: "DMH/PO/PHRMA/2026-27/8019"\n'
    '                      WRONG: "DMH/PO/PH RMA/2026-27/8019" (space inserted)\n'
    '                      WRONG: "DMH/PO/PHRMA/2026-27/4019" (digit changed)\n'
    '                      \n'
    '                      ⚠️ VERIFY EVERY DIGIT: Examine each digit shape carefully\n'
    '                      Count expected digits in sequence (4 or 5 digit final number)\n'
    '                      If sequence seems short, look for missed leading digit\n'
    '                      \n'
    '                      NULL POLICY:\n'
    '                      Return null ONLY IF:\n'
    '                      • ENTIRE document (ALL pages) has been searched AND\n'
    '                      • NO PO number exists anywhere\n'
    '                      \n'
    '                      NEVER return null after:\n'
    '                      • Checking only header\n'
    '                      • Checking only page 1\n'
    '                      • Finding empty "Buyer\'s Order No" field\n'
    '                      \n'
    '                      ⚠️ If "Buyer\'s Order No." is empty → Continue searching entire document\n'
    '                      ⚠️ Many invoices store PO in Remarks/Footer instead of header\n'
    '                      ⚠️ Last page often contains PO number in footer\n\n'

    
    '  DC_date           → Delivery Challan date\n\n'
    
    '  DC_number         → Delivery Challan number\n\n'
    
    '═══════════════════════ FINANCIAL TOTALS ═══════════════════════\n'
    '\n'
    '  invoice_amount    → Final payable amount\n'
    '                      Labeled: "TO PAY", "Net Amount", "Invoice Amount"\n\n'
    
    '  round_off         → Round off adjustment\n'
    '                      ⚠️ CRITICAL EXTRACTION RULE:\n'
    '                      • ONLY extract if invoice EXPLICITLY shows a field labeled:\n'
    '                        "Round Off", "Roundoff", "R/O", "Adjustment", "Rounding"\n'
    '                      • If NO explicit round-off field exists → round_off = null\n'
    '                      • DO NOT calculate round_off as (Grand Total - To Pay)\n'
    '                      • DO NOT invent round_off to force totals to match\n'
    '                      • Extract the printed value AS-IS (may be negative: -0.26)\n\n'
    
    '  total_gst_rate    → Combined GST % (CGST% + SGST% or IGST%)\n'
    '                      ⚠️ CRITICAL: This is a PERCENTAGE\n'
    '                      Example: 12 (not 240)\n'
    '                      If missing but components available:\n'
    '                      total_gst_rate = total_cgst_rate + total_sgst_rate + total_igst_rate\n\n'
    
    '  total_quantity    → Sum of PAID quantities ONLY (excludes free items)\n'
    '                      ⚠️ CRITICAL BUSINESS RULE:\n'
    '                      • Count ONLY items where free_item_yn = "0" (paid items)\n'
    '                      • DO NOT count items where free_item_yn = "1" (free items)\n'
    '                      • After system splits "20+2" format:\n'
    '                        - Record 1: Paid item (quantity=20, free_item_yn="0") → COUNT\n'
    '                        - Record 2: Free item (quantity=2, free_item_yn="1") → SKIP\n'
    '                      \n'
    '                      Formula: total_quantity = SUM(quantity WHERE free_item_yn != "1")\n'
    '                      \n'
    '                      Example:\n'
    '                      Before split: Item A "20+2", Item B "10+1", Item C "30"\n'
    '                      After split: \n'
    '                        - Item A paid: qty=20, free_item_yn="0"\n'
    '                        - Item A free: qty=2, free_item_yn="1"\n'
    '                        - Item B paid: qty=10, free_item_yn="0"\n'
    '                        - Item B free: qty=1, free_item_yn="1"\n'
    '                        - Item C: qty=30, free_item_yn="0"\n'
    '                      total_quantity = 20 + 10 + 30 = 60 (excludes 2 + 1 = 3 free)\n'
    '                      \n'
    '                      Extract from invoice if explicitly shown.\n'
    '                      If not shown, system will calculate after splitting free items.\n\n'
    
    '  total_cgst_rate   → CGST % from summary\n'
    '                      ⚠️ This is a PERCENTAGE (e.g., 6)\n\n'
    
    '  total_cgst_amount → CGST amount from summary\n'
    '                      ⚠️ This is a MONETARY VALUE (e.g., 120)\n\n'
    
    '  total_sgst_rate   → SGST % from summary\n'
    '                      ⚠️ This is a PERCENTAGE (e.g., 6)\n\n'
    
    '  total_sgst_amount → SGST amount from summary\n'
    '                      ⚠️ This is a MONETARY VALUE (e.g., 120)\n\n'
    
    '  total_igst_rate   → IGST % (null if intra-state)\n'
    '                      ⚠️ This is a PERCENTAGE\n\n'
    
    '  total_igst_amount → IGST amount (0 if intra-state)\n'
    '                      ⚠️ This is a MONETARY VALUE\n\n'
    
    '  total_gst_amount  → Total GST amount\n'
    '                      ⚠️ CRITICAL: Never leave null when CGST and SGST are available\n'
    '                      Calculate: total_gst_amount = total_cgst_amount + total_sgst_amount + total_igst_amount\n\n'
    
    '═══════════════════════ LINE ITEMS ═══════════════════════\n'
    '  Extract every product row from invoice table.\n\n'
    
    '  ⚠️ CRITICAL RULES:\n'
    '  • Merge continuation rows across pages\n'
    '  • Remove ghost/duplicate rows from replica pages\n'
    '  • Extract data only once per item\n\n'

    '  ═══════════════════════ COLUMN ALIGNMENT RULE (VERY IMPORTANT) ═══════════════════════\n'
    '  NEVER confuse adjacent columns.\n'
    '  Read the table header first and map each value to its correct column.\n'
    '  Example:\n'
    '    PCode = AL-01-2350\n'
    '    Pack  = 10 S\n'
    '    CORRECT:   item_code = AL-01-2350,  Pack = 10 S\n'
    '    INCORRECT: Pack = AL-01-2350\n'
    '  Rule: Extract values from the column DIRECTLY UNDER the matching header,\n'
    '  even if OCR spacing is poor. Do NOT shift values left or right.\n'
    '  If unsure which column a value belongs to, use the header label as the\n'
    '  single source of truth — not visual position alone.\n'
    '  ══════════════════════════════════════════════════════════════════════\n\n'
    
    '  ITEM FIELD ORDER (MANDATORY - DO NOT CHANGE):\n\n'
    
    '  description       → Product name\n'
    '                      Copy exactly as shown\n\n'
    
    '  Pack              → Package size/UOM\n'
    '                      Examples: "15 ML", "100ML", "10TAB", "VIAL"\n'
    '                      Copy EXACTLY as printed (with or without spaces)\n\n'
    
    '  Batch             → Batch number\n'
    '                      ⚠️⚠️⚠️ CRITICAL: CHARACTER-LEVEL ACCURACY REQUIRED\n'
    '                      Batch numbers are FREQUENTLY mis-read by OCR.\n'
    '                      READ EACH CHARACTER INDIVIDUALLY.\n'
    '                      \n'
    '                      ⚠️ COMMON BATCH OCR ERRORS:\n'
    '                      • "202532" misread as "202552" (3→5)\n'
    '                      • "202552" misread as "202532" (5→3)\n'
    '                      • "7F28B0602" misread as "71F26B0602" (multiple errors)\n'
    '                      • "8" ↔ "B" confusion (8 has two loops, B has two bumps)\n'
    '                      • "6" ↔ "8" confusion (6 has ONE loop, 8 has TWO)\n'
    '                      • "0" ↔ "O" confusion (check context)\n'
    '                      • "2" ↔ "Z" confusion (rare)\n'
    '                      • "5" ↔ "S" confusion (in alphanumeric context)\n'
    '                      • "3" ↔ "8" confusion (check loop structure)\n'
    '                      \n'
    '                      VERIFICATION PROCESS:\n'
    '                      1. Read printed batch character-by-character\n'
    '                      2. For each ambiguous character:\n'
    '                         - Count loops: 8 has TWO closed loops, 6 has ONE\n'
    '                         - Check shape: 3 is open on left, 8 is closed\n'
    '                         - Verify context: letters vs digits\n'
    '                      3. Copy EXACTLY as printed, do not auto-correct\n'
    '                      \n'
    '                      EXAMPLE CORRECTIONS:\n'
    '                      Invoice shows: "202552" carefully\n'
    '                      Verify digit 4: Is it "5" (curved) or "3" (angular)?\n'
    '                      If invoice prints "202552" → extract "202552"\n'
    '                      If invoice prints "202532" → extract "202532"\n'
    '                      DO NOT guess or swap automatically\n'
    '                      \n'
    '                      ⚠️ CRITICAL OCR CORRECTION:\n'
    '                      If batch contains these special characters: < > $ # @ & |\n'
    '                      Replace them with: -\n'
    '                      \n'
    '                      ⚠️ IMPORTANT - PRESERVE "/" (forward slash):\n'
    '                      "/" is VALID in pharmaceutical batch numbers\n'
    '                      Examples:\n'
    '                      • "3220-3461-100/25-26" → KEEP AS-IS (/ is valid)\n'
    '                      • "AB/CD/123" → KEEP AS-IS\n'
    '                      • "AB<123" → "AB-123" (< replaced)\n'
    '                      • "AB>123" → "AB-123" (> replaced)\n'
    '                      • "AB$123" → "AB-123" ($ replaced)\n'
    '                      • "AB#123" → "AB-123" (# replaced)\n'
    '                      • "AB@123" → "AB-123" (@ replaced)\n'
    '                      • "AB&123" → "AB-123" (& replaced)\n'
    '                      • "AB|123" → "AB-123" (| replaced)\n'
    '                      \n'
    '                      Do NOT replace: "/" or "-" (hyphens are valid)\n'
    '                      This correction applies ONLY to Batch field\n\n'
    '                      ⚠️ I vs 1 RULE FOR BATCH (CRITICAL):\n'
    '                      Batch numbers are ALPHANUMERIC — they mix letters AND digits.\n'
    '                      A character that looks like "I" or "1" MUST be identified by its\n'
    '                      surrounding characters:\n'
    '                      • If surrounded by LETTERS (e.g., RUA_2505A) → it is letter "I"\n'
    '                        "RUA12505A" is WRONG → correct is "RUAI2505A"\n'
    '                      • If surrounded by DIGITS (e.g., AB_2505) → it is digit "1"\n'
    '                        "AB12505" is correct\n'
    '                      • Same rule applies to: 0↔O, 8↔B, 5↔S, 2↔Z\n'
    '                      ALWAYS read the characters before AND after to decide.\n'
    '                      NEVER default to digit "1" when letter "I" fits the pattern.\n\n'
    
    '  quantity          → Quantity\n'
    '                      If contains "+": extract as STRING: "20+2"\n'
    '                      If plain number: extract as NUMBER: 40\n\n'
    
    '  free_item_yn      → "0" for paid items, "1" for free items\n'
    '                      System will split free items later\n\n'
    
    '  unit_price        → Per-unit price\n\n'
    
    '  total_price       → Final billed amount per row (AFTER GST included)\n'
    '                      ⚠️ CRITICAL COLUMN MAPPING:\n'
    '                      "NET AMT" → total_price (post-GST final amount)\n'
    '                      "AMOUNT" → total_price (if it is final billed amount)\n'
    '                      "NET AMOUNT" → total_price\n'
    '                      \n'
    '                      Do NOT map:\n'
    '                      "TAXABLE AMT" → taxable_value (not total_price)\n'
    '                      "TAXABLE" → taxable_value (not total_price)\n'
    '                      \n'
    '                      ⚠️ RATE COLUMN WARNING:\n'
    '                      Some invoices have TWO rate columns:\n'
    '                      "Rate (Incl. of Tax)" = MRP rate with GST (DO NOT use for unit_price)\n'
    '                      "Rate" = selling rate without GST (USE this for unit_price)\n'
    '                      \n'
    '                      Copy total_price EXACTLY from AMOUNT column\n'
    '                      Do NOT calculate: Value + GST\n'
    '                      Do NOT recalculate or adjust\n\n'

    
    '  reference_number  → Part No / Ref No (if present)\n\n'
    
    '  hsn_sac           → 8-digit HSN code\n\n'
    
    '  item_code         → Item code / Prod Code / RACK / PC CODE / DMH\n'
    '                      Standard format: AL-XX-XXXX (AL-[2 digits]-[4 digits])\n'
    '                      Examples: AL-01-7005, AL-02-0378, AL-05-0972\n'
    '                      Also called: Product Code, Prod Code, Item Code\n\n'
    '                      ⚠️⚠️⚠️ CRITICAL DMH COLUMN MAPPING:\n'
    '                      When invoice has a column labeled "DMH":\n'
    '                      • DMH column value → item_code field (NOT reference_number)\n'
    '                      • Extract the exact value from the DMH cell\n'
    '                      • Example: DMH="AL-01-7005" → "item_code": "AL-01-7005"\n'
    '                      \n'
    '                      Column name variations:\n'
    '                      • RACK → item_code\n'
    '                      • DMH → item_code\n'
    '                      • PC CODE → item_code\n'
    '                      • ITEM CODE → item_code\n'
    '                      \n'
    '                      Blank values are valid:\n'
    '                      • If DMH/RACK cell is blank → "item_code": ""\n'
    '                      • Still extract the entire item row\n'
    '                      \n'
    '                      May have different names on different invoices\n\n'
    
    '  expiry_date       → Expiry date\n'
    '                      ⚠️⚠️⚠️ CRITICAL: Extract EXACTLY as shown on invoice.\n'
    '                      DO NOT convert formats. DO NOT calculate days from MM/YY.\n'
    '                      \n'
    '                      Examples:\n'
    '                      Invoice shows "04/29"      → Extract "04/29" (not "30-04-2029")\n'
    '                      Invoice shows "02/28"      → Extract "02/28" (not "29-02-2028")\n'
    '                      Invoice shows "28-02-25"   → Extract "28-02-25"\n'
    '                      Invoice shows "1-Dec-30"   → Extract "1-Dec-30"\n'
    '                      Invoice shows "30/12/2030" → Extract "30/12/2030"\n'
    '                      \n'
    '                      Application code will normalize date formats later.\n'
    '                      Your job: copy the date value EXACTLY as printed.\n\n'
    '                      \n'
    '                      YEAR CONVERSION:\n'
    '                      • "30" → "2030" (20XX for pharma expiry dates)\n'
    '                      • "29" → "2029"\n'
    '                      • "2030" → "2030" (already 4 digits)\n'
    '                      \n'
    '                      EXAMPLES:\n'
    '                      Invoice shows "1-Dec-30" → Extract "01-12-2030"\n'
    '                      Invoice shows "30/08/2030" → Extract "30-08-2030"\n'
    '                      Invoice shows "11/30" → Extract "30-11-2030"\n'
    '                      \n'
    '                      ⚠️ DO NOT OUTPUT:\n'
    '                      • "1-Dec-30" (wrong - not DD-MM-YYYY)\n'
    '                      • "30/12/2030" (wrong separator - use hyphen not slash)\n'
    '                      • "2030-12-30" (wrong order - DD-MM-YYYY not YYYY-MM-DD)\n'
    '                      \n'
    '                      ALWAYS OUTPUT: DD-MM-YYYY with hyphens\n'
    '                      Example: "01-12-2030", "31-08-2030"\n\n'
    
    '  Discount          → Discount value (percentage or amount)\n'
    '                      ⚠️ CRITICAL: Extract from ANY discount-related column:\n'
    '                      Valid discount column names (look for any of these):\n'
    '                      - Disc, DISC, Disc%, DISC%\n'
    '                      - DIS, DIS%, DIS QTY\n'
    '                      - CD, CD%, CD AMT\n'
    '                      - CASH DISCOUNT, DISC AMT, DISC %\n'
    '                      \n'
    '                      NEVER extract from:\n'
    '                      - QTY, RATE, AMOUNT, TAXABLE, CGST, SGST, MRP, PACK, BATCH\n'
    '                      \n'
    '                      If discount column has a numeric value → extract it.\n'
    '                      If discount column is EMPTY/BLANK/ZERO/0.00 → Discount: null\n'
    '                      \n'
    '                      Store the value exactly as shown:\n'
    '                      - If column is "Dis", "Disc", "DISC", "Disc%", "CD%" → it is a percentage\n'
    '                      - If column is "DISC AMT", "CD AMT" → it is an amount\n'
    '                      \n'
    '                      ⚠️ SMALL DECIMAL = PERCENTAGE, NOT AMOUNT:\n'
    '                      If Discount value is a small decimal like 0.60, 5.00, 2.5 and\n'
    '                      the column is "Dis" or "Disc" → it is a PERCENTAGE (0.60%)\n'
    '                      NOT a rupee amount.\n'
    '                      Verify: qty × rate × (1 - Discount/100) should equal TAXABLE AMT\n'
    '                      Example: 20 × 1815.25 × (1 - 0.60/100) = 36,087.17 ✓\n'
    '                      \n'
    '                      Examples from real invoices:\n'
    '                      Disc column = 5   → Discount: 5, Discount_type: "percent"\n'
    '                      CD% column = 5    → Discount: 5, Discount_type: "percent"\n'
    '                      "CD AMT: 401.79"  → Discount: 401.79, Discount_type: "amount"\n'
    '                      Disc column = 0 or blank → Discount: null, Discount_type: null\n\n'
    
    '  Discount_type     → Type of discount value\n'
    '                      ⚠️ MANDATORY when Discount is not null\n'
    '                      \n'
    '                      Rules:\n'
    '                      - Column "Dis", "Disc", "DISC", "DISC%", "CD%", "DIS%", "DISC %" → "percent"\n'
    '                      - Column "DISC AMT", "CD AMT", "DISC AMOUNT", "CASH DISC" → "amount"\n'
    '                      - If unclear → "percent" (default assumption)\n'
    '                      - If Discount is null → Discount_type is null\n'
    '                      \n'
    '                      Values:\n'
    '                      - "percent" = rate (e.g., 5 means 5%)\n'
    '                      - "amount" = rupees (e.g., 401.79 means ₹401.79)\n\n'

    
    '  Value             → Item-level value/taxable amount BEFORE GST\n'
    '                      ⚠️ CRITICAL: Extract from the "Value" column when it exists\n'
    '                      \n'
    '                      Rules:\n'
    '                      - If invoice has a "Value" column → extract it\n'
    '                      - If invoice has NO "Value" column → null\n'
    '                      - Never copy taxable_value into Value\n'
    '                      - Never assume Value = taxable_value\n'
    '                      - If both columns missing → both null\n'
    '                      \n'
    '                      Value represents pre-GST subtotal for THIS ITEM ONLY\n'
    '                      NEVER return null when a "Value" column is visible in the table\n\n'

    
    '  Gst%              → GST rate for this item\n'
    '                      ⚠️ This is a PERCENTAGE (e.g., 5, 12, 18)\n\n'
    
    '  MRP               → Maximum Retail Price\n\n'
    
    '  cgst_rate         → CGST % for this item\n'
    '                      ⚠️ This is a PERCENTAGE\n\n'
    
    '  cgst_amount       → CGST amount for this item\n'
    '                      ⚠️ This is a MONETARY VALUE\n'
    '                      ⚠️ COPY EXACTLY from invoice - NEVER calculate\n'
    '                      Exception: If tax shown only at footer, system will split proportionally\n\n'

    
    '  sgst_rate         → SGST % for this item\n'
    '                      ⚠️ This is a PERCENTAGE\n\n'
    
    '  sgst_amount       → SGST amount for this item\n'
    '                      ⚠️ This is a MONETARY VALUE\n\n'
    
    '  igst_rate         → IGST % (null if intra-state)\n'
    '                      ⚠️ This is a PERCENTAGE\n\n'
    
    '  igst_amount       → IGST amount (null if intra-state)\n'
    '                      ⚠️ This is a MONETARY VALUE\n\n'
    
    '  GST_AMT           → Total GST for this item\n'
    '                      ⚠️ CRITICAL: Never leave null when CGST and SGST available\n'
    '                      If missing: GST_AMT = cgst_amount + sgst_amount\n'
    '                      Extract from GST_AMT column if present\n\n'
    
    '  taxable_value     → Taxable value (after discounts, before GST)\n'
    '                      ⚠️ Different from Value field\n'
    '                      \n'
    '                      Common column names:\n'
    '                      - "TAXABLE AMT" → taxable_value\n'
    '                      - "TAXABLE" → taxable_value\n'
    '                      - "TAXABLE VALUE" → taxable_value\n'
    '                      \n'
    '                      Do NOT use as total_price\n'
    '                      Do NOT copy into Value field\n\n'

    
    '═══════════════════════ GST CALCULATION RULES ═══════════════════════\n'
    '⚠️ MANDATORY:\n\n'
    
    'GST rates must ALWAYS be percentages.\n'
    'GST amounts must ALWAYS be monetary values.\n'
    'Never place percentages into amount fields.\n'
    'Never place amounts into rate fields.\n\n'
    
    'Example:\n'
    '  GST Rate = 12 (percentage)\n'
    '  CGST Rate = 6 (percentage)\n'
    '  SGST Rate = 6 (percentage)\n'
    '  GST Amount = 240 (monetary)\n'
    '  CGST Amount = 120 (monetary)\n'
    '  SGST Amount = 120 (monetary)\n\n'
    
    'If GST_AMT is missing but CGST and SGST exist:\n'
    '  GST_AMT = cgst_amount + sgst_amount\n\n'
    
    'If total_gst_amount is missing:\n'
    '  total_gst_amount = total_cgst_amount + total_sgst_amount + total_igst_amount\n\n'
    
    'If total_gst_rate is missing:\n'
    '  total_gst_rate = total_cgst_rate + total_sgst_rate + total_igst_rate\n\n'
    
    '═══════════════════════ JSON TEMPLATE ═══════════════════════\n'
    'Output MUST follow this EXACT field order:\n\n'
    '{\n'
    '  "invoice_id": null,\n'
    '  "invoice_number": null,\n'
    '  "invoice_date": null,\n'
    '  "due_date": null,\n'
    '  "customer_name": null,\n'
    '  "customer_gstin": null,\n'
    '  "seller_name": null,\n'
    '  "seller_gstin": null,\n'
    '  "currency_code": "INR",\n'
    '  "PO_number": null,\n'
    '  "DC_date": null,\n'
    '  "DC_number": null,\n'
    '  "invoice_amount": null,\n'
    '  "round_off": null,\n'
    '  "total_gst_rate": null,\n'
    '  "total_quantity": 0,\n'
    '  "total_cgst_rate": null,\n'
    '  "total_cgst_amount": null,\n'
    '  "total_sgst_rate": null,\n'
    '  "total_sgst_amount": null,\n'
    '  "total_igst_rate": null,\n'
    '  "total_igst_amount": 0,\n'
    '  "total_gst_amount": null,\n'
    '  "items": [\n'
    '    {\n'
    '      "description": null,\n'
    '      "Pack": null,\n'
    '      "Batch": null,\n'
    '      "quantity": 0,\n'
    '      "free_item_yn": "0",\n'
    '      "unit_price": 0,\n'
    '      "total_price": 0,\n'
    '      "reference_number": null,\n'
    '      "hsn_sac": null,\n'
    '      "item_code": null,\n'
    '      "expiry_date": null,\n'
    '      "Discount": null,\n'
    '      "Discount_type": null,\n'
    '      "Value": null,\n'
    '      "Gst%": null,\n'
    '      "MRP": null,\n'
    '      "cgst_rate": null,\n'
    '      "cgst_amount": null,\n'
    '      "sgst_rate": null,\n'
    '      "sgst_amount": null,\n'
    '      "igst_rate": null,\n'
    '      "igst_amount": null,\n'
    '      "GST_AMT": null,\n'
    '      "taxable_value": null\n'
    '    }\n'
    '  ]\n'
    '}\n\n'
    
    '═══════════════════════ TOTALS SECTION ═══════════════════════\n'
    '  Extract from the invoice summary/totals section (after line items table).\n'
    '  Look for highlighted row/box with: "Total", "Net Amount", "TO PAY", "Grand Total"\n\n'

    '  taxable_amount    → TAXABLE / TAXABLE AMT (after all discounts, before GST)\n'
    '  total_cess_amount → CESS total from summary, else 0\n'
    '  invoice_amount    → Valid labels: "NET" / "NET AMOUNT" / "TO PAY" / "TOTAL PAYABLE"\n'
    '                                   / "AMOUNT PAYABLE" / "GRAND TOTAL" / "FINAL AMOUNT"\n'
    '                                   / "BALANCE PAYABLE"\n'
    '                      Extract the FINAL payable amount EXACTLY as printed\n\n'

    '═══════════════════════ FREE ITEM HANDLING (MANDATORY) ═══════════════════════\n'
    '⚠️ SEMANTIC FREE ITEM DETECTION - Do NOT rely only on "+" symbol!\n\n'
    'DETECT PROMOTIONAL QUANTITIES SEMANTICALLY:\n'
    'Look for ANY column that indicates free/promotional quantities.\n\n'
    'POSSIBLE COLUMN NAMES FOR FREE QUANTITIES:\n'
    '  • FREE, FREE QTY, F.QTY\n'
    '  • BONUS, BONUS QTY\n'
    '  • SCHEME, SCH, SCH QTY\n'
    '  • DISC QTY, DISCOUNT QTY\n'
    '  • PROMO, PROMOTIONAL\n'
    '  • Or "20+2" format in quantity column\n\n'
    'EXTRACTION RULES:\n'
    '1. Default: set free_item_yn = "0" for every item.\n'
    '2. If ANY free quantity exists for a line item → set free_item_yn = "1".\n'
    '3. "+" format in quantity column (e.g., "20+2"):\n'
    '   → quantity: "20+2" (keep as string), free_item_yn: "1"\n'
    '   → The system will split this into separate paid/free records later.\n'
    '4. Separate FREE/BONUS/SCH/DISC QTY column:\n'
    '   → quantity: <paid qty as number>, free_quantity: <free qty as number>, free_item_yn: "1"\n'
    '   → If the FREE column is blank/empty/zero for that row → free_quantity: null, free_item_yn: "0"\n'
    '5. ⚠️ TWO-ROW FREE ITEM FORMAT (CRITICAL - DO NOT MISS):\n'
    '   Some invoices print free items as TWO separate rows for the SAME product:\n'
    '     Row A: same description, QTY=blank/0, DISC QTY/FREE=10  ← free qty row only\n'
    '     Row B: same description, QTY=100, DISC QTY/FREE=blank   ← paid qty row\n'
    '   RULE: MERGE into ONE item object — do NOT create two separate items:\n'
    '     → quantity: 100 (from Row B paid qty)\n'
    '     → free_quantity: 10 (from Row A free qty column)\n'
    '     → free_item_yn: "1"\n'
    '   The zero-quantity row (Row A) is NOT a standalone item — it only carries free qty.\n'
    '   NEVER output an item with quantity=0 from this two-row pattern.\n\n'
    'EXAMPLES:\n'
    '• Qty=20, FREE=2 → quantity: 20, free_quantity: 2, free_item_yn: "1"\n'
    '• Qty=50, FREE=5 → quantity: 50, free_quantity: 5, free_item_yn: "1"\n'
    '• Qty: "20+2" → quantity: "20+2", free_item_yn: "1"\n'
    '• Qty=100, FREE=(empty) → quantity: 100, free_quantity: null, free_item_yn: "0"\n'
    '• Two rows (QTY=0,DISC=10)+(QTY=100) → ONE item: quantity:100, free_quantity:10, free_item_yn:"1"\n\n'
    '⚠️ CRITICAL: total_quantity = Sum of PAID quantities ONLY\n'
    '• FREE/BONUS/SCHEME quantities are NEVER included in total_quantity\n'
    '• Example: Items are 20+2, 10, 5+1 → total_quantity = 20 + 10 + 5 = 35 (NOT 38)\n\n'

    '═══════════════════════ EXPIRY DATE RULE ═══════════════════════\n'
    '⚠️ CRITICAL RULE FOR expiry_date:\n'
    '• Extract EXACTLY as printed on the invoice — do NOT convert or modify.\n'
    '• If invoice shows "04/29" → extract "04/29" (not "30-04-2029")\n'
    '• If invoice shows "02/28" → extract "02/28" (not "28-02-2028" or "29-02-2028")\n'
    '• If invoice shows "28-02-25" → extract "28-02-25"\n'
    '• DO NOT calculate day from MM/YY format — extract as-is.\n'
    '• Application code will handle format normalization and calendar calculations.\n\n'

    '═══════════════════════ ITEM CODE EXTRACTION (HIGH PRIORITY) ═══════════════════════\n'
    'Extract item_code from the dedicated item code column.\n'
    '\n'
    'COLUMN NAME VARIATIONS (look for any of these headers):\n'
    '  RACK, PCode, P.Code, Item Code, Item No, Product Code, Product ID,\n'
    '  Material Code, Mat Code, SKU, Catalogue No, Cat No, Article No,\n'
    '  Reference Code, Ref Code, Ref No, Code, PC CODE, PCODE\n'
    '\n'
    '⚠️⚠️⚠️ CRITICAL RULE — ITEM CODE INTEGRITY:\n'
    '  • Each item\'s code comes from THAT item\'s row or description ONLY.\n'
    '  • Priority: Column cell → Description brackets → Empty string\n'
    '  • If the item code cell is blank AND no code in description → item_code = ""\n'
    '  • NEVER copy item_code from adjacent rows (above or below).\n'
    '  • NEVER reuse codes between different items.\n'
    '  • Extract the item EVEN IF item_code is blank — blank item_code is valid.\n'
    '  • Use standardized format: AL-XX-XXXX for consistency\n'
    '\n'
    'EXAMPLES:\n'
    '  Row 1: RACK = (blank), Description = "ALTRADAV CAP" → item_code = ""  ← no code found\n'
    '  Row 2: RACK = (blank), Description = "FARONEM (AL-05-0593)" → item_code = "AL-05-0593"  ← from description\n'
    '  Row 3: RACK = "AL-01-0184", Description = "FUCIDIN CREAM" → item_code = "AL-01-0184"  ← from column\n'
    '  Row 4: RACK = "AL-01-3189", Description = "MINOZ TAB (AL-02-9999)" → item_code = "AL-01-3189"  ← column wins\n'
    '\n'
    'DO NOT assign "AL-01-0184" to Row 1 or Row 2 just because it appears later.\n'
    'Each item gets its own code or empty string — never share codes between items.\n\n'
    'NORMALIZATION (when code exists):\n'
    '• Remove spaces around hyphens: "SR -06-3124" → "SR-06-3124"\n'
    '• Join fragments: "SR - 05 -0812" → "SR-05-0812"\n'
    '• Remove surrounding parentheses: "((SR-05-0812))" → "SR-05-0812"\n'
    '• Replace slashes with hyphens: "SR/01/0451" → "SR-01-0451"\n'
    '• Preserve ALL letters and numbers\n\n'

    '══════════════════════════════════════════════════════════════════════\n'
    'GST DERIVATION RULES — UNIVERSAL (works on ANY invoice layout)\n'
    '══════════════════════════════════════════════════════════════════════\n'
    'Apply derivation whenever the direct value is missing. NEVER hardcode any specific rate or amount.\n\n'
    '── Gst% (GST RATE) ──\n'
    'Step 1: Copy directly if invoice has a GST% / GST Rate / Tax Rate / TAX% column.\n'
    'Step 2: If missing → derive:\n'
    '        Gst% = cgst_rate + sgst_rate   (intra-state)\n'
    '        Gst% = igst_rate               (inter-state)\n'
    'Step 3: If still missing → null\n\n'
    '── GST_AMT (TOTAL GST AMOUNT PER LINE ITEM) ──\n'
    '⚠️⚠️⚠️ CRITICAL: DISCOUNT-AWARE GST CALCULATION ⚠️⚠️⚠️\n\n'
    'GST MUST be calculated on taxable_value (AFTER discount), NOT on Value (BEFORE discount).\n\n'
    'Formula when Discount exists:\n'
    '  1. discount_amount = Value × Discount / 100\n'
    '  2. taxable_value = Value - discount_amount\n'
    '  3. GST_AMT = taxable_value × Gst% / 100\n\n'
    'Example: Value=1530.00, Discount=5%, Gst%=5%\n'
    '  discount_amount = 1530.00 × 5 / 100 = 76.50\n'
    '  taxable_value = 1530.00 - 76.50 = 1453.50\n'
    '  GST_AMT = 1453.50 × 5 / 100 = 72.68 ✓ CORRECT\n'
    '  WRONG: GST_AMT = 1530.00 × 5 / 100 = 76.50 ✗\n\n'
    'Extraction Steps:\n'
    'Step 1: Copy directly if invoice has GST Amount / GST Amt / Tax Amount / TAX AMT column.\n'
    'Step 2: If missing → derive: GST_AMT = cgst_amount + sgst_amount + igst_amount\n'
    'Step 3: If still missing but Gst% and taxable_value known: GST_AMT = taxable_value × (Gst% / 100)\n'
    'Step 4: null ONLY if NO GST data exists anywhere on the invoice\n\n'
    '⚠️ NEVER output GST_AMT = 0 when cgst_amount, sgst_amount, or igst_amount is > 0.\n\n'
    '── cgst_rate / sgst_rate / igst_rate ──\n'
    'Step 1: Copy from respective column.\n'
    'Step 2: If missing but Gst% known: cgst_rate = sgst_rate = Gst%/2 (intra); igst_rate = Gst% (inter)\n'
    'Step 3: null\n\n'
    '── cgst_amount / sgst_amount / igst_amount ──\n'
    'Step 1: Copy from respective column.\n'
    'Step 2: If column absent → null (do NOT default to 0)\n\n'
    '── IF ITEM ROW HAS NO GST COLUMNS ──\n'
    'Search the invoice summary / totals section for GST values.\n'
    'If only ONE item exists on the invoice → apply summary GST values directly to that item.\n'
    'NEVER leave GST fields null when the invoice summary contains values.\n\n'
    '── ABSOLUTE RULES ──\n'
    '1. ALWAYS prefer the printed value over any calculation.\n'
    '2. NEVER hardcode specific rates or amounts.\n'
    '3. Preserve exact decimal precision from the invoice.\n'
    '4. NEVER output 0 when component values exist — always sum them.\n'
    '5. Return null only when NO GST data exists anywhere in the document.\n\n'

    '═══════════════════════ VALUE vs TAXABLE VALUE (STRICT RULE) ═══════════════════════\n'
    '⚠️⚠️⚠️ "Value" and "taxable_value" are DIFFERENT fields - never copy one to the other.\n\n'
    '⚠️ STRICT COLUMN COPYING (HIGHEST PRIORITY):\n'
    'If invoice has a TAXABLE column (labeled "TAXABLE", "TAXABLE AMT", "TAXABLE AMOUNT"):\n'
    '  1. Copy TAXABLE column value directly to BOTH Value and taxable_value\n'
    '  2. NEVER calculate: AMOUNT - DISC\n'
    '  3. NEVER use arithmetic\n'
    '  4. Trust the printed TAXABLE value\n\n'
    'Extraction Priority:\n'
    '1. If TAXABLE column exists → Value = TAXABLE (exact copy), taxable_value = TAXABLE (exact copy)\n'
    '2. If NO TAXABLE column → Extract "Value" from item Amount/Value column (if exists)\n'
    '                        → Extract "taxable_value" from invoice GST/tax summary (after discounts)\n'
    '3. For single-item invoices: taxable_value = invoice summary taxable amount\n'
    '4. Only if no taxable value exists anywhere: taxable_value may equal Value\n\n'
    'COLUMN MAPPING (mandatory):\n'
    '• AMOUNT   → Gross amount (do NOT use for taxable_amount)\n'
    '• DISC     → Discount (separate field)\n'
    '• SCHEME   → Scheme Amount (separate field)\n'
    '• CD AMT   → Cash Discount (separate field)\n'
    '• TAXABLE  → taxable_value (copy directly)\n'
    '• CGST     → total_cgst_amount\n'
    '• SGST     → total_sgst_amount\n'
    '• TOTAL    → invoice_amount\n\n'

    '═══════════════════════ FINAL SELF-CHECK (MANDATORY BEFORE OUTPUT) ═══════════════════════\n'
    'Before returning JSON, verify:\n'
    '✓ PO_number searched entire document (ALL pages, remarks, footer)\n'
    '✓ Item codes extracted from description brackets if no column exists\n'
    '✓ Item codes normalized (spaces removed: "SR -06-3124" → "SR-06-3124")\n'
    '✓ Each item has its own unique code or empty string - no sharing\n'
    '✓ Item codes follow AL-XX-XXXX format when present\n'
    '✓ Gst% reconstructed using priority rule (if direct value not available)\n'
    '✓ GST_AMT reconstructed using priority rule (if direct value not available)\n'
    '✓ taxable_value from invoice summary, NOT copied from Value\n'
    '✓ Single-item invoices use summary values for all GST fields\n'
    '✓ No field is null without searching entire invoice first\n'
    'If any check fails, CORRECT before producing final JSON.\n\n'

    '═══════════════════════ FIELD LOCATION REFERENCE ═══════════════════════\n'
    'Fields can appear in MULTIPLE locations. Search the ENTIRE invoice:\n\n'
    '┌─────────────────────┬──────────────────────────────────────────────────┐\n'
    '│ Field               │ Possible Locations                               │\n'
    '├─────────────────────┼──────────────────────────────────────────────────┤\n'
    '│ PO_number           │ • "Buyer\'s Order No." (header)                   │\n'
    '│                     │ • "Customer Ref." (header)                       │\n'
    '│                     │ • "Reference No." (header or body)               │\n'
    '│                     │ • "Remark:" section (any page)                   │\n'
    '│                     │ • Footer notes (any page)                        │\n'
    '│                     │ • Continuation pages (page 2, 3, etc.)           │\n'
    '│                     │ • Terms & Conditions section                     │\n'
    '├─────────────────────┼──────────────────────────────────────────────────┤\n'
    '│ customer_gstin      │ • Buyer block header                             │\n'
    '│                     │ • Ship-to block                                  │\n'
    '│                     │ • Customer details section                       │\n'
    '├─────────────────────┼──────────────────────────────────────────────────┤\n'
    '│ seller_gstin        │ • Company header (top left)                      │\n'
    '│                     │ • Seller details block                           │\n'
    '│                     │ • Footer (bottom of page)                        │\n'
    '├─────────────────────┼──────────────────────────────────────────────────┤\n'
    '│ DC_number           │ • Dispatch section                               │\n'
    '│                     │ • Delivery details block                         │\n'
    '│                     │ • Remarks/Notes section                          │\n'
    '│                     │ • Footer (any page)                              │\n'
    '└─────────────────────┴──────────────────────────────────────────────────┘\n\n'
    '⚠️ KEY PRINCIPLE: Think DOCUMENT-LEVEL, not REGION-LEVEL\n'
    '  Bad approach: "PO number must come from header → search only header"\n'
    '  Good approach: "PO number may appear anywhere → search entire invoice"\n\n'

    '═══════════════════════ BATCH-LEVEL RULES ═══════════════════════\n'
    '  • Each DISTINCT batch = ONE separate item object\n'
    '  • Do NOT combine batches\n\n'

    '═══════════════════════ FINAL REMINDERS ═══════════════════════\n'
    '• Output ONLY valid JSON\n'
    '• First character MUST be {\n'
    '• Follow EXACT field order\n'
    '• Read ALL pages before extraction\n'
    '• Remove duplicate copy pages\n'
    '• Merge continuation pages\n'
    '• Extract data only once\n'
    '• Never duplicate items from replica pages\n'
    '• GST rates = percentages, GST amounts = monetary values\n'
    '• Customer name = organization only (no address)\n'
    '• PO number = exact copy (no spaces inserted)\n'
    '• total_quantity = sum of PAID quantities only (excludes free items where free_item_yn="1")\n'
    '• Batch = OCR-corrected (replace <>$#@&| with -, but PRESERVE /)\n'
    '• invoice_id = always null (generated later)\n'
    '• Discount = extract from discount columns only\n'
    '• Value ≠ taxable_value (different fields)\n'
    '• total_price = copy from AMOUNT column (not TAXABLE AMT)\n'
    '• COLUMN ALIGNMENT: Always read table header first; map each value to the column\n'
    '  DIRECTLY UNDER its header. Never shift values between adjacent columns.\n'
    '  Example: PCode=AL-01-2350, Pack=10 S → item_code="AL-01-2350", Pack="10 S" (not swapped)\n'
)


def get_extraction_prompt(image_context: str = "") -> tuple[str, str]:
    """
    Get the system and user prompts for invoice extraction.
    
    Args:
        image_context: Additional context about the image
    
    Returns:
        Tuple of (system_prompt, user_prompt)
    """
    user_prompt_with_context = USER_PROMPT
    if image_context:
        user_prompt_with_context = f"{image_context}\n\n{USER_PROMPT}"
    
    return SYSTEM_PROMPT, user_prompt_with_context


# ─────────────────────────────────────────────────────────────────────────────
# TWO-PASS EXTRACTION PROMPTS (for extract_invoice_two_pass)
# ─────────────────────────────────────────────────────────────────────────────

def get_header_prompt() -> tuple[str, str]:
    """
    Get prompts for extracting header fields only (Pass 1a).
    Returns: (system_prompt, user_prompt)
    """
    system_prompt = (
        "You are an invoice data extraction engine. Extract ONLY header fields.\n"
        "Output ONLY valid JSON. First character MUST be {.\n"
        "No markdown, no explanation, no preamble.\n"
        "CRITICAL: Extract from the CURRENT invoice ONLY. Never use memory, cached values,\n"
        "or information from previous invoices. Every value must come from this invoice's OCR.\n"
        "SELLER vs CUSTOMER: Never confuse seller and customer. Associate each GSTIN with\n"
        "the correct company block. Never swap seller and customer GSTINs.\n"
        "PO NUMBER: Search ENTIRE document — header, footer, remarks, notes, all pages.\n"
        "Never return null after checking only the header or page 1.\n"
        "OCR CHARACTER CONFUSION — applies to ALL fields (names, GSTINs, invoice numbers, etc.):\n"
        "  1↔I↔l  0↔O  8↔B  5↔S  2↔Z  6↔G  4↔A  U↔V\n"
        "  Use field context to resolve: digits expected → letter shape is a digit; word context → digit shape is a letter.\n"
        "  Examples: 'PHARMAACEUTICAL' → 'PHARMACEUTICAL' (extra U) | GSTIN pos 1-2 always digits so 'O'→'0'\n"
        "  When truly ambiguous → copy exactly as printed, do NOT guess.\n"
        "NEIGHBOUR RULE for alphanumeric fields (invoice numbers, PO numbers, DC numbers):\n"
        "  Check the characters on BOTH SIDES of an ambiguous character.\n"
        "  • If the ambiguous char is surrounded by digits  → treat it as a DIGIT.\n"
        "    e.g.  KP2620B030 → the 'B' is between digits → KP26208030\n"
        "  • If the ambiguous char is surrounded by letters → treat it as a LETTER.\n"
        "    e.g.  KUNOAN → 'O' between letters → KUNDAN\n"
        "  • At a digit↔letter BOUNDARY, use the majority context of the surrounding block.\n"
        "GSTIN STRUCTURE RULE (15 characters, fixed layout):\n"
        "  Positions 1-2   : always DIGITS   (state code)  — 'O'→'0', 'I'→'1', 'S'→'5', 'B'→'8'\n"
        "  Positions 3-7   : always LETTERS  (PAN prefix)  — '0'→'O', '1'→'I', '5'→'S', '8'→'B'\n"
        "  Positions 8-11  : always DIGITS   (PAN digits)  — same digit fixes\n"
        "  Position  12    : always a LETTER (PAN suffix)  — same letter fixes\n"
        "  Position  13    : always a DIGIT  (entity no.)  — same digit fixes\n"
        "  Position  14    : always a LETTER (check letter)— same letter fixes\n"
        "  Apply these positional corrections before outputting any GSTIN.\n"
    )
    
    user_prompt = (
        "Extract ONLY these header fields from the invoice:\n\n"
        "{\n"
        '  "invoice_id": null,\n'
        '  "invoice_number": null,\n'
        '  "invoice_date": null,\n'
        '  "due_date": null,\n'
        '  "customer_name": null,\n'
        '  "customer_gstin": null,\n'
        '  "seller_name": null,\n'
        '  "seller_gstin": null,\n'
        '  "currency_code": "INR",\n'
        '  "PO_number": null,\n'
        '  "DC_date": null,\n'
        '  "DC_number": null\n'
        "}\n\n"
        "Rules:\n"
        "- invoice_id: Always null\n"
        "- customer_name: Organization name only (no address)\n"
        "- GSTIN: Must be exactly 15 characters or null\n"
        "- PO_number: ⚠️ MANDATORY FULL DOCUMENT SEARCH:\n"
        "  Search the ENTIRE invoice. Do NOT search only header. Do NOT stop after page 1.\n"
        "  Before returning null, inspect EVERY page from top to bottom.\n"
        "  \n"
        "  Search ALL locations:\n"
        "  1. Invoice Header (Buyer's Order No., PO No., P.O. No., Order No., Customer PO, Client PO)\n"
        "  2. Footer (any page)\n"
        "  3. Remarks / Remark\n"
        "  4. Notes\n"
        "  5. Additional Information\n"
        "  6. Customer Reference / Ref No.\n"
        "  7. Internal Reference\n"
        "  8. Last page footer\n"
        "  9. Anywhere in free text\n"
        "  \n"
        "  PO may appear under ANY label or in free text.\n"
        "  \n"
        "  Examples:\n"
        '  "Order No : DMH/PO/dmhmss/2026-27/7600" → PO_number = "DMH/PO/dmhmss/2026-27/7600"\n'
        '  "Remark : DMH/PO/dmhmss/2026-27/8019" → PO_number = "DMH/PO/dmhmss/2026-27/8019"\n'
        '  "Customer Ref : DMH/PO/PHRMCY/2026-27/3906" → PO_number = "DMH/PO/PHRMCY/2026-27/3906"\n'
        "  \n"
        "  NEVER return null after checking only header or page 1.\n"
        "  If 'Buyer's Order No.' is empty → Continue searching entire document.\n"
        "  Return null ONLY if ENTIRE DOCUMENT searched and no PO reference exists.\n"
        "  \n"
        "  Pattern matching (extract if found):\n"
        "  • */PO/*\n"
        "  • DMH/PO/*\n"
        "  • */PO/*/*\n"
        "  • PO/<department>/<year>/<number>\n"
        "  PO does NOT need field label. May appear in Remark, Footer, Notes, or any free-text.\n"
        "  \n"
        "  DOCUMENT SEARCH WORKFLOW:\n"
        "  Step 1: Read every page\n"
        "  Step 2: Locate all header fields\n"
        "  Step 3: Locate all totals\n"
        "  Step 4: Locate all remarks\n"
        "  Step 5: Locate all footer text\n"
        "  Step 6: Locate all references\n"
        "  Step 7: Populate JSON\n"
        "  Never populate PO_number before document scan complete.\n"
        "  Never return null until every page searched.\n"
        "- customer_name: Organization name only (no address)\n"
        "- GSTIN: Must be exactly 15 characters or null\n"
        "- Copy text character-by-character, no modifications\n"
    )
    
    return system_prompt, user_prompt


def get_totals_prompt() -> tuple[str, str]:
    """
    Get prompts for extracting totals fields only (Pass 1b).
    Returns: (system_prompt, user_prompt)
    """
    system_prompt = (
        "You are an invoice data extraction engine. Extract ONLY financial totals.\n"
        "Output ONLY valid JSON. First character MUST be {.\n"
        "No markdown, no explanation, no preamble.\n"
        "CRITICAL: Extract from the CURRENT invoice ONLY. Never use memory, cached values,\n"
        "or information from previous invoices. Every value must come from this invoice's OCR.\n"
        "GST%: If not printed, derive as CGST Rate + SGST Rate + IGST Rate. Never return null\n"
        "when component rates are available.\n"
        "GST_AMT: Never return 0 when CGST/SGST/IGST amounts exist — sum them.\n"
    )
    
    user_prompt = (
        "Extract ONLY these financial total fields from the invoice:\n\n"
        "{\n"
        '  "invoice_amount": null,\n'
        '  "round_off": null,\n'
        '  "total_gst_rate": null,\n'
        '  "total_quantity": 0,\n'
        '  "total_cgst_rate": null,\n'
        '  "total_cgst_amount": null,\n'
        '  "total_sgst_rate": null,\n'
        '  "total_sgst_amount": null,\n'
        '  "total_igst_rate": null,\n'
        '  "total_igst_amount": 0,\n'
        '  "total_gst_amount": null\n'
        "}\n\n"
        "Rules:\n"
        "- Rates are PERCENTAGES (e.g., 6, 12, 18)\n"
        "- Amounts are MONETARY VALUES (e.g., 120.50, 1775.00)\n"
        "- Remove commas from numbers\n"
        "- If total_gst_amount missing: calculate as cgst + sgst + igst\n"
        "- total_quantity = Sum of PAID quantities ONLY (exclude free items after '+')\n"
        "  • If invoice shows '20+2', only count 20\n"
        "  • Even if invoice prints 'Total Qty: 38', use the calculated paid-only value\n"
        "- Extract from SUMMARY/TOTALS section (after line items table)\n"
        "- Look for: 'Total', 'Grand Total', 'TO PAY', 'Net Amount'\n"
        "- taxable_amount: from 'TAXABLE', 'TAXABLE AMT', 'ASSESSABLE VALUE'\n"
        "- invoice_amount: from 'TO PAY', 'NET AMOUNT', 'GRAND TOTAL'\n"
    )
    
    return system_prompt, user_prompt


def get_items_prompt() -> tuple[str, str]:
    """
    Get prompts for extracting line items only (Pass 2).
    Returns: (system_prompt, user_prompt)
    """
    system_prompt = (
        "You are an invoice data extraction engine with ITEM CODE REASONING enabled.\n"
        "Output ONLY valid JSON. First character MUST be {.\n"
        "No markdown, no explanation, no preamble.\n\n"
        
        "🧠 CRITICAL: REASONING FOR ITEM CODES (Prevent Mismatches):\n"
        "Before assigning ANY item_code, reason through:\n"
        "1. Which row/item am I processing right now?\n"
        "2. Does THIS specific row have an item code column (RACK/DMH/PCode/Prod Code)? What value?\n"
        "3. If column is blank, does THIS row's description contain AL-XX-XXXX format?\n"
        "4. NEXT-LINE CHECK: Is there a 'Prod Code : AL-XX-XXXX' annotation on the line\n"
        "   IMMEDIATELY BELOW this item's row? If yes → that code belongs to THIS item.\n"
        "5. Is this code from THIS item or did I accidentally copy from another row?\n"
        "6. Have I already used this code for a different item?\n"
        "7. SPECIAL: If single item invoice, is the code embedded in the product name?\n"
        "8. SPECIAL: If multi-item with mixed codes, am I respecting blank cells?\n\n"

        "⚠️ NEXT-LINE 'Prod Code' ANNOTATION FORMAT (VERY COMMON):\n"
        "Some invoices print the item code on a separate line directly below the item row:\n"
        "  Row:       Pantocid H P Tab (GH)   SR  30049039  Tab  FJD0022  ...  8724.87\n"
        "  Next line:  Prod Code : AL-01-3576.\n"
        "RULE: The 'Prod Code : AL-XX-XXXX' line is NOT a separate item.\n"
        "      It is the item_code for the item row DIRECTLY ABOVE it.\n"
        "      Extract the code and assign it to that item. Strip trailing dots.\n"
        "      Do NOT create a new item object for this line.\n"
        "      Do NOT leave item_code blank because the code wasn't in the main row.\n\n"
        "EXAMPLES of this pattern:\n"
        "  'Prod Code : AL-01-3576.' → item_code = 'AL-01-3576'  (for the item above)\n"
        "  'Prod Code : AL-01-2585'  → item_code = 'AL-01-2585'  (for the item above)\n"
        "  'Prod Code : AL-01-2799'  → item_code = 'AL-01-2799'  (for the item above)\n"
        "  'Prod Code : AL-01-6603'  → item_code = 'AL-01-6603'  (for the item above)\n"
        "  'Prod Code : AL-01-3611.' → item_code = 'AL-01-3611'  (for the item above)\n\n"

        "🚨 ITEM CODE RULES:\n"
        "• Each item gets its OWN code or empty string - never share\n"
        "• Standard format: AL-[2 digits]-[4 digits] (e.g., AL-01-7005)\n"
        "• Priority: Column cell → Next-line 'Prod Code' annotation → Description brackets → Empty string\n"
        "• NEVER copy codes between different items\n"
        "• Also called: Prod Code, Product Code, Item Code\n\n"

        "⚠️ SIDE-BY-SIDE DUPLICATE LAYOUT (very common in Indian pharma invoices):\n"
        "Some invoices print TWO copies of the item table side by side on the same page:\n"
        "  LEFT HALF  = Customer Copy  |  RIGHT HALF = Office Copy / Hospital Copy\n"
        "Both halves contain IDENTICAL items with the same batches, quantities, rates.\n"
        "RULE: Extract items from ONE side only (the left/first occurrence).\n"
        "DO NOT extract the same item twice just because it appears in both halves.\n"
        "Signal: if you see the same product name + batch + qty appear again in the\n"
        "right portion of the same page → it is the duplicate copy, skip it.\n\n"
        
        "CRITICAL: Extract from the CURRENT invoice ONLY. Never use memory, cached values,\n"
        "or information from previous invoices. Every value must come from this invoice's OCR.\n"
        "COLUMN ALIGNMENT: Read table header first. Map each value to the column DIRECTLY UNDER\n"
        "its header. Never shift values between adjacent columns.\n"
        "GST%: Derive as CGST+SGST if not printed. Never null when rates are available.\n"
        "GST_AMT: Never 0 when component amounts exist — sum them.\n"
        "PACK: Normalize — add space between number and unit (10S→10 S, 10TAB→10 TAB).\n"
        "EXPIRY DATE: Always DD-MM-YYYY. Convert MM/YY format.\n"
        "OCR CHARACTER CONFUSION — applies to ALL fields (batch, description, item code, etc.):\n"
        "  1↔I↔l  0↔O  8↔B  5↔S  2↔Z  6↔G  4↔A  U↔V\n"
        "  Use field context to resolve: digits expected → letter shape is a digit; word context → digit shape is a letter.\n"
        "  BATCH RULE (most important): check the NEIGHBOURS of the ambiguous character.\n"
        "    If surrounded by LETTERS → it is a LETTER. e.g., RUA?2505A → 'RUAI2505A' (NOT 'RUA12505A')\n"
        "    If surrounded by DIGITS  → it is a DIGIT.  e.g., AB?2505  → 'AB12505'\n"
        "  Examples: 'B928.00' in amount → '8928.00' | 'PHARMAACEUTICAL' → 'PHARMACEUTICAL' (extra U)\n"
        "  When truly ambiguous → copy exactly as printed, do NOT guess.\n"
    )
    
    user_prompt = (
        "Extract ALL line items from the invoice table.\n\n"
        "Output format:\n"
        "{\n"
        '  "items": [\n'
        "    {\n"
        '      "description": null,\n'
        '      "Pack": null,\n'
        '      "Batch": null,\n'
        '      "quantity": 0,\n'
        '      "free_quantity": null,\n'
        '      "free_item_yn": "0",\n'
        '      "unit_price": 0,\n'
        '      "total_price": 0,\n'
        '      "reference_number": null,\n'
        '      "hsn_sac": null,\n'
        '      "item_code": null,\n'
        '      "expiry_date": null,\n'
        '      "Discount": null,\n'
        '      "Discount_type": null,\n'
        '      "Value": null,\n'
        '      "Gst%": null,\n'
        '      "MRP": null,\n'
        '      "cgst_rate": null,\n'
        '      "cgst_amount": null,\n'
        '      "sgst_rate": null,\n'
        '      "sgst_amount": null,\n'
        '      "igst_rate": null,\n'
        '      "igst_amount": null,\n'
        '      "GST_AMT": null,\n'
        '      "taxable_value": null\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- ⚠️⚠️⚠️ CRITICAL: Extract EVERY product row from invoice table\n"
        "- ⚠️⚠️⚠️ ITEM CODE REASONING (MANDATORY):\n"
        "  For each item, THINK: Does THIS row have its own code?\n"
        "  Step 1: Check column (DMH/RACK/PCode/Prod Code) for THIS row\n"
        "  Step 2: Check line IMMEDIATELY BELOW this row for 'Prod Code : AL-XX-XXXX'\n"
        "  Step 3: If blank, check THIS row's description for AL-XX-XXXX\n"
        "  Step 4: If none found, use empty string - NEVER copy from other rows\n"
        "  \n"
        "  ⚠️ NEXT-LINE 'Prod Code' PATTERN — READ THIS CAREFULLY:\n"
        "  Many invoices print the code on a sub-line directly below the item:\n"
        "    Line 1: Pantocid H P Tab (GH)  SR  30049039  Tab  FJD0022 Feb-28 ... 8724.87\n"
        "    Line 2:  Prod Code : AL-01-3576.\n"
        "  → Line 2 is NOT a new item. It is the item_code for Line 1.\n"
        "  → item_code = 'AL-01-3576' (strip the trailing dot)\n"
        "  → Do NOT create a separate item object for Line 2\n"
        "  → Do NOT leave item_code blank just because it wasn't in the main row\n"
        "  \n"
        "  📋 REAL EXAMPLES FROM THIS INVOICE FORMAT:\n"
        "  'Pantocid H P Tab' + next line 'Prod Code : AL-01-3576.' → item_code = 'AL-01-3576'\n"
        "  'Oxetol 600'       + next line 'Prod Code : AL-01-2585'  → item_code = 'AL-01-2585'\n"
        "  'Etoshine 60 Tab'  + next line 'Prod Code : AL-01-2799'  → item_code = 'AL-01-2799'\n"
        "  'Predmet 8 mg'     + next line 'Prod Code : AL-01-6603'  → item_code = 'AL-01-6603'\n"
        "  'Dicorate ER 250'  + next line 'Prod Code : AL-01-3611.' → item_code = 'AL-01-3611'\n"
        "  'Opiprol 50'       + NO next-line code                   → item_code = ''\n"
        "  \n"
        "  🚫 NEVER assign AL-01-6603 to Opiprol or Sizopin just because it exists!\n"
        "- ⚠️⚠️⚠️ DMH/RACK/PCode COLUMN → item_code FIELD:\n"
        "  Column value goes to item_code field (NOT reference_number)\n"
        "  Blank column → item_code = \"\" (extract item anyway)\n"
        "- If quantity has '+' (e.g., '20+2'), keep as STRING; plain numbers → number type\n"
        "- FREE ITEM RULES (CRITICAL):\n"
        "  • Default: free_item_yn = '0' for every item\n"
        "  • If ANY free quantity exists → free_item_yn = '1'\n"
        "  • '20+2' in QTY column → quantity: '20+2' (string), free_item_yn: '1'\n"
        "  • Separate FREE/BONUS/SCH/DISC QTY column with a value:\n"
        "    → quantity: <paid qty number>, free_quantity: <free qty number>, free_item_yn: '1'\n"
        "  • Separate FREE column is blank/zero → free_quantity: null, free_item_yn: '0'\n"
        "  ⚠️ TWO-ROW FREE ITEM FORMAT (VERY IMPORTANT):\n"
        "  Some invoices show free items as TWO separate rows for the same product:\n"
        "    Row A: description='PRODUCT X', QTY=blank/0, DISC QTY=10  ← free row\n"
        "    Row B: description='PRODUCT X', QTY=100, DISC QTY=blank   ← paid row\n"
        "  RULE: When you see this pattern, DO NOT create two separate item objects.\n"
        "  Instead, MERGE them into ONE item object on the paid row:\n"
        "    → quantity: 100 (from paid row)\n"
        "    → free_quantity: 10 (from free row DISC QTY / FREE column)\n"
        "    → free_item_yn: '1'\n"
        "  The zero-quantity row (Row A) is NOT a separate item — it only carries free qty info.\n"
        "  NEVER output an item with quantity=0 unless the invoice explicitly shows a zero purchase.\n"
        "  Examples:\n"
        "    Qty=50, FREE=5  → quantity:50, free_quantity:5, free_item_yn:'1'\n"
        "    Qty=100, FREE=  → quantity:100, free_quantity:null, free_item_yn:'0'\n"
        "    Qty='20+2'      → quantity:'20+2', free_item_yn:'1'\n"
        "    Two rows: QTY=0+DISC=10, then QTY=100 → ONE item: quantity:100, free_quantity:10, free_item_yn:'1'\n"
        "- Copy Batch exactly as shown (replace <>$#@&| with -, preserve /)\n"
        "- Rates are PERCENTAGES, amounts are MONETARY VALUES\n"
        "- DISCOUNT EXTRACTION (CRITICAL):\n"
        "  Look for any column named: Dis, Disc, DISC, Disc%, CD, CD%, DIS, DIS%\n"
        "  If that column has a numeric value for this row → extract it as Discount\n"
        "  If that column is 0, 0.00, or blank → Discount: null\n"
        "  Column named 'Dis', 'Disc' or 'CD%' → Discount_type: 'percent'\n"
        "  Column named 'CD AMT' or 'DISC AMT' → Discount_type: 'amount'\n"
        "  ⚠️ Small decimal in 'Dis' column (e.g. 0.60) = 0.60% percentage, NOT ₹0.60 amount\n"
        "  Verify: qty × rate × (1 - Discount/100) ≈ TAXABLE AMT confirms it is a percentage\n"
        "  Real example: 'Dis' column = 0.60 → Discount: 0.60, Discount_type: 'percent'\n"
        "- Ghost rows: Skip ONLY if ALL of these are blank: description, quantity, price, batch, MRP\n"
        "  If ANY of those fields has a value → extract the item (even if item_code is blank)\n"
        "\n"
        "═══════════════════════ COLUMN ALIGNMENT RULE (VERY IMPORTANT) ═══════════════════════\n"
        "NEVER confuse adjacent columns. Read the table header first and map each value\n"
        "to its correct column based on the header directly above it.\n"
        "Example:\n"
        "  PCode = AL-01-2350\n"
        "  Pack  = 10 S\n"
        "  CORRECT:   item_code = AL-01-2350,  Pack = 10 S\n"
        "  INCORRECT: Pack = AL-01-2350\n"
        "Rule: Extract values from the column DIRECTLY UNDER the matching header,\n"
        "even if OCR spacing is poor. Do NOT shift values left or right.\n"
        "If unsure which column a value belongs to, use the header label as the\n"
        "single source of truth — not the visual position alone.\n"
        "══════════════════════════════════════════════════════════════════════\n"
        "\n"
        "- Merge continuation rows across pages\n"
        "- expiry_date: extract EXACTLY as shown on invoice — do NOT convert formats\n"
        "  Examples: '04/29' → extract '04/29'  |  '28-02-25' → extract '28-02-25'\n"
        "  Application code will normalize later. Do NOT calculate day from MM/YY.\n"
        "- total_price: copy from AMOUNT column EXACTLY, NEVER calculate\n"
        "- null = column does NOT exist on invoice; 0 = column exists showing zero\n"
        "- item_code: copy from item code column ONLY (column may be named: RACK, PCode,\n"
        "  P.Code, Item Code, Item No, Product Code, Product ID, Material Code, Mat Code,\n"
        "  SKU, Catalogue No, Cat No, Article No, Reference Code, Ref Code, Ref No, Code)\n"
        "  ⚠️⚠️⚠️ CRITICAL: Each row's item_code comes EXCLUSIVELY from that row's item code cell.\n"
        "  • If item code cell is blank → item_code = \"\" (empty string, NOT null)\n"
        "  • NEVER copy item_code from adjacent rows (above/below)\n"
        "  • NEVER search product description for embedded codes\n"
        "  • Blank item_code is valid — still extract the item\n"
        "  EXAMPLES (RACK column):\n"
        "    Row 1: RACK = (blank)      → item_code = \"\"  (extract item with blank code)\n"
        "    Row 2: RACK = (blank)      → item_code = \"\"  (extract item with blank code)\n"
        "    Row 3: RACK = 'AL-01-0184' → item_code = 'AL-01-0184'\n"
        "    Row 4: RACK = 'AL-01-3189' → item_code = 'AL-01-3189'\n"
        "  DO NOT assign 'AL-01-0184' to Row 1 or Row 2.\n"
        "  Normalization (when code exists): remove spaces around hyphens, remove parentheses\n"
        "- GST fields: copy if columns exist; if absent apply derivation:\n"
        "  GST_AMT = cgst_amount + sgst_amount (if GST_AMT column missing)\n"
        "  Gst% = cgst_rate + sgst_rate (if Gst% column missing)\n"
        "  NEVER output GST_AMT = 0 when component amounts are > 0\n"
        "- Value: extract from the 'Value' column when it exists on the invoice\n"
        "  The column may be labeled: 'Value', 'VALUE', 'Amt', 'AMT', 'Amount', 'AMOUNT'\n"
        "  (when it represents the pre-GST item subtotal, not the final net amount)\n"
        "  If such a column exists → copy the value exactly\n"
        "  If no such column exists anywhere → null\n"
        "  NEVER return null when a Value/Amount/Amt column is visible in the table\n"
        "- taxable_value: from TAXABLE/TAXABLE AMT column; different from Value\n"
        "  If TAXABLE column exists → copy to taxable_value (NEVER calculate)\n"
        "- NEVER leave GST fields null when invoice summary contains values\n"
        "- For single-item invoices: apply summary GST values to that item\n"
    )
    
    return system_prompt, user_prompt
