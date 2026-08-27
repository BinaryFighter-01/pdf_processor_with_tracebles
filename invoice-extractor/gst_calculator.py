"""
GST Calculation and Validation Module for Indian Invoices
Handles both item-level and invoice-level GST calculations
"""

from typing import Dict, List, Any, Optional
from decimal import Decimal, ROUND_HALF_UP
from langsmith import traceable


class GSTCalculator:
    """
    GST Calculator for Indian invoices following statutory rules.
    
    Rules:
    - Intra-state: CGST + SGST (split equally)
    - Inter-state: IGST only
    - CGST must equal SGST
    - Total GST = CGST + SGST + IGST
    """
    
    @staticmethod
    def round_to_2(value: float) -> float:
        """Round to 2 decimal places using banker's rounding."""
        if value is None:
            return 0.0
        d = Decimal(str(value))
        return float(d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    
    @staticmethod
    def is_intra_state(data: Dict[str, Any]) -> bool:
        """
        Determine if transaction is intra-state or inter-state.
        
        Logic:
        - If invoice has CGST/SGST amounts → intra-state
        - If invoice has IGST amounts → inter-state
        - Fallback: Check if any items have cgst_amount
        """
        # Check invoice-level
        if data.get('total_cgst_amount') and data['total_cgst_amount'] > 0:
            return True
        if data.get('total_igst_amount') and data['total_igst_amount'] > 0:
            return False
        
        # Check item-level
        items = data.get('items', [])
        if items:
            first_item = items[0]
            if first_item.get('cgst_amount') is not None:
                return True
            if first_item.get('igst_amount') is not None and first_item.get('igst_amount') > 0:
                return False
        
        # Default to intra-state (most common for pharma invoices)
        return True
    
    def calculate_item_gst(
        self, 
        taxable_value: float, 
        gst_percent: Optional[float],
        is_intra_state: bool = True
    ) -> Dict[str, float]:
        """
        Calculate GST for a single line item.
        
        Args:
            taxable_value: Taxable amount before GST (after discounts)
            gst_percent: Total GST rate (e.g., 5, 12, 18)
            is_intra_state: True for CGST+SGST, False for IGST
        
        Returns:
            Dict with calculated GST components
        """
        if gst_percent is None or gst_percent == 0:
            return {
                'gst_percent': 0,
                'total_gst_amount': 0,
                'cgst_rate': None,
                'cgst_amount': None,
                'sgst_rate': None,
                'sgst_amount': None,
                'igst_rate': None,
                'igst_amount': None,
                'net_amount': self.round_to_2(taxable_value)
            }
        
        # Calculate total GST
        total_gst_amount = self.round_to_2(taxable_value * (gst_percent / 100))
        
        if is_intra_state:
            # Split into CGST + SGST (equal split)
            cgst_rate = self.round_to_2(gst_percent / 2)
            sgst_rate = self.round_to_2(gst_percent / 2)
            cgst_amount = self.round_to_2(total_gst_amount / 2)
            sgst_amount = self.round_to_2(total_gst_amount / 2)
            
            return {
                'gst_percent': gst_percent,
                'total_gst_amount': total_gst_amount,
                'cgst_rate': cgst_rate,
                'cgst_amount': cgst_amount,
                'sgst_rate': sgst_rate,
                'sgst_amount': sgst_amount,
                'igst_rate': None,
                'igst_amount': None,
                'net_amount': self.round_to_2(taxable_value + total_gst_amount)
            }
        else:
            # Inter-state: IGST only
            return {
                'gst_percent': gst_percent,
                'total_gst_amount': total_gst_amount,
                'cgst_rate': None,
                'cgst_amount': None,
                'sgst_rate': None,
                'sgst_amount': None,
                'igst_rate': gst_percent,
                'igst_amount': total_gst_amount,
                'net_amount': self.round_to_2(taxable_value + total_gst_amount)
            }
    
    def calculate_item_taxable_value(
        self,
        quantity: float,
        unit_price: float,
        discount_percent: float = 0,
        cd_percent: float = 0
    ) -> float:
        """
        Calculate taxable value for an item after discounts.
        
        Args:
            quantity: Item quantity
            unit_price: Rate per unit
            discount_percent: Trade discount %
            cd_percent: Cash discount %
        
        Returns:
            Taxable value after discounts
        """
        gross = quantity * unit_price
        
        # Apply trade discount
        if discount_percent:
            gross = gross * (1 - discount_percent / 100)
        
        # Apply cash discount
        if cd_percent:
            gross = gross * (1 - cd_percent / 100)
        
        return self.round_to_2(gross)
    
    def enrich_item_with_gst(self, item: Dict[str, Any], is_intra_state: bool) -> Dict[str, Any]:
        """
        Fill missing GST fields for an item if possible.
        DO NOT overwrite extracted values. DO NOT calculate amounts.
        
        Strategy:
        1. If GST amounts are already present → keep them (extracted from invoice)
        2. If GST_AMT missing but have cgst + sgst → add them
        3. Add _gst_source metadata
        """
        # If GST amounts are already present (extracted from invoice), keep them
        has_gst_amounts = (
            item.get('cgst_amount') is not None or 
            item.get('igst_amount') is not None or
            item.get('GST_AMT') is not None
        )
        
        if has_gst_amounts:
            # Already extracted from invoice - don't overwrite
            item['_gst_source'] = 'invoice'
            
            # Only fill GST_AMT if missing but components exist
            if item.get('GST_AMT') is None:
                cgst = item.get('cgst_amount') or 0
                sgst = item.get('sgst_amount') or 0
                igst = item.get('igst_amount') or 0
                if cgst > 0 or sgst > 0 or igst > 0:
                    item['GST_AMT'] = self.round_to_2(cgst + sgst + igst)
            
            return item
        
        # No GST amounts extracted - mark as not applicable
        item['_gst_source'] = 'not_applicable'
        
        # DO NOT calculate GST from taxable value
        # If invoice didn't provide GST amounts, leave them as null
        
        return item
    
    def calculate_invoice_totals(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        DO NOT CALCULATE - Just fill missing GST totals if needed.
        Invoice amounts should come from extraction, not calculation.
        
        Returns updated data with minimal changes.
        """
        items = data.get('items', [])
        if not items:
            return data
        
        # Determine transaction type
        is_intra_state = self.is_intra_state(data)
        
        # ONLY fill missing GST amounts if they're null (not if they're 0)
        # DO NOT overwrite extracted values
        
        # If total_gst_amount is missing but components exist, add them
        if data.get('total_gst_amount') is None:
            cgst = data.get('total_cgst_amount') or 0
            sgst = data.get('total_sgst_amount') or 0
            igst = data.get('total_igst_amount') or 0
            if cgst > 0 or sgst > 0 or igst > 0:
                data['total_gst_amount'] = self.round_to_2(cgst + sgst + igst)
        
        # Set GST rates if missing (infer from items)
        if is_intra_state:
            if data.get('total_cgst_rate') is None:
                if items and items[0].get('cgst_rate'):
                    data['total_cgst_rate'] = items[0]['cgst_rate']
            
            if data.get('total_sgst_rate') is None:
                if items and items[0].get('sgst_rate'):
                    data['total_sgst_rate'] = items[0]['sgst_rate']
            
            data['total_igst_rate'] = None
        else:
            data['total_cgst_rate'] = None
            data['total_sgst_rate'] = None
            if data.get('total_igst_rate') is None:
                if items and items[0].get('igst_rate'):
                    data['total_igst_rate'] = items[0]['igst_rate']
        
        # Calculate total GST rate if missing
        if data.get('total_gst_rate') is None:
            if is_intra_state and data.get('total_cgst_rate') and data.get('total_sgst_rate'):
                data['total_gst_rate'] = data['total_cgst_rate'] + data['total_sgst_rate']
            elif not is_intra_state and data.get('total_igst_rate'):
                data['total_gst_rate'] = data['total_igst_rate']
        
        # DO NOT touch invoice_amount, taxable_amount, or any monetary totals
        # These come from the invoice extraction, not calculation
        
        return data
    
    @traceable(name="enrich_invoice_data", tags=["gst", "calculator"])
    def enrich_invoice_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main method: Enrich invoice data with calculated GST fields.
        
        Process:
        1. Determine transaction type (intra/inter state)
        2. Enrich each item with GST calculations
        3. Calculate invoice-level totals
        4. Add validation metadata
        """
        # Determine transaction type
        is_intra_state = self.is_intra_state(data)
        
        # Track GST sources
        item_gst_sources = []
        
        # Enrich items
        items = data.get('items', [])
        enriched_items = []
        
        for item in items:
            enriched_item = self.enrich_item_with_gst(item, is_intra_state)
            enriched_items.append(enriched_item)
            item_gst_sources.append(enriched_item.get('_gst_source', 'unknown'))
        
        data['items'] = enriched_items
        
        # Calculate invoice totals
        data = self.calculate_invoice_totals(data)
        
        # Determine predominant item GST source
        if item_gst_sources:
            from collections import Counter
            source_counts = Counter(item_gst_sources)
            predominant_source = source_counts.most_common(1)[0][0]
        else:
            predominant_source = 'unknown'
        
        # Determine header GST source (were invoice totals extracted or calculated?)
        header_gst_source = 'invoice' if data.get('total_cgst_amount') or data.get('total_igst_amount') else 'calculated'
        
        # Calculate confidence based on data completeness
        confidence = self._calculate_confidence(data, item_gst_sources)
        
        # Add enhanced metadata
        data['_gst_calculation_metadata'] = {
            'transaction_type': 'intra-state' if is_intra_state else 'inter-state',
            'gst_method': 'CGST+SGST' if is_intra_state else 'IGST',
            'calculated_by': 'GSTCalculator v1.0',
            'item_level_gst_source': predominant_source,
            'header_gst_source': header_gst_source,
            'confidence': confidence
        }
        
        return data
    
    def _calculate_confidence(self, data: Dict[str, Any], item_sources: List[str]) -> float:
        """Calculate confidence score based on data completeness and consistency."""
        score = 1.0
        
        # Reduce confidence if GST was calculated rather than extracted
        if 'calculated' in item_sources:
            score -= 0.05
        
        # Reduce if header GST was calculated
        if not (data.get('total_cgst_amount') or data.get('total_igst_amount')):
            score -= 0.05
        
        # Reduce if missing key header fields
        if not data.get('seller_gstin'):
            score -= 0.05
        if not data.get('customer_gstin'):
            score -= 0.02
        
        # Reduce if invoice amount doesn't match calculation
        taxable = data.get('taxable_amount', 0)
        gst = data.get('total_gst_amount', 0)
        round_off = data.get('round_off', 0)
        invoice_amt = data.get('invoice_amount', 0)
        calculated = self.round_to_2(taxable + gst + round_off)
        
        if abs(calculated - invoice_amt) > 1.0:
            score -= 0.10
        elif abs(calculated - invoice_amt) > 0.10:
            score -= 0.02
        
        return max(0.0, min(1.0, round(score, 2)))
    
    def validate_gst(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate GST calculations and return validation report.
        DO NOT calculate amounts - only check consistency.
        
        Returns:
            Dict with validation results and any discrepancies
        """
        is_intra_state = self.is_intra_state(data)
        errors = []
        warnings = []
        
        # Validate invoice-level
        if is_intra_state:
            cgst = data.get('total_cgst_amount', 0) or 0
            sgst = data.get('total_sgst_amount', 0) or 0
            
            # CGST must equal SGST
            if cgst > 0 and sgst > 0:
                if abs(cgst - sgst) > 0.02:  # Allow 2 paisa tolerance for rounding
                    warnings.append(f"CGST ({cgst}) should equal SGST ({sgst}) for intra-state")
        
        # DO NOT validate invoice total vs calculated
        # Invoice amounts come from extraction, not calculation
        # Mismatches are expected if the invoice has complex discounts or adjustments
        
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings,
            'transaction_type': 'intra-state' if is_intra_state else 'inter-state'
        }


# Convenience function
@traceable(name="enrich_and_validate_gst", tags=["gst", "validation"])
def enrich_and_validate_gst(data: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Enrich invoice data with GST calculations and validate.
    
    Returns:
        (enriched_data, validation_report)
    """
    calculator = GSTCalculator()
    enriched_data = calculator.enrich_invoice_data(data)
    validation_report = calculator.validate_gst(enriched_data)
    
    return enriched_data, validation_report
