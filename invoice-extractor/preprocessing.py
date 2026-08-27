"""
Image Preprocessing Module
Handles rotation detection, deskewing, and enhancement for invoice images
"""

import numpy as np
import cv2
from PIL import Image
import warnings
warnings.filterwarnings('ignore')
from langsmith import traceable


class OrientationDetector:
    """
    Detects document rotation (0, 90, 180, 270 degrees).
    Uses ink-ratio method as primary signal and projection profile as secondary.
    """
    
    def __init__(self):
        self.ocr_ready = False
        self.ocr_client = None
        self._init_ocr()
    
    def _init_ocr(self):
        try:
            from ocr_client import QianfanOCRClient
            self.ocr_client = QianfanOCRClient()
            self.ocr_ready = True
            print('[OK] Qianfan OCR (Baidu) loaded for orientation detection.')
        except Exception as e:
            print(f'[WARNING] Qianfan OCR unavailable ({e}). Using heuristic only.')
    
    @staticmethod
    def _rotate_exact(img_np: np.ndarray, angle: int) -> np.ndarray:
        """Rotate image by exact angle (0, 90, 180, 270)."""
        if angle == 0:
            return img_np
        if angle == 90:
            return cv2.rotate(img_np, cv2.ROTATE_90_CLOCKWISE)
        if angle == 180:
            return cv2.rotate(img_np, cv2.ROTATE_180)
        if angle == 270:
            return cv2.rotate(img_np, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return img_np
    
    def _heuristic_scores(self, binary: np.ndarray) -> dict:
        """Return {angle: projection_variance} for all 4 orientations."""
        scores = {}
        for angle in [0, 90, 180, 270]:
            rotated = self._rotate_exact(binary, angle)
            proj = np.sum(rotated, axis=1).astype(float)
            scores[angle] = float(np.var(proj))
        return scores
    
    def _ink_ratio_scores(self, binary: np.ndarray) -> dict:
        """
        Calculate top/bottom ink ratio for all 4 orientations.
        A correctly-oriented invoice has more ink at top (letterhead/logo).
        """
        ink_ratios = {}
        for angle in [0, 90, 180, 270]:
            rotated = self._rotate_exact(binary, angle)
            h = rotated.shape[0]
            top_ink = float(np.mean(rotated[: h // 4, :]))
            bot_ink = float(np.mean(rotated[3 * h // 4 :, :]))
            ink_ratios[angle] = top_ink / max(bot_ink, 1e-9)
        return ink_ratios
    
    @traceable(name="detect_and_correct_orientation", tags=["preprocessing", "orientation"])
    def detect_and_correct(self, pil_img: Image.Image) -> tuple[Image.Image, int, dict]:
        """
        Detect rotation and return corrected image.
        Uses OCR-based detection for maximum accuracy.
        
        Returns:
            Tuple of (corrected_image, rotation_angle, debug_info)
        """
        rotation_angle = 0
        method = 'none'
        confidence = 0.0
        
        # Use OCR if available for most accurate detection
        if self.ocr_ready and self.ocr_client:
            try:
                rotation_angle, confidence = self.ocr_client.detect_orientation(pil_img)
                method = 'qianfan_ocr'
                
                # If OCR confidence is too low (0%), fall back to heuristic
                if confidence < 0.1:
                    print(f"[WARNING] OCR confidence too low ({confidence:.0%}), using heuristic fallback")
                    method = 'heuristic_fallback'
            except Exception as e:
                print(f"[WARNING] OCR detection failed: {e}, falling back to heuristic")
                method = 'heuristic_fallback'
        
        # Fallback to heuristic if OCR not available or failed
        if not self.ocr_ready or method == 'heuristic_fallback':
            img_np = np.array(pil_img.convert('RGB'))
            h, w = img_np.shape[:2]
            gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            
            # Simple heuristic: check aspect ratio and ink density
            # Invoices are typically landscape (wider than tall)
            if h > w * 1.3:  # Portrait but should be landscape
                # Check top vs bottom density to distinguish 90° from 270°
                top_density = np.mean(binary[:h//4, :])
                bottom_density = np.mean(binary[3*h//4:, :])
                
                # Header typically has more ink (logo, title)
                if top_density > bottom_density * 1.1:
                    rotation_angle = 270  # Rotate 90° counter-clockwise
                else:
                    rotation_angle = 90   # Rotate 90° clockwise
                confidence = 0.7
            else:
                # Already landscape-ish, check if upside down
                top_density = np.mean(binary[:h//4, :])
                bottom_density = np.mean(binary[3*h//4:, :])
                
                if bottom_density > top_density * 1.5:
                    rotation_angle = 180
                    confidence = 0.6
                else:
                    rotation_angle = 0
                    confidence = 0.8
            
            method = 'aspect_ratio_heuristic'
        
        # Apply rotation
        img_np = np.array(pil_img.convert('RGB'))
        corrected_np = self._rotate_exact(img_np, rotation_angle)
        corrected_pil = Image.fromarray(corrected_np)
        
        debug_info = {
            'rotation_angle': rotation_angle,
            'method': method,
            'confidence': confidence,
            'ocr_available': self.ocr_ready
        }
        
        return corrected_pil, rotation_angle, debug_info


class ImagePreprocessor:
    """
    Comprehensive image preprocessing for invoice OCR.
    Handles deskewing, enhancement, and normalization.
    """
    
    def __init__(self):
        self.orientation_detector = OrientationDetector()
    
    @staticmethod
    def detect_skew(img_np: np.ndarray) -> float:
        """Detect skew angle using Hough transform."""
        gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY) if len(img_np.shape) == 3 else img_np
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        
        lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=100, minLineLength=100, maxLineGap=10)
        
        if lines is None:
            return 0.0
        
        angles = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
            # Normalize to [-45, 45]
            if angle < -45:
                angle += 90
            if angle > 45:
                angle -= 90
            angles.append(angle)
        
        if not angles:
            return 0.0
        
        # Use median to reduce outlier impact
        median_angle = float(np.median(angles))
        return median_angle
    
    @staticmethod
    def deskew(pil_img: Image.Image, angle: float) -> Image.Image:
        """Rotate image to correct skew."""
        if abs(angle) < 0.1:
            return pil_img
        
        # Rotate around center
        img_np = np.array(pil_img)
        h, w = img_np.shape[:2]
        center = (w // 2, h // 2)
        
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(
            img_np, M, (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE
        )
        
        return Image.fromarray(rotated)
    
    @staticmethod
    def enhance_contrast(pil_img: Image.Image) -> Image.Image:
        """Enhance image contrast using adaptive histogram equalization."""
        img_np = np.array(pil_img.convert('RGB'))
        
        # Convert to LAB color space
        lab = cv2.cvtColor(img_np, cv2.COLOR_RGB2LAB)
        l, a, b = cv2.split(lab)
        
        # Apply CLAHE to L channel
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l = clahe.apply(l)
        
        # Merge and convert back
        lab = cv2.merge([l, a, b])
        enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
        
        return Image.fromarray(enhanced)
    
    @staticmethod
    def denoise(pil_img: Image.Image) -> Image.Image:
        """Apply denoising filter."""
        img_np = np.array(pil_img.convert('RGB'))
        denoised = cv2.fastNlMeansDenoisingColored(img_np, None, 10, 10, 7, 21)
        return Image.fromarray(denoised)
    
    @staticmethod
    def sharpen(pil_img: Image.Image) -> Image.Image:
        """Sharpen image for better text clarity."""
        img_np = np.array(pil_img.convert('RGB'))
        
        # Sharpening kernel
        kernel = np.array([[-1, -1, -1],
                          [-1,  9, -1],
                          [-1, -1, -1]])
        
        sharpened = cv2.filter2D(img_np, -1, kernel)
        return Image.fromarray(sharpened)
    
    @traceable(name="preprocess_image", tags=["preprocessing"])
    def process(
        self,
        pil_img: Image.Image,
        do_orient: bool = True,
        do_deskew: bool = True,
        do_enhance: bool = True,
        do_denoise: bool = False,
        do_sharpen: bool = True
    ) -> tuple[Image.Image, dict]:
        """
        Complete preprocessing pipeline.
        
        Returns:
            Tuple of (processed_image, debug_info)
        """
        debug_info = {
            'original_size': pil_img.size,
            'steps_applied': []
        }
        
        processed = pil_img
        
        # Step 1: Orientation correction
        if do_orient:
            processed, rotation_angle, orient_debug = self.orientation_detector.detect_and_correct(processed)
            debug_info['orientation'] = orient_debug
            debug_info['steps_applied'].append(f'Rotation correction: {rotation_angle}°')
        
        # Step 2: Skew correction
        if do_deskew:
            img_np = np.array(processed.convert('RGB'))
            skew_angle = self.detect_skew(img_np)
            if abs(skew_angle) > 0.5:
                processed = self.deskew(processed, skew_angle)
                debug_info['skew_angle'] = skew_angle
                debug_info['steps_applied'].append(f'Deskew: {skew_angle:.2f}°')
        
        # Step 3: Denoising (optional, can blur text)
        if do_denoise:
            processed = self.denoise(processed)
            debug_info['steps_applied'].append('Denoising')
        
        # Step 4: Contrast enhancement
        if do_enhance:
            processed = self.enhance_contrast(processed)
            debug_info['steps_applied'].append('Contrast enhancement')
        
        # Step 5: Sharpening
        if do_sharpen:
            processed = self.sharpen(processed)
            debug_info['steps_applied'].append('Sharpening')
        
        debug_info['final_size'] = processed.size
        
        return processed, debug_info
