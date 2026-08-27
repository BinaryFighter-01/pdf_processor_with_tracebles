"""
PDF to Image Conversion Utilities
"""

import fitz  # PyMuPDF
from PIL import Image
import io
from langsmith import traceable


@traceable(name="pdf_to_images", tags=["pdf", "conversion"])
def pdf_to_images(pdf_path: str, dpi: int = 200) -> list[Image.Image]:
    """
    Convert PDF pages to PIL Images.
    
    Args:
        pdf_path: Path to PDF file
        dpi: Resolution for rendering (default: 200)
    
    Returns:
        List of PIL Image objects, one per page
    """
    doc = fitz.open(pdf_path)
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    images = []
    
    for page_num, page in enumerate(doc):
        try:
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))
            images.append(img)
        except Exception as e:
            print(f"⚠️  Failed to convert page {page_num + 1}: {e}")
            continue
    
    doc.close()
    return images


@traceable(name="get_pdf_page_count", tags=["pdf"])
def get_pdf_page_count(pdf_path: str) -> int:
    """Get the number of pages in a PDF."""
    try:
        doc = fitz.open(pdf_path)
        count = len(doc)
        doc.close()
        return count
    except Exception:
        return 0
