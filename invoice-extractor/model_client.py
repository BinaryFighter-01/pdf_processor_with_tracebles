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
        image: Image.Image,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 16000,
        use_reasoning: bool = True    # ON by default — reasoning critical for character-level accuracy
    ) -> tuple[dict, dict]:
        """
        Extract invoice data using vision model.
        
        Returns:
            Tuple of (extracted_data_dict, raw_response_dict)
        """
        # Convert image to base64
        image_b64 = self.image_to_base64(image)
        
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
                        {
                            'type': 'image_url',
                            'image_url': {
                                'url': image_b64
                            }
                        }
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
        # Rule 1: If ANY page is labelled ORIGINAL, use only ORIGINAL pages
        #         (plus NONE-labelled pages that follow an ORIGINAL, which are
        #          continuation sheets of the same copy).
        # Rule 2: If NO page has any recognised label, fall back to pixel dedup.
        has_labels = any(t in ('ORIGINAL', 'DUPLICATE', 'TRIPLICATE', 'OTHER')
                         for t in page_types)

        if has_labels:
            # Keep ORIGINAL pages and NONE pages that are sandwiched between them.
            # A "NONE" page between two ORIGINAL pages is a content continuation.
            # A "NONE" page after a TRIPLICATE is part of the triplicate — skip it.
            original_indices: list[int] = []
            last_kept_type = None
            for idx, ctype in enumerate(page_types):
                if ctype == 'ORIGINAL':
                    original_indices.append(idx)
                    last_kept_type = 'ORIGINAL'
                elif ctype == 'NONE' and last_kept_type == 'ORIGINAL':
                    # Continuation of the original copy
                    original_indices.append(idx)
                else:
                    # DUPLICATE / TRIPLICATE / OTHER / NONE after non-ORIGINAL
                    last_kept_type = ctype

            if not original_indices:
                # No ORIGINAL found — all copies present but none labelled ORIGINAL
                # Just take the first distinct copy (pages up to first non-NONE repeat)
                print("   ⚠️  No ORIGINAL label found — using first copy only")
                original_indices = [i for i, t in enumerate(page_types)
                                    if t not in ('DUPLICATE', 'TRIPLICATE')]
                if not original_indices:
                    original_indices = list(range(len(images)))

            unique_images = [images[i] for i in original_indices]
            print(f"   Label-based selection: pages {[i+1 for i in original_indices]} kept")
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

        # ── Pass 1: Header — page 1 only ─────────────────────────
        print(f"\n📋 Pass 1: Header from page 1 (full resolution {page_1.width}x{page_1.height})...")
        header_system, header_user = get_header_prompt()

        header_data, header_response = self.extract_invoice(
            page_1, header_system, header_user,
            temperature=temperature, max_tokens=4000
        )
        if 'error' in header_data:
            return {
                'error': f"Pass 1 (Header) failed: {header_data['error']}",
                'failed_pass': 'header', 'partial_results': {}
            }, {'pass_1': header_response}

        merged_data.update(header_data)
        pass_metadata['pass_1_header'] = {'fields_extracted': len(header_data)}
        print(f"✅ Pass 1 complete: {len(header_data)} header fields")

        # ── Pass 2: Totals — second unique page (or page 1 if only one) ──────
        # Totals always appear at the END of the first complete copy.
        # For a 2-unique-page invoice: page 2 has the totals summary.
        # Using last_page is WRONG when the last unique page is a triplicate
        # continuation that survived dedup (e.g., different orientation).
        # Use unique_images[1] (second unique page) as the totals page.
        # If only one unique page, reuse page_1.
        totals_page = unique_images[1] if n_unique >= 2 else page_1
        print(f"\n💰 Pass 2: Totals from page 2/{n_unique} ({totals_page.width}x{totals_page.height})...")
        totals_system, totals_user = get_totals_prompt()
        totals_data, totals_response = self.extract_invoice(
            totals_page, totals_system, totals_user,
            temperature=temperature, max_tokens=3000
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
        # STEP 2: DEDUP — remove cross-page repeated rows
        # ────────────────────────────────────────────────────────────
        # Key uses description + qty + batch as primary signal.
        # Falls back to description + qty + taxable_value when batch differs
        # due to OCR variation on duplicate copy pages.
        # ════════════════════════════════════════════════════════════
        seen_primary:   set = set()   # (desc, qty, batch) — exact match
        seen_financial: set = set()   # (hsn, qty, taxable) — OCR-tolerant, description-independent
        deduped_items:  list = []

        for item in all_items:
            desc     = str(item.get('description', '') or '').strip().upper()
            qty      = str(item.get('quantity', '')    or '')
            batch    = str(item.get('Batch', '')       or '').strip().upper()
            taxable  = str(item.get('taxable_value', '') or item.get('Value', '') or '')
            hsn      = str(item.get('hsn_sac', '')     or '').strip()

            # Only deduplicate real items
            if not desc:
                deduped_items.append(item)
                continue

            primary_key   = (desc, qty, batch)
            # Financial key uses HSN+qty+taxable — immune to OCR description variation
            # (SSOK65 vs SSQK65 have same HSN 90183100 + qty 10 + taxable 12425.0)
            financial_key = (hsn, qty, taxable) if (hsn and taxable) else None

            if batch and primary_key in seen_primary:
                print(f"   🔄 Dup removed (exact): {desc[:40]} qty={qty}")
                continue
            if financial_key and financial_key in seen_financial:
                print(f"   🔄 Dup removed (HSN+qty+taxable): hsn={hsn} qty={qty} taxable={taxable}")
                continue

            deduped_items.append(item)
            if batch:
                seen_primary.add(primary_key)
            if financial_key:
                seen_financial.add(financial_key)

        all_items = deduped_items

        # ── Write final items and summary ─────────────────────────
        print(f"\n🔍 Finalising items...")
        unique_items  = all_items
        duplicate_count = 0  # already counted above

        merged_data['items'] = unique_items
        pass_metadata['pass_3_items'] = {
            'items_extracted': len(all_items),
            'items_unique': len(unique_items),
            'duplicates_skipped': duplicate_count,
            'pages_used': n_unique
        }

        print(f"✅ Items finalised: {len(all_items)} extracted, {len(unique_items)} unique, {duplicate_count} duplicates skipped")

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
