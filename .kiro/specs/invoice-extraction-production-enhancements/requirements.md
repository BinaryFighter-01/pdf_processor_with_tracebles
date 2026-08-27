# Requirements Document

## Introduction

This document specifies requirements for enhancing the pharma invoice extraction system with four production-ready capabilities: two-pass extraction, multi-page PDF support, result caching, and async batch queue processing. These enhancements aim to improve extraction accuracy, reduce JSON truncation errors, optimize performance through caching, and enable scalable processing of multiple invoices.

The system currently uses a Flask backend with OpenRouter API (Qwen model) to extract structured data from pharma invoices. The enhancements maintain backward compatibility with the existing `/api/extract` endpoint while adding new capabilities through UI toggles and configuration options.

## Glossary

- **System**: The invoice extraction web application (Flask backend + JavaScript frontend)
- **Extraction_Engine**: The OpenRouter API client that processes images and returns structured JSON
- **Cache_Manager**: Component responsible for storing and retrieving cached extraction results
- **Batch_Queue**: In-memory or SQLite-based job queue for processing multiple invoices
- **Preprocessor**: Image preprocessing pipeline that handles rotation, enhancement, and OCR
- **Validator**: Post-processing component that validates and corrects extracted data
- **Header_Fields**: Invoice metadata including invoice number, dates, seller/buyer information, GSTIN, DL numbers
- **Totals_Fields**: Summary financial data including GST amounts, rates, invoice amount, round-off
- **Line_Items**: Individual product rows with batch, quantity, pricing, and tax information
- **Cache_Key**: SHA-256 hash of (file bytes + extraction options) used for cache lookups
- **Job**: A batch extraction task with unique job_id, status, and results
- **Worker**: Parallel processor that executes extraction jobs from the queue

## Requirements

### Requirement 1: Two-Pass Extraction Strategy

**User Story:** As a user processing long pharma invoices, I want the extraction to be split into focused passes per page, so that JSON truncation errors are reduced and field accuracy is improved.

#### Acceptance Criteria

1. THE System SHALL split single-page extraction into three sequential API calls: Pass 1a (header fields), Pass 1b (totals fields), Pass 2 (line items)
2. WHEN Pass 1a executes, THE Extraction_Engine SHALL extract ONLY header fields (invoice_number, invoice_date, due_date, customer_name, customer_gstin, customer_DL_Number, seller_name, seller_gstin, seller_DL_Number, DC_date, DC_number, PO_number) with max_tokens limit of 500
3. WHEN Pass 1b executes, THE Extraction_Engine SHALL extract ONLY totals fields (total_quantity, total_gst_rate, total_cgst_rate, total_cgst_amount, total_sgst_rate, total_sgst_amount, total_igst_rate, total_igst_amount, total_cess_amount, total_gst_amount, round_off, invoice_amount) with max_tokens limit of 300
4. WHEN Pass 2 executes, THE Extraction_Engine SHALL extract ONLY line items array with all item fields with max_tokens limit of 1500
5. WHEN all three passes complete, THE System SHALL merge results into a single JSON object with header fields first, totals fields second, and items array last
6. THE System SHALL provide a UI checkbox labeled "Two-pass extraction" that defaults to enabled state
7. WHEN two-pass extraction is disabled, THE System SHALL use the legacy single-pass extraction with max_tokens of 2500
8. WHEN any pass fails, THE System SHALL return an error response indicating which pass failed and include the partial results from successful passes

### Requirement 2: Multi-Page PDF Processing

**User Story:** As a user receiving multi-page pharma invoices with continuation sheets, I want all pages to be processed and merged, so that complete invoice data including all line items is extracted.

#### Acceptance Criteria

1. WHEN a PDF file contains multiple pages, THE System SHALL process up to MAX_PDF_PAGES pages (configurable via environment variable, default 20)
2. WHEN processing page 1, THE System SHALL extract all fields (header, totals, and line items)
3. WHEN processing pages 2 through N, THE System SHALL extract ONLY line items
4. WHEN merging results, THE System SHALL use header and totals from page 1 exclusively
5. IF invoice_amount field is present on the last page AND differs from page 1, THEN THE System SHALL use totals from the last page and log a warning
6. WHEN merging line items from multiple pages, THE System SHALL concatenate items arrays into a single items array
7. WHEN duplicate line items are detected (same batch number AND description), THE System SHALL skip the duplicate and log a warning
8. THE System SHALL provide a UI checkbox labeled "Multi-page PDF" that defaults to enabled state
9. WHEN a PDF exceeds MAX_PDF_PAGES limit, THE System SHALL process only the first MAX_PDF_PAGES pages and log a warning
10. THE System SHALL include a page_count field in the metadata response indicating total pages processed

### Requirement 3: Result Caching System

