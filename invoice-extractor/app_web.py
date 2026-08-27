"""
Invoice Data Extraction System - Simple HTML/CSS/JS Web UI
Flask backend with vanilla JavaScript frontend
"""

import os
import json
import time
from pathlib import Path
from flask import Flask, request, render_template, jsonify, Response
from flask_cors import CORS
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

from pdf_utils import pdf_to_images, get_pdf_page_count
from preprocessing import ImagePreprocessor
from model_client import OpenRouterClient
from schema import SYSTEM_PROMPT, USER_PROMPT
from cache_manager import CacheManager
from gst_calculator import enrich_and_validate_gst
from gst_enrichment import enrich_gst_comprehensive
from free_item_splitter import split_free_items, get_free_item_stats
from gstin_validator import post_process_header_fields
from seller_gstin_lookup import apply_seller_gstin_override
from ocr_corrector import apply_ocr_corrections
from consistency_checker import run_consistency_checks
from langsmith import traceable

# Load environment variables
load_dotenv()

# ═══════════════════════════════════════════════════════════════════════════
# LANGSMITH SETUP
# ═══════════════════════════════════════════════════════════════════════════
# Initialize LangSmith environment from .env file
import os
os.environ['LANGCHAIN_TRACING_V2'] = os.getenv('LANGCHAIN_TRACING_V2', 'true')
os.environ['LANGCHAIN_ENDPOINT'] = os.getenv('LANGCHAIN_ENDPOINT', 'https://api.smith.langchain.com')
os.environ['LANGCHAIN_API_KEY'] = os.getenv('LANGCHAIN_API_KEY', '')
os.environ['LANGCHAIN_PROJECT'] = os.getenv('LANGCHAIN_PROJECT', 'invoice-extractor')

print(f"[LANGSMITH] Tracing enabled: {os.environ.get('LANGCHAIN_TRACING_V2')}")
print(f"[LANGSMITH] Project: {os.environ.get('LANGCHAIN_PROJECT')}")
print(f"[LANGSMITH] API Key: {'***' + os.environ.get('LANGCHAIN_API_KEY', '')[-8:] if os.environ.get('LANGCHAIN_API_KEY') else 'Not set'}")

# Initialize Flask app with CORS
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB max file size
app.config['UPLOAD_FOLDER'] = 'uploads'

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Enable CORS for all origins (development)
CORS(app)

# Configuration from environment variables
CACHE_ENABLED = os.getenv('CACHE_ENABLED', 'true').lower() == 'true'
CACHE_DIRECTORY = os.getenv('CACHE_DIRECTORY', 'uploads/.cache')
CACHE_MAX_AGE_HOURS = int(os.getenv('CACHE_MAX_AGE_HOURS', '24'))
MAX_PDF_PAGES = int(os.getenv('MAX_PDF_PAGES', '20'))

# Allowed extensions
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'tiff', 'tif', 'bmp', 'webp'}

# Initialize components
preprocessor = ImagePreprocessor()
cache_manager = CacheManager(cache_dir=CACHE_DIRECTORY, max_age_hours=CACHE_MAX_AGE_HOURS)

try:
    client = OpenRouterClient()
    API_CONFIGURED = True
except Exception as e:
    print(f"Warning: API client initialization failed: {e}")
    API_CONFIGURED = False


def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/')
def index():
    """Serve the main page."""
    return render_template('index.html')


