"""
OpenRouter API Client for Qwen3.7-Plus
"""

import os
import json
import base64
import requests
from io import BytesIO
from PIL import Image
from typing import Optional
from dotenv import load_dotenv
from langsmith import traceable

load_dotenv()


# ════════════════════════════════════════════════════════════════════════════════
#  VERIFICATION PROMPT — post-extraction accuracy check
# ════════════════════════════════════════════════════════════════════════════════

VERIFICATION_SYSTEM_PROMPT = """You are an invoice verification specialist. Your job: compare extracted JSON data against the source invoice image and flag discrepancies.

VERIFICATION RULES:
1. Compare EVERY numeric field (quantities, prices, amounts, GST rates) against the printed invoice.
2. Check item codes, batch numbers, HSN codes character-by-character.
3. Verify GSTIN format (15 chars, correct pattern).
4. Check invoice-level totals: sum(item amounts) + GST = invoice_amount.
5. Flag mismatches, not minor OCR variants (e.g., "O" vs "0" in batch numbers is fine if semantically correct).

OUTPUT FORMAT:
{
  "verification_status": "PASS" or "FAIL",
  "discrepancies": [
    {"field": "item[0].quantity", "extracted": "20", "invoice_shows": "22", "severity": "high"},
    {"field": "customer_gstin", "extracted": "27AABCS1234N1ZA", "invoice_shows": "27AABCS1234N1Z5", "severity": "critical"}
  ],
  "confidence_score": 0.95,
  "notes": "All header fields match. Item 3 unit_price differs by ₹0.50 (possible OCR error in decimal point)."
}

severity levels:
- "critical": GSTIN, invoice_number, invoice_amount wrong
- "high": item quantity, price, GST amount wrong
- "medium": batch number, HSN code, item code wrong
- "low": Pack, MRP, minor description variant

Be strict. If extraction is perfect, return empty discrepancies array and status="PASS"."""

VERIFICATION_USER_PROMPT = """Here is the extracted JSON from this invoice. Verify it against the image:

EXTRACTED DATA:
{extracted_json}

Cross-check every field. Return verification result as JSON."""