**User Story:** As a user re-processing the same invoice files for testing or correction, I want extraction results to be cached, so that I receive instant results without re-invoking the API and incurring additional costs.

#### Acceptance Criteria

1. THE Cache_Manager SHALL generate a cache key using SHA-256 hash of (file bytes + extraction options: use_ocr, two_pass_extraction, multi_page_pdf)
2. WHEN an extraction request is received, THE System SHALL check for cached results using the cache key before invoking the Extraction_Engine
3. WHEN cached results are found AND cache entry is valid, THE System SHALL return cached results with cached: true flag in metadata
4. THE Cache_Manager SHALL store extraction results as JSON files in uploads/.cache/ directory with filename format: {cache_key}.json
5. THE Cache_Manager SHALL store both the extraction result AND metadata (timestamp, filename, extraction_options) in the cache file
6. THE System SHALL provide a UI checkbox labeled "Result cache" that defaults to enabled state
7. WHEN result cache is disabled, THE System SHALL bypass cache lookup and invoke the Extraction_Engine directly
8. THE System SHALL provide a UI indicator displaying "Cached" badge when serving results from cache
9. THE System SHALL provide a POST /api/cache/clear endpoint that deletes all cache files and returns count of deleted entries
10. WHEN cache directory does not exist, THE System SHALL create it automatically on first cache write
11. THE System SHALL include cache_hit boolean and cache_key string in the response metadata

### Requirement 4: Async Batch Queue Processing

**User Story:** As a user with multiple invoices to process, I want to upload them in a batch and monitor progress, so that I can process invoices in parallel and save time.

#### Acceptance Criteria

1. THE System SHALL provide a POST /api/batch endpoint that accepts multiple files and returns a unique job_id
2. WHEN a batch request is received, THE Batch_Queue SHALL create a Job with status "pending" and add it to the processing queue
3. THE Batch_Queue SHALL process up to BATCH_WORKERS jobs in parallel (configurable via environment variable, default 2)
4. WHEN a job begins processing, THE System SHALL update job status to "processing"
5. WHEN a job completes successfully, THE System SHALL update job status to "completed" and store results array
6. WHEN a job fails, THE System SHALL update job status to "failed" and store error message
7. THE System SHALL provide a GET /api/jobs/{job_id} endpoint that returns job status and results
8. THE System SHALL provide a GET /api/jobs endpoint that returns list of recent jobs (up to 100 most recent)
9. THE System SHALL store jobs in an in-memory dictionary or SQLite database (simple queue implementation)
10. THE System SHALL automatically delete completed jobs after 1 hour OR when total completed jobs exceeds 100
11. THE UI SHALL provide multi-file upload functionality with "Batch Extract" button
12. WHEN batch extraction is initiated, THE UI SHALL poll GET /api/jobs/{job_id} every 2 seconds and display progress bar showing completed/total files
13. WHEN polling detects status "completed", THE UI SHALL display results for all files in the batch
14. WHEN polling detects status "failed", THE UI SHALL display error message and partial results if available
15. THE System SHALL include per-file results in batch response with fields: filename, status ("success" or "error"), data (if successful), error (if failed)

### Requirement 5: Extraction Options Configuration

**User Story:** As a system administrator, I want to configure extraction options via environment variables, so that I can tune performance and behavior for different deployment environments.

#### Acceptance Criteria

1. THE System SHALL read MAX_PDF_PAGES from .env file with default value of 20
2. THE System SHALL read BATCH_WORKERS from .env file with default value of 2
3. THE System SHALL read CACHE_ENABLED from .env file with default value of true
4. THE System SHALL read CACHE_DIRECTORY from .env file with default value of "uploads/.cache"
5. THE System SHALL read CACHE_MAX_AGE_HOURS from .env file with default value of 24 (hours)
6. WHEN CACHE_MAX_AGE_HOURS is configured, THE Cache_Manager SHALL exclude cache entries older than CACHE_MAX_AGE_HOURS when performing lookups
7. THE System SHALL validate all numeric environment variables and log warnings for invalid values
8. WHEN an environment variable is invalid, THE System SHALL use the default value and continue operation

### Requirement 6: Backward Compatibility

**User Story:** As a user of the existing system, I want current functionality to remain unchanged, so that my existing integrations and workflows continue to work.

#### Acceptance Criteria

1. THE System SHALL maintain the existing /api/extract endpoint with identical request and response structure
2. WHEN two-pass extraction is disabled AND multi-page PDF is disabled, THE System SHALL execute extraction using the legacy single-pass approach
3. THE System SHALL preserve all existing response fields in the /api/extract response
4. WHEN use_ocr parameter is provided in request, THE System SHALL honor it regardless of other feature toggles
5. THE System SHALL maintain the existing preprocessing pipeline behavior when new features are disabled

### Requirement 7: Pass-Specific Prompt Engineering

**User Story:** As a system developer, I want each extraction pass to have focused prompts, so that the model extracts only relevant fields and reduces token usage.