@app.route('/api/extract', methods=['POST'])
def extract_invoice():
    """Extract invoice data from uploaded file with optional OCR, caching, two-pass, and multi-page support."""
    
    # Check if file is present
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'File type not supported. Please upload PDF or image files.'}), 400
    
    if not API_CONFIGURED:
        return jsonify({'error': 'API key not configured. Please set OPENROUTER_API_KEY in .env file.'}), 500
    
    # Get extraction options
    use_ocr = request.form.get('use_ocr', 'false').lower() == 'true'
    use_cache = request.form.get('use_cache', 'true').lower() == 'true' and CACHE_ENABLED
    two_pass = request.form.get('two_pass', 'true').lower() == 'true'
    multi_page = request.form.get('multi_page', 'true').lower() == 'true'
    
    try:
        # Read file bytes for caching
        file_bytes = file.read()
        file.seek(0)  # Reset file pointer for later use
        
        # Generate cache key
        cache_options = {
            'use_ocr': use_ocr,
            'two_pass': two_pass,
            'multi_page': multi_page
        }
        cache_key = cache_manager.generate_cache_key(file_bytes, cache_options)
        
        # Check cache if enabled
        cached_result = None
        if use_cache:
            cached_result = cache_manager.get(cache_key)
        
        if cached_result:
            print(f"⚡ Serving from cache: {file.filename}")
            return jsonify({
                'success': True,
                'data': cached_result['data'],
                'metadata': {
                    **cached_result.get('metadata', {}),
                    'cached': True,
                    'cache_key': cache_key
                },
                'reasoning': cached_result.get('reasoning', [])
            })
        
        # Save uploaded file
        filename = secure_filename(file.filename)
        filepath = os.path.normpath(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        file.save(filepath)
        
        start_time = time.time()
        reasoning_log = []
        
        # ── LangSmith: open a root span for this entire request ──────────
        from langsmith import trace as ls_trace
        _ls_root_span = ls_trace(
            name=f"invoice_extraction_pipeline",
            run_type="chain",
            metadata={"filename": filename, "use_ocr": use_ocr, "two_pass": two_pass, "multi_page": multi_page}
        )
        _ls_root_span.__enter__()

        # Log function
        def log_step(message):
            timestamp = time.strftime("%H:%M:%S")
            reasoning_log.append(f"[{timestamp}] {message}")
        
        mode_desc = "two-pass" if two_pass else "single-pass"
        ocr_desc = " with OCR" if use_ocr else ""
        multipage_desc = " (multi-page)" if multi_page else ""
        log_step(f"File received, analyzing ({mode_desc}{ocr_desc}{multipage_desc})...")
        
        # Determine file type
        file_ext = Path(filepath).suffix.lower()
        
        # Convert to images
        images = []
        page_count = 1
        
        if file_ext == '.pdf':
            log_step("PDF detected, converting to images...")
            images = pdf_to_images(filepath, dpi=300)
            
            if not images:
                os.remove(filepath)
                return jsonify({'error': 'Failed to convert PDF to images'}), 500
            
            page_count = len(images)
            log_step(f"PDF converted: {page_count} page(s) detected")
            
            # Handle multi-page vs single-page
            if page_count > 1 and multi_page:
                # Limit to MAX_PDF_PAGES
                if page_count > MAX_PDF_PAGES:
                    log_step(f"⚠️  PDF has {page_count} pages, limiting to {MAX_PDF_PAGES} pages (MAX_PDF_PAGES)")
                    images = images[:MAX_PDF_PAGES]
                    page_count = MAX_PDF_PAGES
                
                log_step(f"Multi-page mode: Processing all {page_count} pages")
                log_step(f"Strategy: Page 1 = all fields, Pages 2-{page_count} = items only")
            elif page_count > 1 and not multi_page:
                log_step(f"Multi-page PDF detected ({page_count} pages)")
                log_step(f"Multi-page mode disabled: Processing ONLY page 1")
                images = [images[0]]
                page_count = 1
            else:
                log_step("Single-page PDF: Processing page 1")
        else:
            log_step(f"Image file detected ({file_ext})")
            from PIL import Image
            image = Image.open(filepath).convert('RGB')
            images = [image]
            log_step("Image loaded successfully")
        
        # Preprocess all images
        processed_images = []
        
        for idx, image in enumerate(images):
            page_label = f"page {idx + 1}/{page_count}" if len(images) > 1 else "image"
            
            if use_ocr and idx == 0:  # Only log OCR for first page
                log_step(f"Preprocessing {page_label} with OCR orientation detection...")
            else:
                log_step(f"Preprocessing {page_label}...")
            
            processed_image, preprocess_debug = preprocessor.process(
                image,
                do_orient=True if idx == 0 else False,  # Only detect orientation on first page
                do_deskew=True,      # ✅ ENABLED — corrects tilted scans
                do_enhance=True,     # ✅ already ON — contrast enhancement
                do_denoise=False,    # OFF — too slow, blurs text
                do_sharpen=True,     # ✅ ENABLED — sharpens text edges
                do_crop_border=True, # ✅ ENABLED — removes scanner margins
                do_binarize=False    # OFF unless invoice is genuinely faded
            )
            
            # Log orientation details only for first page
            if idx == 0 and 'orientation' in preprocess_debug:
                rotation = preprocess_debug['orientation'].get('rotation_angle', 0)
                method = preprocess_debug['orientation'].get('method', 'unknown')
                confidence = preprocess_debug['orientation'].get('confidence', 0.0)
                ocr_available = preprocess_debug['orientation'].get('ocr_available', False)
                
                log_step(f"OCR available for rotation detection: {'Yes' if ocr_available else 'No'}")
                if rotation != 0:
                    log_step(f"✅ Rotation detected: {rotation}° (method: {method}, confidence: {confidence:.1%})")
                    log_step(f"Image rotated {rotation}° to correct orientation")
                else:
                    log_step(f"No rotation needed (method: {method}, confidence: {confidence:.1%})")
            
            processed_images.append(processed_image)
        
        log_step(f"Preprocessing complete for {len(processed_images)} page(s)")
        
        # Extract (single-page, two-pass, or multi-page)
        extraction_start = time.time()
        
        if len(processed_images) > 1 and multi_page:
            # Multi-page extraction
            log_step(f"Starting multi-page extraction for {len(processed_images)} pages...")
            try:
                extracted_data, raw_response = client.extract_invoice_multipage(
                    processed_images,
                    use_two_pass=two_pass,
                    temperature=0.1
                )
                print(f"[DEBUG] Multipage extraction returned: type={type(extracted_data)}, has_error={'error' in extracted_data if isinstance(extracted_data, dict) else 'N/A'}")
            except Exception as multipage_error:
                import traceback
                print("="*80)
                print("MULTIPAGE EXTRACTION ERROR:")
                print("="*80)
                traceback.print_exc()
                print("="*80)
                raise
            extraction_mode = f"multi-page ({page_count} pages, {'two-pass' if two_pass else 'single-pass'})"
        elif two_pass:
            # Single-page two-pass extraction
            log_step("Starting two-pass extraction (header → totals → items)...")
            extracted_data, raw_response = client.extract_invoice_two_pass(
                processed_images[0],
                temperature=0.1
            )
            extraction_mode = "two-pass"
        else:
            # Single-page single-pass extraction
            log_step("Starting single-pass extraction...")
            extracted_data, raw_response = client.extract_invoice(
                processed_images[0],
                SYSTEM_PROMPT,
                USER_PROMPT,
                temperature=0.1,
                max_tokens=2500
            )
            extraction_mode = "single-pass"
        
        extraction_time = time.time() - extraction_start
        
        if 'error' in extracted_data:
            os.remove(filepath)
            return jsonify({
                'error': f"Extraction failed: {extracted_data['error']}",
                'failed_pass': extracted_data.get('failed_pass'),
                'failed_page': extracted_data.get('failed_page'),
                'partial_results': extracted_data.get('partial_results', {}),
                'reasoning': reasoning_log
            }), 500
        
        log_step(f"Model response received in {extraction_time:.2f}s ({extraction_mode})")
        
        # ═══════════════════════════════════════════════════════════
        # HEADER FIELD POST-PROCESSING (GSTIN + NAME VALIDATION)
        # ═══════════════════════════════════════════════════════════
        log_step("Validating GSTINs and correcting name/pack OCR errors...")
        try:
            extracted_data = post_process_header_fields(extracted_data)
            log_step("✅ Header field post-processing complete")
        except Exception as pp_error:
            log_step(f"⚠️  Header post-processing error (non-fatal): {pp_error}")

        # ═══════════════════════════════════════════════════════════
        # SELLER GSTIN HARDCODED OVERRIDE
        # Replaces hallucinated / mis-read seller GSTINs with the
        # known-correct value from our fixed seller lookup table.
        # ═══════════════════════════════════════════════════════════
        log_step("Applying hardcoded seller GSTIN override...")
        try:
            extracted_data = apply_seller_gstin_override(extracted_data)
            log_step(f"✅ Seller GSTIN override applied (seller: {extracted_data.get('seller_name', 'unknown')})")
        except Exception as gstin_override_error:
            log_step(f"⚠️  Seller GSTIN override error (non-fatal): {gstin_override_error}")

        # ═══════════════════════════════════════════════════════════
        # OCR CORRECTIONS — deterministic GSTIN / HSN / date fixes
        # Runs after GSTIN override so the override wins, but before
        # any downstream enrichment that depends on clean values.
        # ═══════════════════════════════════════════════════════════
        log_step("Applying deterministic OCR corrections (GSTIN/HSN/dates)...")
        try:
            extracted_data = apply_ocr_corrections(extracted_data)
            log_step("✅ OCR corrections applied")
        except Exception as ocr_fix_error:
            log_step(f"⚠️  OCR correction error (non-fatal): {ocr_fix_error}")

        # ═══════════════════════════════════════════════════════════
        # TYPE NORMALIZATION
        # ═══════════════════════════════════════════════════════════
        log_step("Normalizing data types...")
        
        def normalize_types(data: dict) -> dict:
            """
            Ensure numeric fields are numbers, not strings.
            Ensure 0 vs null distinction is preserved.
            """
            # Numeric fields that should be numbers (not strings)
            numeric_fields = [
                'total_quantity', 'discount_amount',
                'cd_amount', 'taxable_amount',
                'total_gst_rate', 'total_cgst_rate', 'total_cgst_amount',
                'total_sgst_rate', 'total_sgst_amount',
                'total_igst_rate', 'total_igst_amount',
                'total_gst_amount',
                'round_off', 'invoice_amount'
            ]
            
            # Convert string numbers to actual numbers
            for field in numeric_fields:
                if field in data and data[field] is not None:
                    value = data[field]
                    if isinstance(value, str):
                        # Remove commas and convert
                        try:
                            # Handle empty strings or "-" as null
                            if value.strip() in ('', '-', 'N/A', 'n/a'):
                                data[field] = None
                            else:
                                # Remove commas, spaces, currency symbols
                                cleaned = value.replace(',', '').replace(' ', '').replace('₹', '').strip()
                                data[field] = float(cleaned)
                                log_step(f"  Converted {field}: '{value}' → {data[field]}")
                        except (ValueError, AttributeError):
                            log_step(f"  ⚠️  Could not convert {field}: '{value}' → keeping as null")
                            data[field] = None
            
            # Normalize item fields
            if 'items' in data and isinstance(data['items'], list):
                item_numeric_fields = [
                    'unit_price', 'total_price', 'Value', 'MRP',
                    'cd_percent', 'Discount', 'Gst%',
                    'cgst_rate', 'cgst_amount', 'sgst_rate', 'sgst_amount',
                    'igst_rate', 'igst_amount',
                    'GST_AMT'
                ]
                
                for item in data['items']:
                    # Handle quantity (can be number or string like "20+2")
                    if 'quantity' in item and isinstance(item['quantity'], str):
                        qty_str = item['quantity'].strip()
                        # If it contains "+", keep as string (free items)
                        if '+' not in qty_str:
                            # Plain number as string → convert to number
                            try:
                                if qty_str not in ('', '-', 'N/A', 'n/a'):
                                    item['quantity'] = float(qty_str) if '.' in qty_str else int(qty_str)
                            except (ValueError, AttributeError):
                                pass  # Keep as string if can't convert
                    
                    # Convert numeric item fields
                    for field in item_numeric_fields:
                        if field in item and item[field] is not None:
                            value = item[field]
                            if isinstance(value, str):
                                try:
                                    if value.strip() in ('', '-', 'N/A', 'n/a'):
                                        item[field] = None
                                    else:
                                        cleaned = value.replace(',', '').replace(' ', '').replace('₹', '').replace('%', '').strip()
                                        item[field] = float(cleaned)
                                except (ValueError, AttributeError):
                                    item[field] = None
            
            return data
        
        extracted_data = normalize_types(extracted_data)
        
        # ═══════════════════════════════════════════════════════════
        # COMPREHENSIVE GST ENRICHMENT
        # ═══════════════════════════════════════════════════════════
        log_step("Enriching GST fields (comprehensive)...")
        
        # ═══════════════════════════════════════════════════════════
        # FREE ITEM SPLITTING
        # ═══════════════════════════════════════════════════════════
        # CRITICAL: Split items BEFORE any GST calculations.
        # GST enrichment must work on correct paid-only quantities, not pre-split.
        log_step("Splitting free items into separate records...")
        
        try:
            # Get stats before splitting
            items_before = len(extracted_data.get('items', []))
            
            # DEBUG: Check for items with "+" before splitting
            items_with_plus = [i for i in extracted_data.get('items', []) if isinstance(i.get('quantity'), str) and '+' in str(i.get('quantity'))]
            if items_with_plus:
                log_step(f"Found {len(items_with_plus)} items with '+' format before splitting")
            
            # Split items with free quantities
            extracted_data = split_free_items(extracted_data)
            
            # DEBUG: Check if splitting worked
            items_with_plus_after = [i for i in extracted_data.get('items', []) if isinstance(i.get('quantity'), str) and '+' in str(i.get('quantity'))]
            if items_with_plus_after:
                log_step(f"⚠️  WARNING: Still have {len(items_with_plus_after)} items with '+' format after splitting!")
            
            # Get stats after splitting
            stats = get_free_item_stats(extracted_data)
            log_step(f"✅ Free items split: {stats['total_items_before']} items → {stats['total_items_after']} items ({stats['paid_items']} paid, {stats['free_items']} free)")
        except Exception as split_error:
            log_step(f"⚠️  Free item splitting error: {str(split_error)}")
        
        # ═══════════════════════════════════════════════════════════
        # GST ENRICHMENT (AFTER SPLITTING)
        # ═══════════════════════════════════════════════════════════
        log_step("Enriching GST fields...")
        try:
            # New comprehensive GST enrichment
            # NOW runs AFTER splitting — calculates on correct paid-only quantities
            extracted_data = enrich_gst_comprehensive(extracted_data)
            log_step("✅ GST enrichment complete")
        except Exception as gst_enrich_error:
            log_step(f"⚠️  GST enrichment error: {str(gst_enrich_error)}")
        
        # ═══════════════════════════════════════════════════════════
        # CALCULATE TOTAL_QUANTITY (PAID ITEMS ONLY)
        # ═══════════════════════════════════════════════════════════
        # Business rule: total_quantity = sum of PAID quantities only.
        # Free items (free_item_yn == "1") are excluded.
        log_step("Calculating total_quantity (paid items only)...")
        
        paid_quantity_sum = 0
        free_quantity_sum = 0
        
        for item in extracted_data.get('items', []):
            qty = item.get('quantity', 0)
            
            # Convert to number
            if isinstance(qty, str):
                # Should NOT have "+" at this point!
                if '+' in qty:
                    log_step(f"⚠️  ERROR: Item still has '+' in quantity after splitting: {qty}")
                    continue
                try:
                    qty = float(qty)
                except (ValueError, TypeError):
                    log_step(f"⚠️  Cannot convert quantity to number: {qty}")
                    continue
            elif not isinstance(qty, (int, float)):
                continue
            
            # Track paid vs free separately
            if item.get('free_item_yn') == "1":
                free_quantity_sum += qty
            else:
                paid_quantity_sum += qty
        
        # total_quantity = paid quantities only (free items excluded)
        extracted_data['total_quantity'] = int(paid_quantity_sum) if paid_quantity_sum == int(paid_quantity_sum) else paid_quantity_sum
        
        log_step(f"✅ total_quantity = {extracted_data['total_quantity']} (paid only)")
        log_step(f"   Paid items total: {paid_quantity_sum}")
        log_step(f"   Free items total: {free_quantity_sum} (excluded)")
        
        # ═══════════════════════════════════════════════════════════
        # GST VALIDATION (Original)
        # ═══════════════════════════════════════════════════════════
        log_step("Enriching GST calculations and validating...")
        
        try:
            print(f"[DEBUG] Before enrich_and_validate_gst: type={type(extracted_data)}, keys={list(extracted_data.keys())[:10]}")
            extracted_data, gst_validation = enrich_and_validate_gst(extracted_data)
            print(f"[DEBUG] After enrich_and_validate_gst: type={type(extracted_data)}, keys={list(extracted_data.keys())[:10]}")
            
            if gst_validation['valid']:
                log_step(f"✅ GST validation passed ({gst_validation['transaction_type']})")
            else:
                log_step(f"⚠️  GST validation warnings: {len(gst_validation.get('warnings', []))} issues")
            
            if gst_validation.get('errors'):
                for error in gst_validation['errors']:
                    log_step(f"❌ GST Error: {error}")
            
            if gst_validation.get('warnings'):
                for warning in gst_validation['warnings']:
                    log_step(f"⚠️  {warning}")
        
        except Exception as gst_error:
            log_step(f"⚠️  GST calculation error: {str(gst_error)}")
            gst_validation = {'valid': False, 'error': str(gst_error)}

        # ═══════════════════════════════════════════════════════════
        # CONSISTENCY CHECKS — math-based validation, zero API cost
        # Flags items where GST_AMT, component sums, or qty×price
        # don't add up. Adds _needs_review + _review_reasons per item.
        # Invoice-level mismatches stored in _invoice_review_reasons.
        # These flags survive into the final JSON so the frontend /
        # caller can highlight suspicious rows for human review.
        # ═══════════════════════════════════════════════════════════
        log_step("Running consistency checks (GST math, amount cross-validation)...")
        try:
            extracted_data, consistency_summary = run_consistency_checks(extracted_data)
            flagged = consistency_summary['items_flagged']
            inv_issues = len(consistency_summary['invoice_issues'])
            if consistency_summary['has_issues']:
                log_step(f"⚠️  Consistency: {flagged} item(s) flagged, "
                         f"{inv_issues} invoice-level issue(s) — see _needs_review / _review_reasons")
            else:
                log_step(f"✅ Consistency checks passed "
                         f"({consistency_summary['items_clean']} items clean)")
        except Exception as consistency_error:
            log_step(f"⚠️  Consistency check error (non-fatal): {consistency_error}")

        # ═══════════════════════════════════════════════════════════
        # MODEL-BASED VERIFICATION — cross-check extracted JSON vs image
        # Sends the extracted data + first page back to model for
        # validation. Cheap pass (no reasoning, 2000 tokens) that flags
        # discrepancies between what was extracted and what's visible.
        # Result stored in _verification field for frontend display.
        # ═══════════════════════════════════════════════════════════
        log_step("Running model-based verification pass...")
        try:
            # Use the FIRST processed image (page 1) for verification
            # since that's where header/totals typically are
            verification_result = client.verify_extraction(
                processed_images[0],
                extracted_data
            )
            extracted_data['_verification'] = verification_result
            status = verification_result.get('verification_status', 'UNKNOWN')
            log_step(f"✅ Verification complete: {status}")
        except Exception as verify_error:
            log_step(f"⚠️  Verification error (non-fatal): {verify_error}")
            extracted_data['_verification'] = {
                'verification_status': 'ERROR',
                'error': str(verify_error)
            }

        # ═══════════════════════════════════════════════════════════
        # ITEM-TO-HEADER RECONCILIATION
        # Sums item-level values and compares against printed invoice
        # totals. Produces a validation_status field in the response.
        # Rule: if printed totals exist, use them as the authority.
        # ═══════════════════════════════════════════════════════════
        log_step("Running item-to-header reconciliation...")
        try:
            def _n(v):
                """Safe float conversion, None → 0.0."""
                if v is None or v == '':
                    return 0.0
                try:
                    return float(str(v).replace(',', '').replace('₹', '').strip())
                except (ValueError, TypeError):
                    return 0.0

            items_for_recon = extracted_data.get('items', [])

            # Sum item-level values (paid items only for quantity)
            sum_qty      = sum(_n(it.get('quantity'))     for it in items_for_recon
                               if it.get('free_item_yn') != '1')
            sum_taxable  = sum(_n(it.get('taxable_value')) for it in items_for_recon)
            sum_cgst     = sum(_n(it.get('cgst_amount'))  for it in items_for_recon)
            sum_sgst     = sum(_n(it.get('sgst_amount'))  for it in items_for_recon)
            sum_igst     = sum(_n(it.get('igst_amount'))  for it in items_for_recon)
            sum_gst      = sum(_n(it.get('GST_AMT'))      for it in items_for_recon)

            # Printed invoice totals
            hdr_qty      = _n(extracted_data.get('total_quantity'))
            hdr_cgst     = _n(extracted_data.get('total_cgst_amount'))
            hdr_sgst     = _n(extracted_data.get('total_sgst_amount'))
            hdr_igst     = _n(extracted_data.get('total_igst_amount'))
            hdr_gst      = _n(extracted_data.get('total_gst_amount'))
            hdr_amount   = _n(extracted_data.get('invoice_amount'))
            hdr_roundoff = _n(extracted_data.get('round_off'))

            TOL = 0.05   # ₹0.05 rounding tolerance per field

            recon_issues = []
            def _check(label, computed, printed, tol=TOL):
                if printed > 0 and abs(computed - printed) > tol:
                    recon_issues.append(
                        f"{label}: sum={computed:.2f} printed={printed:.2f} diff={computed-printed:.2f}"
                    )

            _check("quantity",   sum_qty,     hdr_qty,  tol=0.5)
            _check("cgst",       sum_cgst,    hdr_cgst)
            _check("sgst",       sum_sgst,    hdr_sgst)
            _check("igst",       sum_igst,    hdr_igst)
            _check("gst_total",  sum_gst,     hdr_gst)

            # Invoice amount check: taxable + gst + round_off ≈ invoice_amount
            computed_total = round(sum_taxable + sum_gst + hdr_roundoff, 2)
            if hdr_amount > 0 and abs(computed_total - hdr_amount) > 1.0:
                recon_issues.append(
                    f"invoice_amount: computed={computed_total:.2f} printed={hdr_amount:.2f}"
                )

            if recon_issues:
                validation_status = "FAIL"
                log_step(f"⚠️  Reconciliation FAIL ({len(recon_issues)} mismatch(es)):")
                for issue in recon_issues:
                    log_step(f"   → {issue}")
            else:
                validation_status = "PASS"
                log_step(f"✅ Reconciliation PASS — qty={sum_qty:.0f} cgst={sum_cgst:.2f} "
                         f"sgst={sum_sgst:.2f} gst={sum_gst:.2f}")

            extracted_data['_reconciliation'] = {
                'status':           validation_status,
                'item_qty_sum':     round(sum_qty,     2),
                'item_taxable_sum': round(sum_taxable, 2),
                'item_cgst_sum':    round(sum_cgst,    2),
                'item_sgst_sum':    round(sum_sgst,    2),
                'item_igst_sum':    round(sum_igst,    2),
                'item_gst_sum':     round(sum_gst,     2),
                'issues':           recon_issues,
            }

        except Exception as recon_err:
            log_step(f"⚠️  Reconciliation error (non-fatal): {recon_err}")

        # Reorder fields: Header → Totals → Items
        log_step("Organizing output structure...")
        
        # Define field order
        header_fields = [
            'invoice_id', 'invoice_number', 'invoice_date', 'due_date',
            'customer_name', 'customer_gstin',
            'seller_name', 'seller_gstin',
            'currency_code',
            'PO_number', 'DC_date', 'DC_number'
        ]
        
        totals_fields = [
            'invoice_amount', 'round_off',
            'total_gst_rate', 'total_quantity',
            'total_cgst_rate', 'total_cgst_amount',
            'total_sgst_rate', 'total_sgst_amount',
            'total_igst_rate', 'total_igst_amount',
            'total_gst_amount',
            'round_off', 'invoice_amount'
        ]
        
        # Reorder the data
        ordered_data = {}
        
        # Add header fields first
        for field in header_fields:
            if field in extracted_data:
                ordered_data[field] = extracted_data[field]
        
        # Add totals fields second
        for field in totals_fields:
            if field in extracted_data:
                ordered_data[field] = extracted_data[field]
        
        # Add items array last
        if 'items' in extracted_data:
            ordered_data['items'] = extracted_data['items']
        
        # Add any remaining fields that weren't in our predefined lists
        for key, value in extracted_data.items():
            if key not in ordered_data:
                ordered_data[key] = value
        
        extracted_data = ordered_data
        
        # ═══════════════════════════════════════════════════════════
        # CLIENT-SPECIFIC OUTPUT FORMATTING
        # ═══════════════════════════════════════════════════════════
        log_step("Applying client output formatting...")
        
        @traceable(name="format_for_client", tags=["formatting", "output"])
        def format_for_client(data: dict) -> dict:
            """
            Apply client-specific formatting requirements.
            
            Changes:
            1. Add invoice_id (copy from invoice_number)
            2. Add currency_code: "INR"
            3. Format dates: DD-MM-YYYY → DD/MM/YYYY
            4. Keep monetary fields as NUMBERS (frontend handles formatting)
            5. Add free_item_yn: "0" for normal items
            6. Keep Pack if exists (don't force null)
            7. Remove internal fields (_gst_source, _gst_calculation_metadata)
            
            IMPORTANT: Monetary fields (invoice_amount, round_off, MRP, prices, etc.)
            are kept as NUMBERS, not converted to strings. The frontend JavaScript
            will handle the display formatting.
            """
            from ocr_corrector import correct_date
            
            # 1. Add currency_code if missing (should already be in extraction)
            if 'currency_code' not in data or not data['currency_code']:
                data['currency_code'] = 'INR'
            
            # 1b. Ensure invoice_id = invoice_number if missing
            if 'invoice_number' in data and data['invoice_number']:
                if 'invoice_id' not in data or not data['invoice_id']:
                    data['invoice_id'] = data['invoice_number']
            
            # 2. Format dates — leap-year-aware via ocr_corrector.correct_date
            # correct_date handles: multiple input formats, leap-year clamping,
            # 2-digit year conversion, MM/YY → last-day-of-month for pharma expiry.
            # Returns value unchanged (as string) if parsing fails — never drops data.
            for field in ['invoice_date', 'due_date', 'DC_date']:
                if data.get(field):
                    data[field] = correct_date(data[field])
            
            # 3. Ensure numeric fields are numbers (not strings)
            # These fields MUST be numbers for frontend JavaScript to work
            numeric_fields = [
                'invoice_amount', 'round_off',
                'taxable_amount',
                'total_cgst_amount', 'total_sgst_amount', 'total_igst_amount',
                'total_gst_amount'
            ]
            
            for field in numeric_fields:
                if field in data and data[field] is not None:
                    if isinstance(data[field], str):
                        try:
                            # Remove formatting: commas, currency symbols, special brackets
                            # Handle special format like "(-)0.26" → -0.26
                            cleaned = (data[field]
                                      .replace(',', '')
                                      .replace('₹', '')
                                      .replace('(-)', '-')
                                      .replace('(', '')
                                      .replace(')', '')
                                      .strip())
                            data[field] = float(cleaned)
                        except (ValueError, AttributeError):
                            # If conversion fails, set to null
                            data[field] = None
            
            # 4. Process items
            if 'items' in data and isinstance(data['items'], list):
                for item in data['items']:
                    # Add free_item_yn (default "0" for normal items)
                    if 'free_item_yn' not in item:
                        item['free_item_yn'] = "0"
                    
                    # Format expiry_date — leap-year-aware via ocr_corrector.correct_date
                    if item.get('expiry_date'):
                        item['expiry_date'] = correct_date(item['expiry_date'])
                    
                    # Ensure item numeric fields are numbers (not strings)
                    item_numeric_fields = [
                        'quantity', 'unit_price', 'total_price', 'Value', 'MRP',
                        'Discount', 'Gst%',
                        'cgst_rate', 'cgst_amount', 'sgst_rate', 'sgst_amount',
                        'igst_rate', 'igst_amount', 'GST_AMT'
                    ]
                    
                    for field in item_numeric_fields:
                        if field in item and item[field] is not None:
                            # Special handling for quantity (can be "20+2" string)
                            if field == 'quantity' and isinstance(item[field], str):
                                if '+' in item[field]:
                                    # Keep as string for free items
                                    continue
                                else:
                                    # Convert plain number string to number
                                    try:
                                        qty_str = item[field].strip()
                                        item[field] = float(qty_str) if '.' in qty_str else int(qty_str)
                                    except (ValueError, AttributeError):
                                        pass  # Keep as string if conversion fails
                            elif isinstance(item[field], str):
                                try:
                                    # Remove formatting and convert to float
                                    cleaned = item[field].replace(',', '').replace('₹', '').replace('%', '').strip()
                                    item[field] = float(cleaned)
                                except (ValueError, AttributeError):
                                    item[field] = None
            
            # 5. Remove internal and deprecated fields
            internal_fields = ['_gst_source', '_gst_calculation_metadata',
                              '_validation_warnings', '_validation_errors',
                              '_gst_rate_corrected', '_invoice_review_reasons']
            deprecated_fields = ['seller_DL_Number', 'customer_DL_Number']

            for field in internal_fields + deprecated_fields:
                if field in data:
                    del data[field]

            # Also remove from items
            # Remove review flags from items as client doesn't need them in output
            deprecated_item_fields = ['mfgr_code', '_gst_source', '_needs_review', '_review_reasons']
            if 'items' in data and isinstance(data['items'], list):
                for item in data['items']:
                    for field in internal_fields + deprecated_item_fields:
                        if field in item:
                            del item[field]
            
            return data
        
        extracted_data = format_for_client(extracted_data)
        
        # Defensive check - ensure extracted_data is valid
        if not isinstance(extracted_data, dict):
            raise ValueError(f"extracted_data is not a dict, got {type(extracted_data)}")
        if 'items' not in extracted_data:
            extracted_data['items'] = []
        
        # ═══════════════════════════════════════════════════════════
        # FORMAT MONETARY FIELDS WITH 2 DECIMALS (AS STRINGS)
        # ═══════════════════════════════════════════════════════════
        def format_decimals_as_strings(data: dict) -> dict:
            """
            Format all monetary fields to strings with exactly 2 decimal places.
            Converts: 1775 → "1775.00", 70.4 → "70.40", etc.
            This ensures JSON output maintains .00 format.
            """
            # Header monetary fields
            monetary_fields = [
                'invoice_amount', 'round_off',
                'taxable_amount',
                'total_cgst_amount', 'total_sgst_amount',
                'total_igst_amount', 'total_gst_amount',
                'round_off'
            ]
            
            for field in monetary_fields:
                if field in data and data[field] is not None:
                    # Format to string with 2 decimals
                    data[field] = f"{float(data[field]):.2f}"
            
            # Item monetary fields
            if 'items' in data and isinstance(data['items'], list):
                item_monetary_fields = [
                    'unit_price', 'total_price', 'Value', 'MRP',
                    'Discount',
                    'cgst_amount', 'sgst_amount', 'igst_amount',
                    'GST_AMT'
                ]
                
                for item in data['items']:
                    for field in item_monetary_fields:
                        if field in item and item[field] is not None:
                            item[field] = f"{float(item[field]):.2f}"
            
            return data
        
        extracted_data = format_decimals_as_strings(extracted_data)
        
        # CRITICAL DEBUG: Check items before returning
        log_step(f"[DEBUG] Final item count: {len(extracted_data.get('items', []))}")
        for idx, item in enumerate(extracted_data.get('items', [])[:3]):  # Show first 3
            log_step(f"[DEBUG] Item {idx+1}: qty={item.get('quantity')}, free_yn={item.get('free_item_yn')}, desc={item.get('description', '')[:30]}")
        
        log_step("Extraction complete - returning structured JSON output")
        
        elapsed = time.time() - start_time
        
        # Prepare metadata
        metadata = {
            'processing_time': elapsed,
            'extraction_time': extraction_time,
            'extraction_mode': extraction_mode,
            'page_count': page_count,
            'preprocessing': {
                'rotation': preprocess_debug.get('orientation', {}).get('rotation_angle', 0),
                'steps': len(preprocess_debug.get('steps_applied', [])),
                'ocr_used': use_ocr
            },
            'model_used': client.model,
            'cached': False,
            'cache_key': cache_key,
            'gst_validation': gst_validation if 'gst_validation' in locals() else None
        }
        
        # Add multi-page metadata if applicable
        if 'pages' in raw_response:
            metadata['pages_metadata'] = raw_response['pages']
            metadata['total_items'] = raw_response.get('total_items', len(extracted_data.get('items', [])))
            metadata['duplicates_skipped'] = raw_response.get('duplicates_skipped', 0)
        
        # Prepare response
        # Remove internal metadata fields from data before returning
        verification_result = extracted_data.pop('_verification', None)
        reconciliation_result = extracted_data.pop('_reconciliation', None)
        
        response_data = {
            'success': True,
            'data': extracted_data,
            'metadata': metadata,
            'reasoning': reasoning_log,
            'reconciliation': reconciliation_result,
        }
        
        # Cache result if enabled
        if use_cache:
            cache_metadata = {
                'filename': filename,
                'extraction_options': cache_options,
                'extraction_time': extraction_time,
                'processing_time': elapsed,
                'page_count': page_count
            }
            cache_manager.set(cache_key, response_data, cache_metadata)
        
        # Clean up uploaded file
        os.remove(filepath)
        
        # Close LangSmith root span — success
        try:
            _ls_root_span.__exit__(None, None, None)
        except Exception:
            pass

        # Return with explicit JSON to preserve field order
        return Response(
            json.dumps(response_data, ensure_ascii=False),
            mimetype='application/json'
        )
    
    except Exception as e:
        # Clean up file on error
        if 'filepath' in locals() and os.path.exists(filepath):
            os.remove(filepath)
        
        # Close LangSmith root span — failure
        try:
            import sys
            _ls_root_span.__exit__(*sys.exc_info())
        except Exception:
            pass
        
        # Get detailed traceback
        import traceback
        import sys
        error_traceback = traceback.format_exc()
        
        # Get the specific frame where error occurred
        exc_type, exc_value, exc_tb = sys.exc_info()
        tb_list = traceback.extract_tb(exc_tb)
        
        print("="*80)
        print("CRITICAL ERROR OCCURRED:")
        print("="*80)
        print(f"Error Type: {type(e).__name__}")
        print(f"Error Message: {str(e)}")
        print("\nFull Traceback:")
        print(error_traceback)
        
        if tb_list:
            print("\nERROR LOCATION:")
            for frame in tb_list:
                filename = frame.filename
                lineno = frame.lineno
                func_name = frame.name
                line_text = frame.line
                print(f"  File: {filename}")
                print(f"  Function: {func_name}")
                print(f"  Line {lineno}: {line_text}")
                print()
        
        print("="*80)
        print("DEBUGGING INFO:")
        print("="*80)
        print(f"Local variables available: {list(locals().keys())}")
        print(f"extracted_data type: {type(locals().get('extracted_data', 'NOT_DEFINED'))}")
        if 'extracted_data' in locals():
            print(f"extracted_data is dict: {isinstance(locals()['extracted_data'], dict)}")
            if isinstance(locals()['extracted_data'], dict):
                print(f"extracted_data keys: {list(locals()['extracted_data'].keys())[:10]}")
        print("="*80)
        
        return jsonify({
            'error': f'Unexpected error: {str(e)}',
            'error_type': type(e).__name__,
            'error_location': f"{tb_list[-1].filename}:{tb_list[-1].lineno}" if tb_list else "unknown",
            'error_function': tb_list[-1].name if tb_list else "unknown",
            'traceback': error_traceback,
            'reasoning': reasoning_log if 'reasoning_log' in locals() else []
        }), 500


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'api_configured': API_CONFIGURED
    })


