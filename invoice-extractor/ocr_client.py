"""
OCR Client using Baidu Qianfan OCR Fast (Free) via OpenRouter
Replaces PaddleOCR for orientation detection
"""

import os
import base64
import requests
from io import BytesIO
from PIL import Image
from typing import Optional
from dotenv import load_dotenv
from langsmith import traceable

load_dotenv()


class QianfanOCRClient:
    """Client for Baidu Qianfan OCR via OpenRouter."""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv('OPENROUTER_API_KEY')
        self.model = 'baidu/qianfan-ocr-fast:free'
        self.base_url = 'https://openrouter.ai/api/v1/chat/completions'
        
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not found in environment variables")
    
    @staticmethod
    def image_to_base64(pil_image: Image.Image, format: str = 'PNG') -> str:
        """Convert PIL Image to base64 string."""
        buffered = BytesIO()
        pil_image.save(buffered, format=format)
        img_bytes = buffered.getvalue()
        img_base64 = base64.b64encode(img_bytes).decode('utf-8')
        return f"data:image/{format.lower()};base64,{img_base64}"
    
    @traceable(name="ocr_detect_orientation", tags=["ocr", "orientation"])
    def detect_orientation(self, image: Image.Image) -> tuple[int, float]:
        """
        Detect image orientation using OCR.
        
        Returns:
            Tuple of (rotation_angle, confidence)
            rotation_angle: 0, 90, 180, or 270 degrees
            confidence: 0.0 to 1.0
        """
        try:
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
                        'role': 'user',
                        'content': [
                            {
                                'type': 'text',
                                'text': (
                                    'Analyze this document image and determine its rotation angle. '
                                    'The document should be readable with text flowing left-to-right horizontally. '
                                    'Reply with ONLY a single number: 0, 90, 180, or 270. '
                                    'Where: 0 = correct orientation, 90 = rotated 90° clockwise, '
                                    '180 = upside down, 270 = rotated 90° counter-clockwise.'
                                )
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
                'temperature': 0.0,
                'max_tokens': 10,
            }
            
            # Make request
            response = requests.post(self.base_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            response_data = response.json()
            
            # Extract orientation
            if 'choices' in response_data and len(response_data['choices']) > 0:
                text_response = response_data['choices'][0]['message']['content'].strip()
                
                # Parse rotation angle - look for the number
                for angle in [0, 90, 180, 270]:
                    if str(angle) in text_response:
                        print(f"🔄 OCR detected rotation: {angle}° (response: {text_response})")
                        return angle, 0.95  # High confidence from OCR model
                
                # Default to 0 if no angle found
                print(f"⚠️  Could not parse rotation from OCR response: {text_response}")
                return 0, 0.5
            
            return 0, 0.0
        
        except Exception as e:
            print(f"⚠️  Qianfan OCR orientation detection failed: {e}")
            return 0, 0.0
    
    @traceable(name="ocr_extract_text", tags=["ocr"])
    def extract_text(self, image: Image.Image) -> tuple[str, float]:
        """
        Extract all text from image using OCR.
        
        Returns:
            Tuple of (extracted_text, confidence)
        """
        try:
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
                        'role': 'user',
                        'content': [
                            {
                                'type': 'text',
                                'text': 'Extract all text from this document. Preserve layout and structure.'
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
                'temperature': 0.0,
                'max_tokens': 4096,
            }
            
            # Make request
            response = requests.post(self.base_url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            response_data = response.json()
            
            # Extract text
            if 'choices' in response_data and len(response_data['choices']) > 0:
                text_response = response_data['choices'][0]['message']['content']
                return text_response, 1.0
            
            return "", 0.0
        
        except Exception as e:
            print(f"⚠️  Qianfan OCR text extraction failed: {e}")
            return "", 0.0
