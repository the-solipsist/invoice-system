import os
import sys
import yaml
import json
import logging
import datetime
import hashlib
from decimal import Decimal

from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

from app.config import InvoiceConfig, setup_logging
from app.modules.models import InvoiceModel, InvoiceRegistry
from app.services.context_builder import InvoiceContextBuilder
from app.services.financials_service import FinancialsService
from app.services.view_model_service import ViewModelService

# Load Configuration & Setup Logging
config = InvoiceConfig.load_default()
setup_logging(config)
logger = logging.getLogger(__name__)

def calculate_hash(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()

class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal): return float(o)
        if hasattr(o, 'model_dump'): return o.model_dump()
        return super(DecimalEncoder, self).default(o)

def sanitize_context_for_export(context):
    return json.loads(json.dumps(context, cls=DecimalEncoder))

def assemble_invoice_data(invoice_yaml_path: str):
    """Assembles all data and calculates financials without writing files or updating registry."""
    filename = os.path.basename(invoice_yaml_path)
    registry = InvoiceRegistry.load(config.registry_path)
    
    with open(invoice_yaml_path, 'r') as f:
        raw_data = yaml.safe_load(f)
    invoice_model = InvoiceModel(**raw_data)

    builder = InvoiceContextBuilder(config)
    resolved = builder.resolve_invoice(invoice_model, raw_data, registry, filename)

    financials_service = FinancialsService(config, builder.fee_calculator)
    financials = financials_service.calculate(resolved)
    
    return {
        "invoice_model": invoice_model,
        "config_dict": resolved.config_dict,
        "client": resolved.client,
        "sender": resolved.sender,
        "financials": financials,
        "invoice_number": resolved.invoice_number,
        "canonical_number": resolved.canonical_number
    }

def generate(invoice_yaml_path: str, force: bool = False):
    """Orchestrates the invoice generation pipeline across multiple layers."""
    try:
        filename = os.path.basename(invoice_yaml_path)
        current_hash = calculate_hash(invoice_yaml_path)
        registry = InvoiceRegistry.load(config.registry_path)
        
        if not force and filename in registry.entries and registry.entries[filename].content_hash == current_hash:
            logger.info(f"Skipping {filename} (Up-to-date)")
            return
        
        logger.info(f"Processing: {invoice_yaml_path}")
        with open(invoice_yaml_path, 'r') as f:
            raw_data = yaml.safe_load(f)
        invoice_model = InvoiceModel(**raw_data)

        # 1. Data Assembly Layer
        builder = InvoiceContextBuilder(config)
        resolved = builder.resolve_invoice(invoice_model, raw_data, registry, filename)

        # 2. Business Logic Layer (Financials)
        financials_service = FinancialsService(config, builder.fee_calculator)
        financials = financials_service.calculate(resolved)

        # 3. Presentation Layer (View Model)
        view_model_service = ViewModelService(config, builder.fee_calculator)
        context = view_model_service.build_context(resolved, financials)

        print(f"Invoice Number: {resolved.invoice_number}")
        if resolved.canonical_number != resolved.invoice_number:
             print(f"Canonical File ID: {resolved.canonical_number}")

        # 4. Render
        os.makedirs(config.output_dir, exist_ok=True)
        env = Environment(loader=FileSystemLoader(config.templates_dir))
        from app.modules.fee_calculator import format_currency
        env.filters['currency'] = format_currency
        env.filters['nl2br'] = lambda x: x.replace('\n', '<br>') if x else ''
        
        safe_id = resolved.canonical_number.replace('/', '_')
        out_path = config.output_dir / f"{safe_id}.pdf"
        HTML(string=env.get_template("invoice.html").render(context), base_url=str(config.templates_dir)).write_pdf(out_path)
        
        with open(config.output_dir / f"{safe_id}.yaml", 'w') as f:
            yaml.dump(sanitize_context_for_export(context), f, sort_keys=False)
            
        # 5. Registry Update
        actual_id = resolved.invoice_number if resolved.invoice_number != resolved.canonical_number else None
        registry.update_entry(filename, resolved.canonical_number, current_hash, actual_id)
        registry.save(config.registry_path)
        
        return {
            "pdf_path": str(out_path),
            "invoice_model": invoice_model,
            "config_dict": resolved.config_dict,
            "client": resolved.client,
            "sender": resolved.sender,
            "financials": financials,
            "invoice_number": resolved.invoice_number,
            "canonical_number": resolved.canonical_number
        }

    except Exception as e:
        logger.error(f"Failed to generate {invoice_yaml_path}: {e}", exc_info=True)
        print(f"Failed to generate {invoice_yaml_path}: {e}")
        return None

if __name__ == "__main__":
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]: generate(arg)
