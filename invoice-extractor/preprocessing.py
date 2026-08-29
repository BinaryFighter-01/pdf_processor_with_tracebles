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
        # OCR is disabled - using visual heuristics only
        self.ocr_ready = False
        self.ocr_client = None
    
    def _init_ocr(self):
        # DISABLED: Qianfan OCR removed, using heuristic-only detection
        pass
    
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
        """
        Enhance image contrast using CLAHE on the L channel (LAB space).

        Skips enhancement for already-high-contrast images (digital PDFs).
        Only applies CLAHE when the image stddev indicates a flat histogram
        (scanned/faded invoices). This avoids amplifying JPEG artifacts on
        clean digital PDFs.
        """
        img_np = np.array(pil_img.convert('RGB'))
        gray   = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)

        # If contrast is already good (stddev > 60), skip — don't touch clean PDFs
        if float(np.std(gray)) > 60.0:
            return pil_img

        # Apply CLAHE to L channel only
        lab = cv2.cvtColor(img_np, cv2.COLOR_RGB2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l = clahe.apply(l)
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
    def crop_border(pil_img: Image.Image, threshold: int = 240, min_crop: int = 10) -> Image.Image:
        """
        Crop uniform-colored border regions (scanner margins, shadows).
        
        SAFE VERSION: caps crop at 2% of each dimension to prevent
        accidentally removing invoice content at edges (dark headers,
        batch codes near margins, footer totals).
        """
        img_np = np.array(pil_img.convert('RGB'))
        gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        h, w = gray.shape

        # Max 2% of image dimension — prevents content loss
        max_crop_h = int(h * 0.02)
        max_crop_w = int(w * 0.02)

        # Sample edge pixels to detect dominant border color
        edge_pixels = np.concatenate([
            gray[0, :],    # top row
            gray[-1, :],   # bottom row
            gray[:, 0],    # left column
            gray[:, -1]    # right column
        ])
        edge_median = np.median(edge_pixels)

        # Detect border type: white (>240) or black (<15)
        if edge_median > threshold:
            mask = gray < threshold   # find dark content in white border
        else:
            mask = gray > 15          # find bright content in black border

        rows = np.any(mask, axis=1)
        cols = np.any(mask, axis=0)

        if not rows.any() or not cols.any():
            return pil_img

        y_min, y_max = np.where(rows)[0][[0, -1]]
        x_min, x_max = np.where(cols)[0][[0, -1]]

        # Only crop if detected border is within the safe 2% cap
        crop_top    = min(y_min, max_crop_h)    if y_min >= min_crop else 0
        crop_bottom = max(y_max + 1, h - max_crop_h) if (h - y_max - 1) >= min_crop else h
        crop_left   = min(x_min, max_crop_w)    if x_min >= min_crop else 0
        crop_right  = max(x_max + 1, w - max_crop_w) if (w - x_max - 1) >= min_crop else w

        # Safety: never crop more than 2% from any side
        crop_top    = max(crop_top,    0)
        crop_bottom = min(crop_bottom, h)
        crop_left   = max(crop_left,   0)
        crop_right  = min(crop_right,  w)

        cropped = img_np[crop_top:crop_bottom, crop_left:crop_right]
        return Image.fromarray(cropped)

    @staticmethod
    def binarize(pil_img: Image.Image) -> Image.Image:
        """
        Adaptive thresholding for low-contrast invoices.
        
        Converts the image to black text on white background using local
        threshold adaptation. Useful for faded thermal prints, photocopies,
        or poorly lit scans where text is washed out.
        
        Returns:
            PIL Image (converted back from binary for pipeline compatibility)
        """
        img_np = np.array(pil_img.convert('RGB'))
        gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        
        # Adaptive thresholding: computes local threshold for each 11×11 block
        # GAUSSIAN: weighs nearby pixels more (smoother than MEAN)
        # C=2: subtract constant from mean to bias toward text (higher C = more aggressive)
        binary = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=11,
            C=2
        )
        
        # Convert back to RGB for downstream compatibility
        rgb = cv2.cvtColor(binary, cv2.COLOR_GRAY2RGB)
        return Image.fromarray(rgb)

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
        do_sharpen: bool = True,
        do_crop_border: bool = True,
        do_binarize: bool = False
    ) -> tuple[Image.Image, dict]:
        """
        Complete preprocessing pipeline.
        
        Args:
            pil_img: Input PIL Image
            do_orient: Correct 0/90/180/270° rotation (via OCR or heuristic)
            do_deskew: Correct sub-degree skew via Hough transform (recommended ON)
            do_enhance: CLAHE contrast enhancement on LAB L-channel (recommended ON)
            do_denoise: Apply color-preserving denoising (slow, use only for noisy scans)
            do_sharpen: Apply 3x3 sharpening kernel (recommended ON)
            do_crop_border: Remove scanner margins/shadows (recommended ON)
            do_binarize: Adaptive thresholding for poor-contrast invoices (use if text is washed out)
        
        Returns:
            Tuple of (processed_image, debug_info)
        """
        debug_info = {
            'original_size': pil_img.size,
            'steps_applied': []
        }
        
        processed = pil_img
        
        # Step 0: Remove scanner borders/shadows
        if do_crop_border:
            processed = self.crop_border(processed)
            debug_info['steps_applied'].append('Border cropping')
        
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
        
        # Step 6: Binarization (optional)
        if do_binarize:
            processed = self.binarize(processed)
            debug_info['steps_applied'].append('Binarization')
        
        debug_info['final_size'] = processed.size
        
        return processed, debug_info