@app.route('/api/cache/stats', methods=['GET'])
def cache_stats():
    """Get cache statistics."""
    if not CACHE_ENABLED:
        return jsonify({'error': 'Cache is disabled'}), 400
    
    stats = cache_manager.get_stats()
    return jsonify(stats)


@app.route('/api/cache/clear', methods=['POST'])
def cache_clear():
    """Clear cache entries."""
    if not CACHE_ENABLED:
        return jsonify({'error': 'Cache is disabled'}), 400
    
    # Optional: clear only entries older than specified age
    max_age_hours = request.args.get('max_age_hours', type=int)
    
    result = cache_manager.clear(max_age_hours=max_age_hours)
    
    return jsonify({
        'success': True,
        'deleted_count': result['deleted_count'],
        'freed_space_bytes': result['freed_space_bytes'],
        'freed_space_kb': round(result['freed_space_bytes'] / 1024, 2)
    })


if __name__ == '__main__':
    web_port = 8001
    print("="*80)
    print("[ROCKET] Invoice Extraction System - Web UI")
    print("="*80)
    print(f"[KEY] API Key: {'[OK] Configured' if API_CONFIGURED else '[X] Missing (add to .env)'}")
    print(f"[WEB] Server: http://localhost:{web_port}")
    print("="*80)
    print(f"\n[INFO] Open http://localhost:{web_port} in your browser\n")
    
    app.run(debug=True, host='0.0.0.0', port=web_port)