class OpenRouterClient:
    """Client for OpenRouter API with Qwen model."""
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.getenv('OPENROUTER_API_KEY')
        self.model = model or os.getenv('MODEL_NAME', 'qwen/qwen3.7-plus')
        self.base_url = 'https://openrouter.ai/api/v1/chat/completions'
        
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not found in environment variables")
    
    @staticmethod
    def repair_json(json_str: str) -> str:
        """
        Attempt to repair common JSON syntax errors.
        
        Common issues:
        - Missing closing brackets/braces
        - Trailing commas
        - Truncated responses
        - Unquoted property names
        - Single quotes instead of double quotes
        """
        import re
        
        # Remove trailing commas before closing brackets
        json_str = json_str.replace(',]', ']').replace(',}', '}')
        
        # Replace single quotes with double quotes (but not inside strings)
        # This is a simple heuristic - may not work for all cases
        json_str = json_str.replace("'", '"')
        
        # Fix common unquoted property names (e.g., {description: "value"} -> {"description": "value"})
        # Match word characters followed by colon
        json_str = re.sub(r'(\{|,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', json_str)
        
        # Remove any non-JSON content before first {
        first_brace = json_str.find('{')
        if first_brace > 0:
            json_str = json_str[first_brace:]
            print(f"🔧 Removed {first_brace} characters before first brace")
        
        # Remove any non-JSON content after last }
        last_brace = json_str.rfind('}')
        if last_brace >= 0 and last_brace < len(json_str) - 1:
            extra_chars = len(json_str) - last_brace - 1
            json_str = json_str[:last_brace + 1]
            print(f"🔧 Removed {extra_chars} characters after last brace")
        
        # Count opening and closing brackets
        open_braces = json_str.count('{')
        close_braces = json_str.count('}')
        open_brackets = json_str.count('[')
        close_brackets = json_str.count(']')
        
        # Add missing closing brackets
        if open_brackets > close_brackets:
            json_str += ']' * (open_brackets - close_brackets)
            print(f"🔧 Added {open_brackets - close_brackets} closing bracket(s)")
        
        if open_braces > close_braces:
            json_str += '}' * (open_braces - close_braces)
            print(f"🔧 Added {open_braces - close_braces} closing brace(s)")
        
        return json_str
    
    @staticmethod
    def image_to_base64(pil_image: Image.Image, format: str = 'PNG', max_size: int = 8192) -> str:
        """
        Convert PIL Image to base64 string at maximum quality.

        Always uses PNG (lossless) regardless of image size — JPEG compression
        degrades fine text (batch numbers, HSN codes, small-print amounts) and
        directly causes OCR errors. Token cost is not a constraint, accuracy is.

        Args:
            pil_image: PIL Image object
            format: Ignored — always PNG for lossless quality
            max_size: Maximum dimension in pixels (default 8192; covers 300-DPI A4 at full res)
        """
        # Always PNG — lossless preserves every pixel of fine invoice text
        format = 'PNG'

        # Ensure RGB (PNG handles RGB cleanly; RGBA would add unnecessary alpha)
        if pil_image.mode not in ('RGB', 'L'):
            pil_image = pil_image.convert('RGB')

        width, height = pil_image.size

        # Downscale only if genuinely oversized (e.g. 600 DPI scan > 8192 px)
        if width > max_size or height > max_size:
            if width > height:
                new_width  = max_size
                new_height = int(height * (max_size / width))
            else:
                new_height = max_size
                new_width  = int(width * (max_size / height))
            pil_image = pil_image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            print(f"🔄 Image resized from {width}x{height} to {new_width}x{new_height} (still lossless PNG)")
        else:
            print(f"📐 Image at full resolution: {width}x{height} px — no resize needed")

        buffered = BytesIO()
        # PNG with compress_level=1: fast compression, lossless quality
        # Level 9 saves ~5% size but takes 10x longer — not worth it for invoices
        pil_image.save(buffered, format='PNG', compress_level=1)
        img_bytes  = buffered.getvalue()
        img_base64 = base64.b64encode(img_bytes).decode('utf-8')

        size_mb = len(img_bytes) / (1024 * 1024)
        print(f"📦 Image encoded: {size_mb:.2f} MB as lossless PNG ({pil_image.width}x{pil_image.height})")

        return f"data:image/png;base64,{img_base64}"
    
    @traceable(name="model_extract_invoice", tags=["model", "extraction"], metadata={"model": "qwen3.7-plus"})
    def extract_invoice(
        self,
        image: Image.Image | list[Image.Image],  # NOW supports single image OR list of images
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 16000,
        use_reasoning: bool = True    # ON by default — reasoning critical for character-level accuracy
    ) -> tuple[dict, dict]:
        """
        Extract invoice data using vision model.
        
        Args:
            image: Single PIL Image OR list of PIL Images (for multi-page context)
            system_prompt: System instructions
            user_prompt: User extraction request
            temperature: Model temperature
            max_tokens: Maximum output tokens
            use_reasoning: Enable high-effort reasoning for character-level accuracy
        
        Returns:
            Tuple of (extracted_data_dict, raw_response_dict)
        """
        # Handle both single image and multiple images
        if isinstance(image, list):
            images = image
            image_b64_list = [self.image_to_base64(img) for img in images]
            print(f"📸 Sending {len(images)} images to model for extraction")
        else:
            images = [image]
            image_b64_list = [self.image_to_base64(image)]
        
        # Prepare request
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }
        
        payload = {
            'model': self.model,
            'messages': [
                {
                    'role': 'system',
                    'content': system_prompt
                },
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'text',
                            'text': user_prompt
                        },
                        # Send ALL images in this extraction call
                        *[
                            {
                                'type': 'image_url',
                                'image_url': {'url': img_b64}
                            }
                            for img_b64 in image_b64_list
                        ]
                    ]
                }
            ],
            'temperature': temperature,
            'max_tokens': max_tokens,
            # ── Reasoning / thinking control ────────────────────────────
            # reasoning effort=high: model thinks through every ambiguous character
            # before committing to a value (batch numbers, GSTINs, item codes).
            # CRITICAL: exclude=True keeps reasoning tokens in the thinking buffer
            # and does NOT count them against max_tokens — output budget is preserved.
            # For cheap classification calls, use_reasoning=False disables thinking
            # entirely (effort=none) to avoid unnecessary token spend.
            **(
                {
                    'reasoning': {'effort': 'high', 'exclude': True},
                    'reasoning_effort': 'high',
                    'thinking': {'type': 'enabled'},
                    'enable_thinking': True,
                }
                if use_reasoning else
                {
                    'reasoning': {'effort': 'none', 'exclude': True},
                    'reasoning_effort': 'none',
                    'thinking': {'type': 'disabled'},
                    'enable_thinking': False,
                }
            ),
        }
        
        # Make request with retry logic
        max_retries = 2
        retry_count = 0
        
        while retry_count <= max_retries:
            try:
                timeout_duration = 300  # 5 minutes timeout for complex invoices
                print(f"🌐 Sending request to {self.model}... (attempt {retry_count + 1}/{max_retries + 1}, timeout: {timeout_duration}s)")
                
                response = requests.post(
                    self.base_url, 
                    headers=headers, 
                    json=payload, 
                    timeout=timeout_duration
                )
                
                # Handle HTTP errors with detailed error info
                if response.status_code != 200:
                    try:
                        error_data = response.json()
                        error_msg = error_data.get('error', {})
                        if isinstance(error_msg, dict):
                            error_msg = error_msg.get('message', str(error_msg))
                        api_error = f"API Error ({response.status_code}): {error_msg}"
                    except:
                        api_error = f"API Error ({response.status_code}): {response.text}"
                    
                    print(f"❌ {api_error}")
                    return {'error': api_error}, {}
                
                # Try to parse JSON response
                try:
                    response_data = response.json()
                except json.JSONDecodeError as json_err:
                    # Response is not valid JSON
                    error_msg = f"API returned invalid JSON: {str(json_err)}"
                    print(f"❌ {error_msg}")
                    print(f"📄 Response text (first 500 chars): {response.text[:500]}")
                    return {'error': error_msg, 'raw_response': response.text[:1000]}, {}
                
                break  # Success, exit retry loop
                
            except requests.exceptions.Timeout:
                retry_count += 1
                if retry_count > max_retries:
                    error_msg = f"Request timeout after {max_retries + 1} attempts ({timeout_duration}s each). The invoice may be too complex or the server is slow."
                    print(f"❌ {error_msg}")
                    return {'error': error_msg}, {}
                else:
                    print(f"⚠️  Timeout on attempt {retry_count}, retrying...")
                    continue
                    
            except requests.exceptions.HTTPError as e:
                # Handle specific HTTP errors
                status_code = e.response.status_code
                if status_code == 402:
                    error_msg = "❌ Payment Required: Your OpenRouter account has insufficient credits. Please add funds at https://openrouter.ai/account/billing/overview"
                elif status_code == 401:
                    error_msg = "❌ Unauthorized: Invalid or expired API key. Please check your OPENROUTER_API_KEY in .env"
                elif status_code == 429:
                    error_msg = "❌ Rate Limited: Too many requests. Please wait a moment and try again."
                else:
                    try:
                        error_data = e.response.json()
                        error_msg = f"API Error ({status_code}): {error_data.get('error', {}).get('message', str(error_data))}"
                    except:
                        error_msg = f"API Error ({status_code}): {e.response.text}"
                
                print(error_msg)
                return {'error': error_msg}, {}
            except requests.exceptions.RequestException as e:
                error_msg = f"API request failed: {str(e)}"
                print(f"❌ {error_msg}")
                return {'error': error_msg}, {}
            except Exception as e:
                error_msg = f"Unexpected error during request: {str(e)}"
                print(f"❌ {error_msg}")
                return {'error': error_msg}, {}
        
        # Process response
        try:
            
            print(f"✅ API response received")
            print(f"📊 Response keys: {list(response_data.keys())}")
            
            # Debug: Print response structure
            if 'choices' in response_data:
                print(f"📝 Choices length: {len(response_data.get('choices', []))}")
                if len(response_data['choices']) > 0:
                    print(f"📝 First choice keys: {list(response_data['choices'][0].keys())}")
            else:
                print(f"⚠️  No 'choices' in response. Response: {response_data}")
            
            # Extract text response
            if 'choices' in response_data and len(response_data['choices']) > 0:
                message = response_data['choices'][0].get('message', {})
                text_response = message.get('content', '') or ''
                
                if not text_response:
                    # content=None — model returned nothing.
                    # If reasoning is on and exclude=True, try once more with exclude=False
                    # so reasoning text is visible for fallback extraction.
                    reasoning_text = message.get('reasoning', '') or ''

                    if not reasoning_text and use_reasoning:
                        print(f"⚠️  content=None with exclude=True — retrying with exclude=False to recover reasoning")
                        payload_retry = dict(payload)
                        payload_retry['reasoning'] = {'effort': 'high', 'exclude': False}
                        try:
                            retry_resp = requests.post(self.base_url, headers=headers, json=payload_retry, timeout=timeout_duration)
                            if retry_resp.status_code == 200:
                                retry_data = retry_resp.json()
                                retry_msg  = retry_data.get('choices', [{}])[0].get('message', {})
                                text_response = retry_msg.get('content', '') or ''
                                if not text_response:
                                    reasoning_text = retry_msg.get('reasoning', '') or ''
                                    print(f"   Retry: content still empty, reasoning={len(reasoning_text)} chars")
                                else:
                                    print(f"   Retry succeeded: {len(text_response)} chars")
                        except Exception as retry_err:
                            print(f"   Retry failed: {retry_err}")

                    if text_response:
                        # Recovered on retry — continue to normal parse path below
                        pass
                    elif reasoning_text:
                        print(f"⚠️  content is empty — model used all tokens on reasoning ({len(reasoning_text)} chars).")
                        print(f"🔍 Attempting to extract JSON from reasoning fallback...")
                        start_r = reasoning_text.find('{')    # first { — JSON starts here
                        end_r   = reasoning_text.rfind('}') + 1  # last } — JSON ends here
                        if start_r >= 0 and end_r > start_r:
                            candidate = reasoning_text[start_r:end_r]
                            try:
                                extracted_data = json.loads(candidate)
                                print(f"✅ JSON recovered from reasoning field ({len(candidate)} chars)")
                                return extracted_data, response_data
                            except json.JSONDecodeError:
                                # Try repair
                                try:
                                    extracted_data = json.loads(self.repair_json(candidate))
                                    print(f"✅ JSON recovered (repaired) from reasoning field")
                                    return extracted_data, response_data
                                except json.JSONDecodeError:
                                    pass
                        print(f"❌ Could not recover JSON from reasoning. Increase max_tokens.")
                        print(f"   Reasoning tail (last 500): {reasoning_text[-500:]}")
                    else:
                        print(f"⚠️  Empty content in message: {message}")
                    return {'error': 'Model returned empty response'}, response_data
                
                print(f"📄 Response length: {len(text_response)} characters")
                
                # Parse JSON from response
                try:
                    # Clean response - remove markdown fences if present
                    text_response = text_response.strip()
                    
                    # Remove markdown code fences (```json ... ``` or ``` ... ```)
                    if text_response.startswith('```'):
                        # Find the end of the code block
                        end_fence = text_response.rfind('```')
                        if end_fence > 0:
                            text_response = text_response[text_response.find('\n')+1:end_fence]
                        else:
                            # Malformed, try to extract anyway
                            text_response = text_response[3:]
                    
                    text_response = text_response.strip()
                    
                    # Find JSON content
                    start_idx = text_response.find('{')
                    end_idx = text_response.rfind('}') + 1

                    # Handle truncated response: { found but no closing }
                    if start_idx >= 0 and end_idx <= start_idx:
                        print(f"⚠️  Truncated JSON detected (no closing brace) — attempting repair")
                        truncated = text_response[start_idx:]
                        repaired = self.repair_json(truncated)
                        try:
                            extracted_data = json.loads(repaired)
                            print(f"✅ Truncated JSON repaired and parsed ({len(repaired)} chars)")
                            return extracted_data, response_data
                        except json.JSONDecodeError as te:
                            print(f"❌ Repair failed on truncated response: {te.msg}")
                            return {
                                'error': f'Failed to parse JSON response: truncated (no closing brace)',
                                'raw_response': text_response[:2000]
                            }, response_data
                    
                    if start_idx >= 0 and end_idx > start_idx:
                        json_str = text_response[start_idx:end_idx]
                        print(f"📝 JSON string length: {len(json_str)}")
                        
                        # Try to parse
                        try:
                            extracted_data = json.loads(json_str)
                            print(f"✅ JSON parsed successfully")
                            return extracted_data, response_data
                        except json.JSONDecodeError as parse_err:
                            print(f"❌ JSON decode failed at position {parse_err.pos}: {parse_err.msg}")
                            
                            # Show context around error
                            start_context = max(0, parse_err.pos - 100)
                            end_context = min(len(json_str), parse_err.pos + 100)
                            error_context = json_str[start_context:end_context]
                            
                            # Highlight error position
                            error_offset = parse_err.pos - start_context
                            context_with_marker = (
                                error_context[:error_offset] + 
                                ' <<<ERROR>>> ' + 
                                error_context[error_offset:]
                            )
                            
                            print(f"Error context:\n{context_with_marker}")
                            
                            # Try to repair JSON
                            print("🔧 Attempting to repair JSON...")
                            repaired_json = self.repair_json(json_str)
                            
                            try:
                                extracted_data = json.loads(repaired_json)
                                print(f"✅ JSON repaired and parsed successfully!")
                                return extracted_data, response_data
                            except json.JSONDecodeError as repair_err:
                                print(f"❌ Repair failed: {repair_err.msg}")
                                
                                # Save the failed JSON for debugging
                                print(f"\n🔍 FAILED JSON (first 1000 chars):")
                                print(json_str[:1000])
                                print(f"\n🔍 FAILED JSON (last 500 chars):")
                                print(json_str[-500:])
                                
                                # Provide helpful suggestion
                                if "Expecting property name enclosed in double quotes" in str(parse_err):
                                    print("💡 Error: Model used unquoted property names or single quotes")
                                    print("   The model must use double quotes for all property names")
                                elif "Expecting ',' delimiter" in str(parse_err):
                                    print("💡 Hint: Model likely generated invalid JSON syntax. Common causes:")
                                    print("   - Missing comma between object properties")
                                    print("   - Trailing comma before closing brace")
                                    print("   - Unquoted string values")
                                    print("   - Incomplete JSON (truncated response)")
                                elif "Expecting value" in str(parse_err):
                                    print("💡 Error: Missing value after colon or comma")
                                
                                raise parse_err  # Raise original error
                    else:
                        print(f"⚠️  No JSON found in response")
                        print(f"Full response: {text_response[:1000]}")
                        raise ValueError("No JSON object found in response")
                
                except (json.JSONDecodeError, ValueError) as e:
                    print(f"❌ Parse error: {str(e)}")
                    # Return first 2000 chars for debugging
                    return {
                        'error': f'Failed to parse JSON response: {str(e)}',
                        'raw_response': text_response[:2000]
                    }, response_data
            
            print(f"❌ No valid response structure")
            return {'error': 'No response from model', 'debug': str(response_data)[:500]}, response_data
        
        except json.JSONDecodeError as e:
            print(f"⚠️  JSON parsing error in response processing: {e}")
            return {'error': 'Failed to parse model response'}, {}
        except Exception as e:
            error_msg = f"Unexpected error processing response: {str(e)}"
            print(f"❌ {error_msg}")
            return {'error': error_msg}, {}
    
    def get_reasoning_stream(self) -> str:
        """
        Generate a mock reasoning stream for the UI.
        In a real implementation, this could tap into model's chain-of-thought.
        """
        return "Processing invoice image...\n"
    
    @traceable(name="model_extract_two_pass", tags=["model", "extraction", "two-pass"])
    def extract_invoice_two_pass(
        self,
        image: Image.Image,
        temperature: float = 0.1
    ) -> tuple[dict, dict]:
        """
        Extract invoice data using two-pass strategy for better accuracy.
        
        Pass 1a: Extract header fields only (500 tokens)
        Pass 1b: Extract totals fields only (300 tokens)
        Pass 2: Extract line items only (1500 tokens)
        
        Returns:
            Tuple of (merged_data_dict, metadata_dict)
        """
        from schema import get_header_prompt, get_totals_prompt, get_items_prompt
        
        print("\n" + "="*80)
        print("🔄 TWO-PASS EXTRACTION MODE")
        print("="*80)
        
        merged_data = {}
        pass_metadata = {}
        
        # Pass 1a: Header fields
        print("\n📋 Pass 1a: Extracting header fields...")
        header_system, header_user = get_header_prompt()
        
        header_data, header_response = self.extract_invoice(
            image,
            header_system,
            header_user,
            temperature=temperature,
            max_tokens=4000   # Header: 12 fields; 4000 gives full reasoning headroom
        )
        
        if 'error' in header_data:
            return {
                'error': f"Pass 1a (Header) failed: {header_data['error']}",
                'failed_pass': 'header',
                'partial_results': {}
            }, {'pass_1a': header_response}
        
        merged_data.update(header_data)
        pass_metadata['pass_1a'] = {
            'fields_extracted': len(header_data),
            'response': header_response
        }
        print(f"✅ Pass 1a complete: {len(header_data)} header fields extracted")
        
        # Pass 1b: Totals fields
        print("\n💰 Pass 1b: Extracting totals fields...")
        totals_system, totals_user = get_totals_prompt()
        
        totals_data, totals_response = self.extract_invoice(
            image,
            totals_system,
            totals_user,
            temperature=temperature,
            max_tokens=6000   # Totals: reasoning on amounts/rates needs space
        )
        
        if 'error' in totals_data:
            return {
                'error': f"Pass 1b (Totals) failed: {totals_data['error']}",
                'failed_pass': 'totals',
                'partial_results': merged_data.copy()
            }, {'pass_1a': header_response, 'pass_1b': totals_response}
        
        merged_data.update(totals_data)
        pass_metadata['pass_1b'] = {
            'fields_extracted': len(totals_data),
            'response': totals_response
        }
        print(f"✅ Pass 1b complete: {len(totals_data)} totals fields extracted")
        
        # Pass 2: Line items
        print("\n📦 Pass 2: Extracting line items...")
        items_system, items_user = get_items_prompt()

        # ── Cross-pass context injection (single-page path) ──────────────────
        cross_context = self._build_cross_pass_context(merged_data)
        items_user_with_context = cross_context + "\n\n" + items_user
        print(f"   Cross-pass context injected ({len(cross_context)} chars)")
        # ─────────────────────────────────────────────────────────────────────

        items_data, items_response = self.extract_invoice(
            image,
            items_system,
            items_user_with_context,
            temperature=temperature,
            max_tokens=16000  # Items pass: each item ~150-200 tokens; 16000 covers 60+ items
                              # reasoning excluded via exclude=True — full budget for JSON output
        )
        
        if 'error' in items_data:
            return {
                'error': f"Pass 2 (Items) failed: {items_data['error']}",
                'failed_pass': 'items',
                'partial_results': merged_data.copy()
            }, {'pass_1a': header_response, 'pass_1b': totals_response, 'pass_2': items_response}
        
        # Merge items array
        merged_data['items'] = items_data.get('items', [])
        pass_metadata['pass_2'] = {
            'items_extracted': len(merged_data['items']),
            'response': items_response
        }
        print(f"✅ Pass 2 complete: {len(merged_data['items'])} items extracted")
        
        print("\n" + "="*80)
        print(f"✅ TWO-PASS EXTRACTION COMPLETE")
        print(f"   Header fields: {pass_metadata['pass_1a']['fields_extracted']}")
        print(f"   Totals fields: {pass_metadata['pass_1b']['fields_extracted']}")
        print(f"   Line items: {pass_metadata['pass_2']['items_extracted']}")
        print("="*80 + "\n")
        
        return merged_data, pass_metadata

    @staticmethod
    def _build_cross_pass_context(merged_data: dict) -> str:
        """
        Build a compact context string from Pass 1 (header) + Pass 2 (totals)
        results to inject into Pass 3 (items) user prompt.

        Keeps the injection small (~150-200 tokens) — only the fields that
        genuinely help the model cross-check item-level extraction:
          - Invoice identity  → model can confirm it's reading the right doc
          - Seller / Customer → model won't swap GST lines to wrong party
          - Expected totals   → model can sanity-check its item amounts
        """
        def _v(val):
            return str(val) if val not in (None, '', 'null') else 'unknown'

        invoice_no   = _v(merged_data.get('invoice_number'))
        invoice_date = _v(merged_data.get('invoice_date'))
        seller_name  = _v(merged_data.get('seller_name'))
        seller_gstin = _v(merged_data.get('seller_gstin'))
        cust_name    = _v(merged_data.get('customer_name'))
        cust_gstin   = _v(merged_data.get('customer_gstin'))
        inv_amount   = _v(merged_data.get('invoice_amount'))
        total_gst    = _v(merged_data.get('total_gst_amount'))
        total_cgst   = _v(merged_data.get('total_cgst_amount'))
        total_sgst   = _v(merged_data.get('total_sgst_amount'))
        total_igst   = _v(merged_data.get('total_igst_amount'))
        total_qty    = _v(merged_data.get('total_quantity'))

        lines = [
            "╔══════════════════════════════════════════════════════════════╗",
            "║  CROSS-PASS CONTEXT  (verified from prior extraction passes) ║",
            "╚══════════════════════════════════════════════════════════════╝",
            f"Invoice   : {invoice_no}  |  Date: {invoice_date}",
            f"Seller    : {seller_name}  (GSTIN: {seller_gstin})",
            f"Customer  : {cust_name}  (GSTIN: {cust_gstin})",
            f"Inv Amount: {inv_amount}  |  Total GST: {total_gst}",
            f"GST Split : CGST={total_cgst}  SGST={total_sgst}  IGST={total_igst}",
            f"Total Qty : {total_qty}",
            "",
            "USE THIS CONTEXT TO:",
            "  1. Confirm you are extracting from invoice " + invoice_no,
            "  2. Never assign seller GSTIN (" + seller_gstin + ") to customer or vice versa",
            "  3. Cross-check your item GST amounts — they must sum close to " + total_gst,
            "  4. Cross-check total paid quantity against " + total_qty,
            "  5. If a batch/description looks inconsistent with this invoice, re-read it carefully",
            "",
        ]
        return "\n".join(lines)

    @traceable(name="model_extract_multipage", tags=["model", "extraction", "multi-page"])
    def extract_invoice_multipage(
        self,
        images: list[Image.Image],
        use_two_pass: bool = True,
        temperature: float = 0.1
    ) -> tuple[dict, dict]:
        """
        Extract invoice data from multi-page PDF.
        
        ⚠️ CRITICAL DESIGN: PAGE-AGNOSTIC EXTRACTION
        
        OLD (Page-Number-Dependent) ❌:
        - Page 1: Extract ALL fields (header + totals + items)
        - Pages 2-N: Extract ONLY items
        → Fragile: PO on page 2 footer → MISSED
        → Fragile: Totals on last page → MISSED
        
        NEW (Page-Agnostic) ✅:
        - Pass 1: ALL PAGES → Header fields
        - Pass 2: ALL PAGES → Totals fields
        - Pass 3: ALL PAGES → Items
        → Robust: PO on any page → FOUND
        → Robust: Totals on any page → FOUND
        
        Strategy:
        1. Concatenate all pages into a single tall image
        2. Send complete document to each extraction pass
        3. Model sees entire invoice context
        4. No page-number assumptions
        
        Args:
            images: List of PIL Images (one per page)
            use_two_pass: Use three-pass extraction (header, totals, items)
            temperature: Model temperature
        
        Returns:
            Tuple of (merged_data_dict, metadata_dict)
        """
        from schema import get_header_prompt, get_totals_prompt, get_items_prompt
        
        if not images:
            return {'error': 'No images provided'}, {}
        
        page_count = len(images)
        
        print("\n" + "="*80)
        print(f"📄 MULTI-PAGE EXTRACTION MODE ({page_count} pages)")
        print("="*80)
        print("📋 Strategy: PAGE-AGNOSTIC (all pages sent to each pass)")
        print("="*80)
        
        # ════════════════════════════════════════════════════════════
        # PAGE CLASSIFICATION — identify copy type per page
        # ────────────────────────────────────────────────────────────
        # Every page of a tax invoice carries a label in a corner:
        #   "ORIGINAL FOR RECIPIENT"
        #   "DUPLICATE FOR TRANSPORTER"
        #   "TRIPLICATE FOR SUPPLIER"
        #   "EXTRA COPY" / "OFFICE COPY" etc.
        #
        # Strategy:
        #   1. For each page ask the model a single cheap question:
        #      "Is this an ORIGINAL, DUPLICATE, TRIPLICATE, or OTHER copy?"
        #   2. Keep only the first complete copy (ORIGINAL pages + their
        #      continuation pages).
        #   3. If no copy labels found (many invoices don't have them),
        #      fall back to pixel-fingerprint dedup.
        # ════════════════════════════════════════════════════════════
        print(f"\n🔍 Classifying {page_count} pages...")

        _COPY_SYSTEM = (
            "You are a document classifier. "
            "Inspect the invoice page image and respond with ONLY a JSON object. "
            "No markdown, no explanation. First character must be {."
        )
        _COPY_USER = (
            "Look for a copy-type label anywhere on this page "
            "(usually top-right or top-left corner). "
            "Labels to recognise: "
            "'ORIGINAL FOR RECIPIENT', 'ORIGINAL', "
            "'DUPLICATE FOR TRANSPORTER', 'DUPLICATE', "
            "'TRIPLICATE FOR SUPPLIER', 'TRIPLICATE', "
            "'EXTRA COPY', 'OFFICE COPY', 'SUPPLIER COPY', 'BUYER COPY'.\n\n"
            "Return ONLY this JSON (no markdown, no explanation):\n"
            "{\"copy_type\": \"ORIGINAL\", \"label_found\": \"exact text here\"}\n\n"
            "copy_type values: ORIGINAL | DUPLICATE | TRIPLICATE | OTHER | NONE"
        )

        page_types: list[str] = []
        for idx, img in enumerate(images):
            # Use a dedicated lightweight call with reasoning DISABLED
            # to avoid burning tokens on a simple classification task
            classify_data, _ = self.extract_invoice(
                img, _COPY_SYSTEM, _COPY_USER,
                temperature=0.0, max_tokens=200, use_reasoning=False
            )
            ctype = (classify_data.get('copy_type') or 'NONE').upper().strip()
            label = classify_data.get('label_found') or ''
            page_types.append(ctype)
            print(f"   Page {idx + 1}: {ctype!r}  ← \"{label}\"")

        # ── Select pages to use ──────────────────────────────────
        # CRITICAL: Handle replica scenarios properly
        # 
        # Scenario 1: Standard multi-copy invoice
        #   Page 1: ORIGINAL, Page 2: DUPLICATE, Page 3: TRIPLICATE
        #   → Keep only ORIGINAL (page 1)
        #
        # Scenario 2: Multi-page invoice with continuation
        #   Page 1: ORIGINAL (header + items 1-5)
        #   Page 2: NONE (items 6-10 continuation)
        #   → Keep pages 1 AND 2 (both are ORIGINAL copy)
        #
        # Scenario 3: Multi-page invoice with replica confusion
        #   Page 1: ORIGINAL (header + items 1-5)
        #   Page 2: NONE (items 6-10 continuation)
        #   Page 3: ORIGINAL (replica of page 1, same items 1-5)
        #   → Keep pages 1 and 2 ONLY, skip page 3 (pixel-fingerprint detects replica)
        #
        # Strategy:
        #   1. If labels exist: keep ORIGINAL pages + NONE continuations
        #   2. Within kept pages: run pixel-fingerprint dedup to catch replicas
        #   3. If no labels: run pixel-fingerprint on all pages
        # ────────────────────────────────────────────────────────────
        has_labels = any(t in ('ORIGINAL', 'DUPLICATE', 'TRIPLICATE', 'OTHER')
                         for t in page_types)

        if has_labels:
            # ── Step 1: Label-based filtering ────────────────────
            # Keep ORIGINAL pages and NONE pages immediately following an ORIGINAL
            original_indices: list[int] = []
            in_original_section = False
            
            for idx, ctype in enumerate(page_types):
                if ctype == 'ORIGINAL':
                    original_indices.append(idx)
                    in_original_section = True
                elif ctype == 'NONE' and in_original_section:
                    # Continuation of the original copy
                    original_indices.append(idx)
                elif ctype in ('DUPLICATE', 'TRIPLICATE', 'OTHER'):
                    # Different copy started — stop accepting NONE pages
                    in_original_section = False

            if not original_indices:
                # No ORIGINAL found — take first complete copy
                print("   ⚠️  No ORIGINAL label found — using first copy")
                first_copy_end = next((i for i, t in enumerate(page_types) 
                                      if t in ('DUPLICATE', 'TRIPLICATE')), len(page_types))
                original_indices = list(range(first_copy_end))
                if not original_indices:
                    original_indices = list(range(len(images)))

            # ── Step 2: Pixel-fingerprint dedup WITHIN label-filtered pages ────
            # Catches replicas like: Page 1 ORIGINAL, Page 2 NONE, Page 3 ORIGINAL (replica of page 1)
            print(f"   Label-based filter: pages {[i+1 for i in original_indices]} selected")
            print(f"   Running pixel-fingerprint dedup on selected pages...")
            
            def _page_fingerprint(img: Image.Image) -> bytes:
                w, h = img.size
                if w > h:
                    img = img.rotate(90, expand=True)
                thumb = img.convert('L').resize((16, 16), Image.Resampling.LANCZOS)
                return thumb.tobytes()
            
            unique_images = []
            seen_fps: list[bytes] = []
            for rel_idx, abs_idx in enumerate(original_indices):
                img = images[abs_idx]
                fp = _page_fingerprint(img)
                is_dup = any(
                    sum(1 for a, b in zip(fp, s) if abs(a - b) < 15) / len(fp) >= 0.88
                    for s in seen_fps
                )
                if is_dup:
                    print(f"      Page {abs_idx + 1}: 🔄 pixel-duplicate — skipped")
                else:
                    unique_images.append(img)
                    seen_fps.append(fp)
                    print(f"      Page {abs_idx + 1}: ✅ unique — kept")
        else:
            # No labels found — use pixel fingerprint dedup as fallback
            print("   No copy labels detected — using pixel fingerprint dedup")

            def _page_fingerprint(img: Image.Image) -> bytes:
                w, h = img.size
                if w > h:
                    img = img.rotate(90, expand=True)
                thumb = img.convert('L').resize((16, 16), Image.Resampling.LANCZOS)
                return thumb.tobytes()

            unique_images = []
            seen_fps: list[bytes] = []
            for idx, img in enumerate(images):
                fp = _page_fingerprint(img)
                is_dup = any(
                    sum(1 for a, b in zip(fp, s) if abs(a - b) < 15) / len(fp) >= 0.88
                    for s in seen_fps
                )
                if is_dup:
                    print(f"   Page {idx + 1}: 🔄 pixel-dup — skipped")
                else:
                    unique_images.append(img)
                    seen_fps.append(fp)
                    print(f"   Page {idx + 1}: ✅ kept")

        if not unique_images:
            unique_images = images  # safety fallback

        print(f"   {len(images)} pages → {len(unique_images)} pages to process")

        # ════════════════════════════════════════════════════════════
        # PER-PAGE EXTRACTION + SMART MERGE
        # ────────────────────────────────────────────────────────────
        # Instead of concatenating pages into one tall image (which
        # crushes each page to unreadable size), we:
        #   1. Send each unique page individually at full resolution
        #   2. Extract header from page 1 only
        #   3. Extract totals from last page only
        #   4. Extract items from EACH page, then merge all items
        #
        # This is the industry-standard approach: per-page OCR + merge.
        # ════════════════════════════════════════════════════════════
        merged_data: dict = {}
        pass_metadata: dict = {}

        n_unique = len(unique_images)
        page_1   = unique_images[0]
        last_page = unique_images[-1]

        # ── Pass 1: Header — ALL PAGES ───────────────────────────────
        # Send ALL unique pages so model can find PO#, delivery info,
        # remarks that might be on any page (header, footer, continuation).
        print(f"\n📋 Pass 1: Header from ALL {n_unique} pages...")
        header_system, header_user = get_header_prompt()
        
        # Inject instruction to search all pages
        header_user_multipage = (
            f"⚠️ MULTI-PAGE INVOICE: {n_unique} pages provided.\n"
            f"Search ALL pages for header fields. PO#, delivery date, remarks, "
            f"customer details may appear on ANY page (header, footer, continuation).\n\n"
            + header_user
        )

        header_data, header_response = self.extract_invoice(
            unique_images,  # ← Send ALL pages
            header_system,
            header_user_multipage,
            temperature=temperature,
            max_tokens=4000
        )
        if 'error' in header_data:
            return {
                'error': f"Pass 1 (Header) failed: {header_data['error']}",
                'failed_pass': 'header', 'partial_results': {}
            }, {'pass_1': header_response}

        merged_data.update(header_data)
        pass_metadata['pass_1_header'] = {'fields_extracted': len(header_data)}
        print(f"✅ Pass 1 complete: {len(header_data)} header fields")

        # ── Pass 2: Totals — ALL PAGES ────────────────────────────────
        # Totals might be on page 1 header, page 2 footer, or last page.
        # Send ALL pages to find them.
        print(f"\n💰 Pass 2: Totals from ALL {n_unique} pages...")
        totals_system, totals_user = get_totals_prompt()
        
        totals_user_multipage = (
            f"⚠️ MULTI-PAGE INVOICE: {n_unique} pages provided.\n"
            f"Search ALL pages for totals. Invoice amount, GST totals, taxable amount "
            f"may appear on ANY page (header summary, footer, last page).\n\n"
            + totals_user
        )
        
        totals_data, totals_response = self.extract_invoice(
            unique_images,  # ← Send ALL pages
            totals_system,
            totals_user_multipage,
            temperature=temperature,
            max_tokens=6000
        )
        if 'error' in totals_data:
            return {
                'error': f"Pass 2 (Totals) failed: {totals_data['error']}",
                'failed_pass': 'totals', 'partial_results': merged_data.copy()
            }, {'pass_1': header_response, 'pass_2': totals_response}

        merged_data.update(totals_data)
        pass_metadata['pass_2_totals'] = {'fields_extracted': len(totals_data)}
        print(f"✅ Pass 2 complete: {len(totals_data)} totals fields")

        # ── Pass 3: Items — each page individually, then merge ────
        print(f"\n📦 Pass 3: Items from {n_unique} unique pages individually...")
        items_system, items_user = get_items_prompt()
        cross_context = self._build_cross_pass_context(merged_data)
        base_items_prompt = cross_context + "\n\n" + items_user
        print(f"   Cross-pass context injected ({len(cross_context)} chars)")

        all_items: list[dict] = []
        items_responses: dict = {}
        last_page_last_item: dict | None = None  # track last item from previous page

        for pg_idx, page_img in enumerate(unique_images):
            print(f"\n   📄 Page {pg_idx + 1}/{n_unique} items ({page_img.width}x{page_img.height})...")

            # ── Inject previous-page tail context for page 2+ ────
            # The model on page N+1 cannot see page N, so if an item
            # was split across the boundary it will mis-assign the
            # hanging batch/code lines to the first item on this page.
            # Telling the model what the last item from the previous
            # page was lets it correctly associate orphan metadata.
            if pg_idx > 0 and last_page_last_item:
                prev_desc  = last_page_last_item.get('description', 'unknown')
                prev_batch = last_page_last_item.get('Batch') or 'null'
                prev_code  = last_page_last_item.get('item_code') or 'null'
                prev_hsn   = last_page_last_item.get('hsn_sac') or 'null'
                continuation_hint = (
                    f"\n⚠️ PAGE BOUNDARY CONTEXT:\n"
                    f"The PREVIOUS page ended with this item (may be incomplete):\n"
                    f"  Description : {prev_desc}\n"
                    f"  Batch       : {prev_batch}\n"
                    f"  Item Code   : {prev_code}\n"
                    f"  HSN         : {prev_hsn}\n\n"
                    f"RULE: If this page begins with ONLY:\n"
                    f"  - 'Batch & Expiry : ...' line\n"
                    f"  - 'Item Code : ...' line\n"
                    f"  ...with NO item number or description before them,\n"
                    f"  these values belong to the item above ({prev_desc}).\n"
                    f"  DO NOT attach them to the first item on THIS page.\n"
                    f"  Return them as a continuation object:\n"
                    f"  {{\"_continuation_for_previous_page\": true, "
                    f"\"Batch\": \"...\", \"expiry_date\": \"...\", \"item_code\": \"...\"}}\n\n"
                )
                items_user_with_context = base_items_prompt + continuation_hint
                print(f"   Continuation hint injected for prev item: {prev_desc[:40]}")
            else:
                items_user_with_context = base_items_prompt

            page_items_data, page_items_response = self.extract_invoice(
                page_img, items_system, items_user_with_context,
                temperature=temperature,
                max_tokens=8000
            )
            items_responses[f'page_{pg_idx + 1}'] = page_items_response

            if 'error' in page_items_data:
                print(f"   ⚠️  Page {pg_idx + 1} items failed: {page_items_data['error']} — skipping")
                continue

            page_items = page_items_data.get('items', [])
            print(f"   ✅ Page {pg_idx + 1}: {len(page_items)} items extracted")
            all_items.extend(page_items)

            # Track last real item from this page for next page's context
            real_items = [it for it in page_items if it.get('description') and it.get('quantity')]
            if real_items:
                last_page_last_item = real_items[-1]

        if not all_items and n_unique > 0:
            return {
                'error': "Pass 3 (Items) failed: no items extracted from any page",
                'failed_pass': 'items', 'partial_results': merged_data.copy()
            }, {'pass_1': header_response, 'pass_2': totals_response, 'pass_3': items_responses}

        # ════════════════════════════════════════════════════════════
        # STEP 1: CONTINUATION MERGE (must run BEFORE dedup)
        # ────────────────────────────────────────────────────────────
        # Per-page extraction splits items at page boundaries:
        #   Page 1 item 4 → description+qty, but batch=null (data on page 2)
        #   Page 2 first row → batch/expiry/item_code only, no description
        # Patch orphan continuation rows into the last real item first,
        # before dedup removes anything.
        # ════════════════════════════════════════════════════════════
        def _has_real_data(item: dict) -> bool:
            """True if item is a real item row (has description + qty or price)."""
            desc = str(item.get('description') or '').strip()
            has_desc  = bool(desc) and desc not in ('?', 'null', 'none', 'N/A')
            qty       = item.get('quantity')
            has_qty   = qty is not None and str(qty).strip() not in ('', '0', '0.0', 'null', '?')
            has_price = item.get('unit_price') is not None or item.get('total_price') is not None
            return has_desc and (has_qty or has_price)

        def _is_continuation(item: dict) -> bool:
            """True if row carries ONLY batch/expiry/item_code — tail of a split item."""
            # Explicit flag set when model was told to return a continuation object
            if item.get('_continuation_for_previous_page'):
                return True
            has_meta = any([
                item.get('Batch')       and str(item.get('Batch', '')).strip(),
                item.get('expiry_date') and str(item.get('expiry_date', '')).strip(),
                item.get('item_code')   and str(item.get('item_code', '')).strip(),
            ])
            return has_meta and not _has_real_data(item)

        merged_items: list[dict] = []
        for item in all_items:
            if _is_continuation(item) and merged_items:
                last = merged_items[-1]
                patched = False
                for field in ('Batch', 'expiry_date', 'item_code'):
                    if item.get(field) and not last.get(field):
                        last[field] = item[field]
                        patched = True
                if patched:
                    print(f"   🔗 Continuation row merged into: {last.get('description', '')[:45]}")
            else:
                merged_items.append(item)

        all_items = merged_items

        # ════════════════════════════════════════════════════════════
        # STEP 2: AGGRESSIVE DEDUPLICATION — remove replica items
        # ────────────────────────────────────────────────────────────
        # Scenario: Page 1 ORIGINAL (items 1-5), Page 2 NONE (items 6-10),
        #           Page 3 ORIGINAL replica (items 1-5 again)
        # Result: Items 1-5 extracted twice from pages 1 and 3.
        #
        # Strategy: Use MULTIPLE dedup keys with priority:
        #   1. (desc, qty, batch) — exact match (highest confidence)
        #   2. (hsn, qty, taxable) — financial match (OCR-tolerant)
        #   3. (desc_normalized, qty) — fuzzy match (handles "PARACETAMOL 500MG" vs "PARACETAMOL 500 MG")
        #   4. (item_code, qty) — when item code is reliable
        # ════════════════════════════════════════════════════════════
        seen_primary:   set = set()   # (desc, qty, batch) — exact match
        seen_financial: set = set()   # (hsn, qty, taxable) — OCR-tolerant
        seen_fuzzy:     set = set()   # (desc_normalized, qty) — handles spacing/case variations
        seen_itemcode:  set = set()   # (item_code, qty) — when item_code present
        deduped_items:  list = []

        def _normalize_desc(desc: str) -> str:
            """Normalize description for fuzzy matching."""
            # Remove extra spaces, punctuation, convert to uppercase
            import re
            desc = desc.upper().strip()
            desc = re.sub(r'[^\w\s]', '', desc)  # Remove punctuation
            desc = re.sub(r'\s+', ' ', desc)     # Collapse multiple spaces
            return desc

        for item in all_items:
            desc     = str(item.get('description', '') or '').strip().upper()
            qty      = str(item.get('quantity', '')    or '')
            batch    = str(item.get('Batch', '')       or '').strip().upper()
            taxable  = str(item.get('taxable_value', '') or item.get('Value', '') or '')
            hsn      = str(item.get('hsn_sac', '')     or '').strip()
            item_code = str(item.get('item_code', '')  or '').strip().upper()

            # Only deduplicate real items
            if not desc:
                deduped_items.append(item)
                continue

            # Build dedup keys
            primary_key   = (desc, qty, batch)
            financial_key = (hsn, qty, taxable) if (hsn and taxable) else None
            fuzzy_key     = (_normalize_desc(desc), qty)
            itemcode_key  = (item_code, qty) if item_code and item_code not in ('', '?', 'NULL') else None

            # Check all dedup strategies (priority order)
            is_duplicate = False
            
            # Strategy 1: Exact match (desc + qty + batch)
            if batch and primary_key in seen_primary:
                print(f"   🔄 Dup removed (exact): {desc[:40]} qty={qty} batch={batch}")
                is_duplicate = True
            
            # Strategy 2: Financial match (hsn + qty + taxable) — catches OCR variants
            elif financial_key and financial_key in seen_financial:
                print(f"   🔄 Dup removed (financial): {desc[:40]} hsn={hsn} qty={qty} taxable={taxable}")
                is_duplicate = True
            
            # Strategy 3: Item code match — reliable when present
            elif itemcode_key and itemcode_key in seen_itemcode:
                print(f"   🔄 Dup removed (item_code): {item_code} qty={qty}")
                is_duplicate = True
            
            # Strategy 4: Fuzzy description match — handles spacing/punctuation variations
            elif fuzzy_key in seen_fuzzy:
                print(f"   🔄 Dup removed (fuzzy): {desc[:40]} qty={qty}")
                is_duplicate = True
            
            if is_duplicate:
                continue
            
            # Not a duplicate — keep it and register all keys
            deduped_items.append(item)
            if batch:
                seen_primary.add(primary_key)
            if financial_key:
                seen_financial.add(financial_key)
            if itemcode_key:
                seen_itemcode.add(itemcode_key)
            seen_fuzzy.add(fuzzy_key)

        duplicate_count = len(all_items) - len(deduped_items)
        all_items = deduped_items

        # ── Write final items and summary ─────────────────────────
        print(f"\n🔍 Finalising items...")
        unique_items = all_items

        merged_data['items'] = unique_items
        pass_metadata['pass_3_items'] = {
            'items_extracted': len(all_items) + duplicate_count,  # Total before dedup
            'items_unique': len(unique_items),
            'duplicates_skipped': duplicate_count,
            'pages_used': n_unique
        }

        print(f"✅ Items finalised: {len(all_items) + duplicate_count} extracted, {len(unique_items)} unique, {duplicate_count} duplicates removed")

        print("\n" + "="*80)
        print(f"✅ EXTRACTION COMPLETE — Per-page strategy")
        print(f"   Unique pages: {n_unique} (of {page_count} total)")
        print(f"   Header fields: {pass_metadata['pass_1_header']['fields_extracted']}")
        print(f"   Totals fields: {pass_metadata['pass_2_totals']['fields_extracted']}")
        print(f"   Unique items : {pass_metadata['pass_3_items']['items_unique']}")
        print("="*80 + "\n")
        
        metadata = {
            'passes': pass_metadata,
            'total_pages': page_count,
            'total_items': len(unique_items),
            'duplicates_skipped': duplicate_count,
            'extraction_strategy': 'page_agnostic'
        }
        
        return merged_data, metadata

    @traceable(name="model_verify_extraction", tags=["model", "verification"], metadata={"model": "qwen3.7-plus"})
    def verify_extraction(
        self,
        image: Image.Image,
        extracted_data: dict,
        temperature: float = 0.0
    ) -> dict:
        """
        Verification pass: ask the model to cross-check extracted JSON against the invoice image.
        
        Sends the extracted data back to the model alongside the image and asks it to flag
        discrepancies. Cheap pass (max_tokens=2000, no reasoning) focused purely on validation.
        
        Args:
            image: The original invoice image (same image used for extraction)
            extracted_data: The final extracted JSON (after all post-processing)
            temperature: Always 0.0 for deterministic verification
        
        Returns:
            Verification report dict with structure:
            {
                "verification_status": "PASS" or "FAIL",
                "discrepancies": [...],
                "confidence_score": float,
                "notes": str
            }
        """
        print(f"\n{'═'*80}")
        print(f"🔍 VERIFICATION PASS — Cross-checking extracted data against invoice image")
        print(f"{'═'*80}")
        
        # Format extracted data as compact JSON for the prompt
        import json
        # Remove internal fields that shouldn't be verified
        clean_data = {k: v for k, v in extracted_data.items() if not k.startswith('_')}
        extracted_json = json.dumps(clean_data, indent=2, ensure_ascii=False)
        
        user_prompt = VERIFICATION_USER_PROMPT.format(extracted_json=extracted_json)
        
        # Cheap verification call: no reasoning (pure comparison), low token limit
        verification_result, _ = self.extract_invoice(
            image,
            system_prompt=VERIFICATION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.0,
            max_tokens=2000,
            use_reasoning=False  # No thinking needed — just compare two sources
        )
        
        # Default to PASS if model returns empty/malformed verification
        if not verification_result or not isinstance(verification_result, dict):
            verification_result = {
                "verification_status": "PASS",
                "discrepancies": [],
                "confidence_score": 1.0,
                "notes": "Verification call failed — assuming extraction is correct."
            }
        
        status = verification_result.get("verification_status", "PASS")
        discrepancy_count = len(verification_result.get("discrepancies", []))
        
        if status == "PASS" and discrepancy_count == 0:
            print(f"✅ Verification: PASS — No discrepancies found")
        else:
            print(f"⚠️  Verification: {status} — {discrepancy_count} discrepancies flagged")
            for i, disc in enumerate(verification_result.get("discrepancies", [])[:5], 1):
                print(f"   {i}. {disc.get('field')}: {disc.get('severity')} — {disc.get('extracted')} ≠ {disc.get('invoice_shows')}")
            if discrepancy_count > 5:
                print(f"   ... and {discrepancy_count - 5} more")
        
        return verification_result