#### Acceptance Criteria

1. THE System SHALL provide a function get_header_prompt() that returns system and user prompts for Pass 1a with instructions to extract ONLY header fields
2. THE System SHALL provide a function get_totals_prompt() that returns system and user prompts for Pass 1b with instructions to extract ONLY totals fields
3. THE System SHALL provide a function get_items_prompt() that returns system and user prompts for Pass 2 with instructions to extract ONLY line items array
4. WHEN generating pass-specific prompts, THE System SHALL include only the relevant JSON template section for that pass
5. THE System SHALL preserve all existing extraction rules (EARS patterns, field isolation, GST validation) in pass-specific prompts

### Requirement 8: Error Handling and Recovery

**User Story:** As a user experiencing extraction failures, I want detailed error messages and partial results, so that I can understand what went wrong and recover data where possible.

#### Acceptance Criteria

1. WHEN Pass 1a fails, THE System SHALL return error response indicating "Header extraction failed" with error details
2. WHEN Pass 1b fails BUT Pass 1a succeeded, THE System SHALL return partial results with header fields and error message
3. WHEN Pass 2 fails BUT Passes 1a and 1b succeeded, THE System SHALL return partial results with header and totals fields and error message
4. WHEN cache file is corrupted, THE System SHALL log warning, delete corrupted file, and proceed with fresh extraction
5. WHEN batch job processing fails for a file, THE System SHALL continue processing remaining files and mark that file as failed in results
6. THE System SHALL include detailed error information in response including: error_type, error_message, failed_pass (for two-pass extraction), and partial_results (if available)

### Requirement 9: Performance Monitoring

**User Story:** As a system administrator, I want performance metrics for each feature, so that I can monitor system behavior and optimize configuration.

#### Acceptance Criteria

1. THE System SHALL include timing breakdown in response metadata with fields: preprocessing_time, extraction_time (or pass_1a_time, pass_1b_time, pass_2_time), validation_time, total_time
2. THE System SHALL include cache_hit boolean in response metadata
3. WHEN two-pass extraction is enabled, THE System SHALL report individual pass times in metadata
4. WHEN multi-page PDF is processed, THE System SHALL report per-page processing times in metadata
5. THE System SHALL log performance metrics to console with format: "[timestamp] Feature: metric_name = value"

### Requirement 10: Cache Management

**User Story:** As a system administrator, I want to manage cached results, so that I can clear stale data and reclaim disk space.

#### Acceptance Criteria

1. THE System SHALL provide GET /api/cache/stats endpoint that returns: total_entries, total_size_bytes, oldest_entry_age_hours, newest_entry_age_hours
2. THE System SHALL provide POST /api/cache/clear endpoint with optional query parameter max_age_hours that deletes entries older than specified age
3. WHEN max_age_hours is not provided, THE POST /api/cache/clear endpoint SHALL delete all cache entries
4. THE Cache_Manager SHALL automatically delete cache entries older than CACHE_MAX_AGE_HOURS during cache lookups
5. THE System SHALL return deleted_count and freed_space_bytes in the response of POST /api/cache/clear

## Implementation Notes

### Phase 1 (High Priority)
- Requirement 1: Two-Pass Extraction Strategy
- Requirement 3: Result Caching System
- Requirement 5: Extraction Options Configuration (partial - only cache-related config)
- Requirement 7: Pass-Specific Prompt Engineering

### Phase 2 (Medium Priority)
- Requirement 2: Multi-Page PDF Processing
- Requirement 5: Extraction Options Configuration (complete - PDF and batch config)

### Phase 3 (Low Priority)
- Requirement 4: Async Batch Queue Processing

### Cross-Cutting Requirements (All Phases)
- Requirement 6: Backward Compatibility
- Requirement 8: Error Handling and Recovery
- Requirement 9: Performance Monitoring
- Requirement 10: Cache Management

### Technical Considerations

**Token Allocation Strategy:**
- Single-pass: 2500 tokens total
- Two-pass: 500 (header) + 300 (totals) + 1500 (items) = 2300 tokens total
- Allows 200 token buffer for overhead and reduces risk of truncation

**Cache Key Collision:**
- SHA-256 provides negligible collision probability (1 in 2^256)
- Extraction options included in hash ensure different configurations produce different cache entries

**Multi-Page Duplicate Detection:**
- Use tuple of (batch_number, description) as uniqueness key
- Case-insensitive comparison
- Normalize whitespace before comparison

**Batch Queue Implementation:**
- Start with in-memory dict for simplicity
- Migrate to SQLite if persistence is required
- Use threading.Thread for parallel workers (Python GIL acceptable for I/O-bound tasks)

**Backward Compatibility Testing:**
- All new features default to enabled state
- Existing integrations work without changes
- Feature flags can be overridden via request parameters