@traceable(name="extract_table_region", tags=["preprocessing", "cropping"])
def extract_table_region(pil_img: Image.Image, expand_ratio: float = 1.2) -> Image.Image:
    """
    Extract the item table region from invoice for high-resolution batch code extraction.
    
    Strategy:
    1. Find horizontal lines (table borders)
    2. Crop to table region
    3. Return at FULL resolution for character-level accuracy
    
    Args:
        pil_img: Full invoice image
        expand_ratio: How much to expand detected table region (default 1.2 = 20% padding)
    
    Returns:
        Cropped PIL Image containing just the table region at full resolution
    """
    img_np = np.array(pil_img.convert('RGB'))
    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    
    # Detect horizontal lines (table borders)
    edges = cv2.Canny(gray, 50, 150)
    
    # Detect horizontal lines using morphology
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (w // 20, 1))
    horizontal_lines = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, horizontal_kernel)
    
    # Find contours
    contours, _ = cv2.findContours(horizontal_lines, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        print("⚠️  No table detected - returning full image")
        return pil_img
    
    # Find the largest rectangular region (likely the table)
    max_area = 0
    table_bbox = None
    
    for contour in contours:
        x, y, w_box, h_box = cv2.boundingRect(contour)
        area = w_box * h_box
        
        # Filter: must be at least 30% of image width and 20% of height
        if w_box > w * 0.3 and h_box > h * 0.2 and area > max_area:
            max_area = area
            table_bbox = (x, y, w_box, h_box)
    
    if table_bbox is None:
        print("⚠️  Table region too small - returning full image")
        return pil_img
    
    # Expand bbox for safety
    x, y, w_box, h_box = table_bbox
    center_x = x + w_box // 2
    center_y = y + h_box // 2
    
    new_w = int(w_box * expand_ratio)
    new_h = int(h_box * expand_ratio)
    
    x1 = max(0, center_x - new_w // 2)
    y1 = max(0, center_y - new_h // 2)
    x2 = min(w, center_x + new_w // 2)
    y2 = min(h, center_y + new_h // 2)
    
    # Crop
    cropped_np = img_np[y1:y2, x1:x2]
    cropped_pil = Image.fromarray(cropped_np)
    
    print(f"✂️  Table region extracted: {x1},{y1} → {x2},{y2} ({x2-x1}x{y2-y1})")
    
    return cropped_pil


@traceable(name="crop_item_rows", tags=["preprocessing", "zoom"])
def crop_item_rows(
    pil_img: Image.Image,
    n_items: int,
    zoom_factor: float = 3.0,
    padding_px: int = 12,
    table_top_ratio: float = 0.25,
    table_bottom_ratio: float = 0.92,
) -> list[Image.Image]:
    """
    Crop each item row from an invoice table and return zoomed PIL images.

    Strategy
    --------
    1. Locate the item-table vertical band by slicing away the header/footer
       (configurable via table_top_ratio / table_bottom_ratio).
    2. Find horizontal separators inside that band using ink-density projection:
       rows with very low horizontal ink are row boundaries.
    3. Split the band into N row strips (one per item).
    4. Upscale each strip by zoom_factor (default 3x) using LANCZOS so that
       4-5 px batch-code characters become 12-15 px — unambiguous for the model.

    Parameters
    ----------
    pil_img          : Full-page preprocessed invoice image.
    n_items          : Expected number of item rows (from first extraction pass).
    zoom_factor      : Upscale multiplier applied to each row crop (default 3.0).
    padding_px       : Extra pixels added above/below each row crop (at original scale).
    table_top_ratio  : Fraction of image height where the item table starts.
    table_bottom_ratio: Fraction of image height where the item table ends.

    Returns
    -------
    List of PIL Images, one per item row, in order.
    If detection fails or n_items == 0, returns [pil_img] (full image fallback).
    """
    if n_items == 0:
        return [pil_img]

    img_np = np.array(pil_img.convert('L'))   # grayscale numpy
    full_h, full_w = img_np.shape

    # ── Step 1: restrict to table vertical band ──────────────────────────────
    y_top    = int(full_h * table_top_ratio)
    y_bottom = int(full_h * table_bottom_ratio)
    band     = img_np[y_top:y_bottom, :]
    band_h   = y_bottom - y_top

    # ── Step 2: ink-density horizontal projection ─────────────────────────────
    # Invert: white paper = 255 → 0 ink, black text = 0 → 255 ink
    inv_band = 255 - band
    row_ink  = inv_band.mean(axis=1)   # mean ink per horizontal line (float)

    # Smooth slightly to handle dotted/dashed borders
    kernel_size = max(3, band_h // 80)
    kernel      = np.ones(kernel_size) / kernel_size
    smoothed    = np.convolve(row_ink, kernel, mode='same')

    # ── Step 3: find row boundaries via local minima ──────────────────────────
    # A boundary is a run of low-ink pixels (border line or gap between rows).
    ink_threshold = smoothed.max() * 0.15   # below 15% of max = boundary zone
    is_boundary   = smoothed < ink_threshold

    # Convert runs of boundary pixels → single y coordinate (midpoint of run)
    boundaries = [0]   # always start from top of band
    in_run = False
    run_start = 0
    for y, b in enumerate(is_boundary):
        if b and not in_run:
            in_run, run_start = True, y
        elif not b and in_run:
            boundaries.append((run_start + y) // 2)
            in_run = False
    boundaries.append(band_h)   # always end at bottom of band

    # Remove duplicates / very close boundaries (< 10px apart)
    clean_bounds = [boundaries[0]]
    for b in boundaries[1:]:
        if b - clean_bounds[-1] > 10:
            clean_bounds.append(b)

    # ── Step 4: map N items onto detected boundaries ──────────────────────────
    # If we detected more boundaries than items, we have enough resolution.
    # If fewer, fall back to equal-height slicing.
    n_boundaries = len(clean_bounds) - 1   # number of detected intervals

    if n_boundaries >= n_items:
        # Use detected boundaries directly, merge extras at end if needed
        row_intervals = []
        step = n_boundaries / n_items
        for i in range(n_items):
            b_start = clean_bounds[int(round(i * step))]
            b_end   = clean_bounds[min(int(round((i + 1) * step)), len(clean_bounds) - 1)]
            row_intervals.append((b_start, b_end))
    else:
        # Equal-height fallback
        row_h = band_h // n_items
        row_intervals = [(i * row_h, (i + 1) * row_h) for i in range(n_items)]

    # ── Step 5: crop, pad, zoom each row ─────────────────────────────────────
    img_rgb = np.array(pil_img.convert('RGB'))
    crops   = []

    for (r_top, r_bot) in row_intervals:
        # Convert back to full-image coordinates
        abs_top = max(0,      y_top + r_top - padding_px)
        abs_bot = min(full_h, y_top + r_bot + padding_px)

        row_crop_np = img_rgb[abs_top:abs_bot, :]
        row_pil     = Image.fromarray(row_crop_np)

        # Zoom: upscale to make characters larger
        new_w = int(row_pil.width  * zoom_factor)
        new_h = int(row_pil.height * zoom_factor)
        zoomed = row_pil.resize((new_w, new_h), Image.Resampling.LANCZOS)
        crops.append(zoomed)

    if not crops:
        print("[crop_item_rows] No rows detected — returning full image")
        return [pil_img]

    print(f"[crop_item_rows] {len(crops)} row crops at {zoom_factor}x zoom "
          f"({crops[0].width}x{crops[0].height} each)")
    return crops
