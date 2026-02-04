#!/usr/bin/env -S uv run --script

import sys
import os
import argparse
import glob
import json
import datetime
import questionary
import yaml
from app.invoice_controller import generate, assemble_invoice_data, config
from app.modules.models import InvoiceRegistry
from app.services.hledger_service import HledgerService
from app.modules.fee_calculator import FeeCalculator

# Configuration Paths
# Uses app.config imported from invoice_controller

def load_registry():
    return InvoiceRegistry.load(config.registry_path)

def handle_hledger(filename, gen_result):
    # Setup service
    billing_config = yaml.safe_load(open(config.billing_config_path))
    hledger_service = HledgerService(config, FeeCalculator(billing_config))
    
    # Prompt for work finished dates
    item_dates = []
    items = gen_result['invoice_model'].line_items
    for item in items:
        dt = questionary.text(
            f"When was work finished for '{item.description}'?",
            default=gen_result['invoice_model'].date
        ).ask()
        item_dates.append(dt)
    
    hledger_service.print_work_and_invoice(gen_result, item_dates)

def handle_receipt_mode():
    registry = load_registry()
    unpaid = [fname for fname, entry in registry.entries.items() if not entry.payment_received]
    
    if not unpaid:
        print("No unpaid invoices found in registry.")
        return

    selected_file = questionary.select(
        "Select invoice for which payment was received:",
        choices=sorted(unpaid, reverse=True)
    ).ask()

    if not selected_file: return

    path = config.invoices_dir / selected_file
    gen_result = generate(str(path), force=True)
    
    receipt_date = questionary.text("Receipt Date (YYYY-MM-DD):", default=datetime.date.today().strftime("%Y-%m-%d")).ask()
    bank = questionary.select("Bank:", choices=["YES", "IOB-IN", "SBI"]).ask()
    
    currency = gen_result['client'].currency
    tds = 0
    ex_rate = 1.0
    
    if currency == "INR":
        tds_def = float(gen_result['financials']['subtotal']) * 0.1
        tds = questionary.text("TDS Amount:", default=f"{tds_def:.2f}").ask()
    else:
        ex_rate = questionary.text("Exchange Rate:", default=str(gen_result['config_dict']['params'].get('exchange_rate', ""))).ask()

    # Setup service
    billing_config = yaml.safe_load(open(config.billing_config_path))
    hledger_service = HledgerService(config, FeeCalculator(billing_config))
    
    hledger_service.print_receipt(gen_result, receipt_date, bank, tds_amount=tds, exchange_rate=ex_rate)
    
    if questionary.confirm("Mark as paid in registry?").ask():
        registry.mark_as_paid(selected_file, receipt_date)
        registry.save(config.registry_path)
        print(f"Updated registry: {selected_file} marked as paid on {receipt_date}")

def process_file(path, args):
    """Unified handler for a single invoice file."""
    filename = os.path.basename(path)
    if args.hledger:
        result = assemble_invoice_data(str(path))
        if result:
            handle_hledger(filename, result)
        return True
    else:
        result = generate(str(path), force=args.force)
        if result:
            if 'pdf_path' in result:
                print(f"Generated PDF: {result['pdf_path']}")
            return True
    return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate PDF invoices from YAML files.")
    parser.add_argument("filenames", nargs="*", help="Specific invoice YAML files to generate")
    parser.add_argument("--force", action="store_true", help="Force regeneration of all invoices")
    parser.add_argument("--hledger", action="store_true", help="Generate hledger Work/Invoice entries (skips PDF generation)")
    parser.add_argument("--receipt", action="store_true", help="Handle payment received workflow")
    
    args = parser.parse_args()
    
    if args.receipt:
        handle_receipt_mode()
        sys.exit(0)

    if args.filenames:
        for arg in args.filenames:
            process_file(arg, args)
    else:
        # Smart detection mode
        print("No filenames provided. Scanning for new invoices...")
        registry = load_registry()
        invoice_files = glob.glob(str(config.invoices_dir / "*.yaml"))
        invoice_files.sort()
        
        count = 0
        skipped = 0
        
        for path in invoice_files:
            filename = os.path.basename(path)
            if args.hledger or args.force or filename not in registry.entries:
                if process_file(path, args):
                    count += 1
            else:
                skipped += 1
        
        print(f"\nSummary: Processed {count} invoices. Skipped {skipped} existing invoices.")