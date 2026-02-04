import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, List

from app.config import InvoiceConfig
from app.modules.models import ResolvedInvoice, InvoiceItem

class FinancialsService:
    """Handles business logic for taxes, subtotals, and currency."""
    
    def __init__(self, config: InvoiceConfig, fee_calculator):
        self.config = config
        self.fee_calculator = fee_calculator
        self.tax_rules = config.business_rules.tax_rules

    def calculate(self, resolved: ResolvedInvoice) -> Dict[str, Any]:
        """Calculates financials for a fully resolved invoice."""
        preset_id = resolved.config_dict['billing_preset']
        params = resolved.config_dict['params']
        items = resolved.invoice_model.line_items
        client = resolved.client
        sender = resolved.sender
        inv_date = resolved.inv_date

        return self.perform_calculation(preset_id, params, items, client, sender, inv_date)

    def perform_calculation(self, preset_id, params, items, client, sender, inv_date) -> Dict[str, Any]:
        """The core math engine."""
        financials = {
            "billing_lines": [],
            "subtotal": Decimal('0.00'),
            "tax_lines": [],
            "tax_total": Decimal('0.00'),
            "final_total": Decimal('0.00'),
            "show_subtotal": False,
            "lut_text": None
        }
        
        result = self.fee_calculator.calculate(preset_id, items, params, inv_date)
        financials['billing_lines'] = result['lines']
        subtotal = result['subtotal']
        
        financials['subtotal'] = subtotal
        financials['show_subtotal'] = len(financials['billing_lines']) > 1
        
        # GST Logic
        if inv_date >= self.tax_rules.gst_threshold_date:
            if client.gst_category == 'overseas':
                financials['lut_text'] = self._get_lut_text(inv_date, sender.lut_number)
            elif client.state_code == sender.state_code:
                rate = Decimal(str(self.tax_rules.cgst_rate))
                tax = (subtotal * rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                pct = int(self.tax_rules.cgst_rate * 100)
                suffix = " on sub-total" if financials['show_subtotal'] else ""
                financials['tax_lines'] = [
                    {'label': 'CGST', 'rate_desc': f"@ {pct}%{suffix}", 'amount': tax},
                    {'label': 'SGST', 'rate_desc': f"@ {pct}%{suffix}", 'amount': tax}
                ]
                financials['tax_total'] = tax * 2
            else:
                rate = Decimal(str(self.tax_rules.igst_rate))
                tax = (subtotal * rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                pct = int(self.tax_rules.igst_rate * 100)
                suffix = " on sub-total" if financials['show_subtotal'] else ""
                financials['tax_lines'] = [{'label': 'IGST', 'rate_desc': f"@ {pct}%{suffix}", 'amount': tax}]
                financials['tax_total'] = tax

        financials['final_total'] = subtotal + financials['tax_total']
        return financials

    def _get_lut_text(self, inv_date: datetime.date, lut_number: str = None) -> str:
        if not lut_number:
            return None
        return self.tax_rules.lut_text_template.format(lut_number=lut_number)