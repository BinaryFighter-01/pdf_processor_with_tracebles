# Invoice Data Extraction System

Production-ready invoice extraction API powered by AI vision models with comprehensive GST calculations and free item handling.

## 🚀 Features

- **Multi-page PDF Support** - Process invoices with multiple pages
- **OCR Integration** - Automatic text extraction and rotation detection
- **GST Calculations** - Comprehensive GST enrichment and validation
- **Free Item Handling** - Intelligent splitting of free items with proportional calculations
- **Caching System** - Built-in response caching for faster repeated extractions
- **Web Interface** - Modern HTML/CSS/JS frontend for easy testing
- **REST API** - Production-ready API endpoints

## 📋 Prerequisites

- Python 3.8+
- OpenRouter API key (for AI model access)
- Poppler (for PDF processing)

## 🛠️ Installation

1. **Clone or download the repository**

2. **Install Python dependencies:**
```bash
pip install -r requirements.txt
```

3. **Install Poppler (for PDF processing):**
   - **Windows:** Download from https://github.com/oschwartz10612/poppler-windows/releases
   - Add to PATH or place in project directory
   - **Linux:** `sudo apt-get install poppler-utils`
   - **macOS:** `brew install poppler`

4. **Configure environment variables:**
```bash
cp .env.example .env
```

Edit `.env` and add your OpenRouter API key:
```
OPENROUTER_API_KEY=your_api_key_here
```

## 🎯 Quick Start

### Start the Server

**Windows:**
```bash
start.bat
```

**Manual:**
```bash
python app_web.py
```

The server will start at `http://localhost:5000`

### API Usage

**Extract Invoice Data:**
```bash
POST /api/extract
Content-Type: multipart/form-data

file: <invoice.pdf>
use_ocr: true
two_pass: true
multi_page: true
use_cache: true
```

**Response:**
```json
{
  "success": true,
  "data": {
    "invoice_number": "INV-123",
    "invoice_amount": "1775.00",
    "customer_name": "ABC Company",
    "items": [...]
  },
  "metadata": {
    "processing_time": 2.5,
    "page_count": 2
  }
}
```

## 📁 Project Structure

```
invoice-extractor/
├── app_web.py              # Flask web server and API
├── schema.py               # Extraction prompts and schema
├── model_client.py         # AI model client (OpenRouter)
├── ocr_client.py           # OCR integration (Tesseract)
├── preprocessing.py        # Image preprocessing
├── pdf_utils.py            # PDF handling utilities
├── gst_enrichment.py       # GST calculation logic
├── gst_calculator.py       # GST validation
├── free_item_splitter.py   # Free item splitting logic
├── cache_manager.py        # Response caching
├── requirements.txt        # Python dependencies
├── .env.example            # Environment variables template
├── templates/
│   └── index.html          # Web interface
└── Markdowns/              # Documentation and tests
```

## 🔧 Configuration

Edit `.env` file:

```env
# API Configuration
OPENROUTER_API_KEY=your_key_here
OPENROUTER_MODEL=openai/gpt-4o-mini

# Cache Configuration
CACHE_ENABLED=true
CACHE_DIRECTORY=uploads/.cache
CACHE_MAX_AGE_HOURS=24

# PDF Configuration
MAX_PDF_PAGES=20
```

## 📊 Extracted Fields

### Header Fields
- Invoice identifiers (number, date, PO number, etc.)
- Seller information (name, GSTIN, DL number)
- Customer information (name, GSTIN, DL number)

### Financial Totals
- Invoice amount, gross amount, taxable amount
- GST breakdown (CGST, SGST, IGST)
- Discounts, round-off

### Line Items
- Product details (description, batch, expiry, HSN)
- Quantities (including free item handling)
- Prices and taxes per item
- All values with 2 decimal precision

## 🎁 Free Item Handling

The system automatically splits items with free quantities:

**Input:** `quantity: "20+2"` or `quantity: 20, free_quantity: 2`

**Output:** Two separate records:
- Paid item: 20 units with full pricing
- Free item: 2 units with proportional values

All product-identifying fields remain identical. Monetary values are calculated proportionally based on paid quantity.

## 🔒 Production Deployment

### Security Checklist
- [ ] Set strong API keys in production `.env`
- [ ] Configure CORS for specific origins (update `app_web.py`)
- [ ] Set appropriate file size limits
- [ ] Enable HTTPS
- [ ] Implement rate limiting
- [ ] Add authentication if needed

### Performance
- Enable caching to reduce API costs
- Configure appropriate `MAX_PDF_PAGES` limit
- Use two-pass extraction for better accuracy
- Consider using Ngrok or similar for public access

### Monitoring
- Check logs for extraction errors
- Monitor API usage and costs
- Track processing times
- Review cache hit rates

## 📚 API Endpoints

### POST /api/extract
Extract data from invoice PDF or image.

**Parameters:**
- `file` (required): Invoice file (PDF, PNG, JPG, etc.)
- `use_ocr` (optional): Enable OCR for rotation detection (default: false)
- `two_pass` (optional): Use two-pass extraction (default: true)
- `multi_page` (optional): Process all pages (default: true)
- `use_cache` (optional): Enable caching (default: true)

### GET /api/health
Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "api_configured": true
}
```

### GET /api/cache/stats
Get cache statistics.

## 🐛 Troubleshooting

**Issue: PDF conversion fails**
- Ensure Poppler is installed and in PATH
- Check PDF file is not corrupted

**Issue: API key errors**
- Verify `.env` file exists and contains valid API key
- Check OPENROUTER_API_KEY is set correctly

**Issue: Poor extraction accuracy**
- Enable `use_ocr=true` for better text detection
- Use `two_pass=true` for structured extraction
- Check image quality and orientation

## 📝 License

This project is proprietary. All rights reserved.

## 📞 Support

For issues or questions, contact the development team.

---

**Version:** 2.0  
**Last Updated:** January 2025  
**Status:** Production Ready
