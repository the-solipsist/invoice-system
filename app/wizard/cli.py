import sys
import os
import yaml
from datetime import date
from typing import List, Dict, Any
import questionary
from questionary import Choice

# Custom Style for Legibility
style = questionary.Style(
    [
        ("qmark", "fg:#5f819d bold"),
        ("question", "bold"),
        ("answer", "fg:#ff9d00 bold"),
        ("pointer", "fg:#ff9d00 bold"),
        ("highlighted", "fg:#ffffff bg:#5f819d"),
        ("selected", "fg:#ff9d00"),
        ("separator", "fg:#6C6C6C"),
        ("instruction", "fg:#6C6C6C italic"),
        ("text", ""),
        ("disabled", "fg:#858585 italic"),
    ]
)

# Add root
sys.path.append(os.getcwd())

from app.wizard.state import WizardState
from app.invoice_controller import generate


def validate_float(val):
    try:
        float(val)
        return True
    except ValueError:
        return "Please enter a valid number"


class CLIWizard:
    def __init__(self):
        self.state = WizardState()
        self.data = {}

    def run(self):
        print("\n🧙‍♂️  ANNEKAANTA INVOICE WIZARD\n")
        print("(Ctrl+C or Ctrl+D to quit)\n")

        mode = questionary.select(
            "Billing Mode:",
            choices=["Existing Contract", "Standalone / One-Off"],
            style=style,
        ).ask()

        if mode == "Existing Contract":
            self.run_contract_mode()
        else:
            self.run_standalone_mode()

        # Logistics
        self.data["date"] = questionary.text(
            "Invoice Date (YYYY-MM-DD):", default=str(date.today()), style=style
        ).ask()

        # Bank Logic
        # Resolve Client for smart default
        client_id = self.data.get("client_id")
        if not client_id and "contract_id" in self.data:
            c = next(
                (
                    x
                    for x in self.state.contracts
                    if x.get("id") == self.data["contract_id"]
                ),
                {},
            )
            client_id = c.get("client_id")

        client = self.state.clients.get(client_id, {})
        is_overseas = (
            client.get("gst_category") == "overseas"
            or client.get("place_of_supply") == "96"
        )

        smart_default = "iob_chennai" if is_overseas else "yes_bank_savings"

        # Override contract default if specific logic applies?
        # Contract might have specific bank.
        # Priority: Contract Bank > Smart Default > Config Default
        contract_bank = self.data.get("bank_id")  # Set in run_contract_mode
        default_bank = contract_bank or smart_default

        banks = list(self.state.banks.keys())
        if default_bank not in banks:
            default_bank = banks[0]

        # Move default to top
        if default_bank in banks:
            banks.insert(0, banks.pop(banks.index(default_bank)))

        self.data["bank_id"] = questionary.select(
            "Bank Account:", choices=banks, style=style
        ).ask()

        po = questionary.text("PO Number (Optional):").ask()
        if po:
            self.data["po_number"] = po

        # Advanced Presentation
        if questionary.confirm(
            "Configure advanced presentation (Headers/Labels)?", default=False
        ).ask():
            self.configure_presentation()

        # Review
        print("\n--- YAML PREVIEW ---")
        print(yaml.dump(self.data, sort_keys=False))

        if questionary.confirm("Generate Invoice?", style=style).ask():
            self.generate_output()

    def configure_presentation(self):
        # 1. Row Label
        current_label = self.data.get("billing_terms", {}).get("label")
        new_label = questionary.text(
            "Row Label Template (e.g. 'Fee' or 'Tranche {number}'):",
            default=current_label or "",
        ).ask()
        if new_label:
            if "billing_terms" not in self.data:
                self.data["billing_terms"] = {}
            self.data["billing_terms"]["label"] = new_label

        # 2. Billing Headers
        if questionary.confirm("Override Table Headers?", default=False).ask():
            if "headers" not in self.data:
                self.data["headers"] = {}
            if "billing" not in self.data["headers"]:
                self.data["headers"]["billing"] = {}

            col1 = questionary.text(
                "Billing Column 1 Header:", default="Billing Item"
            ).ask()
            if col1:
                self.data["headers"]["billing"]["col1"] = col1

    def generate_output(self):
        client_id = self.data.get("client_id", "unknown")
        if "contract_id" in self.data:
            c = next(
                (
                    x
                    for x in self.state.contracts
                    if x.get("id") == self.data["contract_id"]
                ),
                {},
            )
            client_id = c.get("client_id", "client")

        slug = f"{self.data['date']}-{client_id}.yaml"
        filename = questionary.text("Filename:", default=slug, style=style).ask()
        out_path = self.state.config.invoices_dir / filename

        with open(out_path, "w") as f:
            yaml.dump(self.data, f, sort_keys=False)

        print(f"Saved to {out_path}")
        try:
            pdf = generate(str(out_path))
            print(f"\n✅ SUCCESS: {pdf}")
        except Exception as e:
            print(f"\n❌ ERROR: {e}")

    def run_contract_mode(self):
        # Searchable List using Autocomplete
        choices = []
        lookup = {}
        for c in self.state.contracts:
            cid = c.get("id", c.get("file_id"))
            client = c.get("client_id", "?").upper()
            title = c.get("project_title", cid)
            label = f"{client} - {title}"
            choices.append(label)
            lookup[label] = cid

        selection = questionary.autocomplete(
            "Select Engagement:",
            choices=choices,
            validate=lambda x: x in choices,
            style=style,
        ).ask()

        if not selection:
            sys.exit(0)
        contract_id = lookup[selection]

        self.data["contract_id"] = contract_id

        # Load Defaults
        defaults = self.state.get_contract_defaults(contract_id)
        contract = defaults["contract"]
        preset = defaults["preset"]

        # Load History
        last_inv = self.state.get_last_invoice(contract_id)
        if last_inv:
            self.data["bank_id"] = last_inv.get("bank_id") or contract.get("bank_id")
            # Extract descriptions for suggestions
            suggestions = [
                i.get("description")
                for i in last_inv.get("line_items", [])
                if i.get("description")
            ]
        else:
            self.data["bank_id"] = contract.get("bank_id")
            suggestions = []

        # PO Logic
        default_po = (
            last_inv.get("po_number") if last_inv else contract.get("po_number")
        )
        if default_po:
            if questionary.confirm(
                f"Use PO Number: {default_po}?", default=True, style=style
            ).ask():
                self.data["po_number"] = default_po
            else:
                self.data["po_number"] = questionary.text(
                    "Enter PO Number:", style=style
                ).ask()

        print(f"Mode: {preset.upper()}")

        if preset == "retainer":
            # Just ask for items.
            # Usually user enters: "Assigned By", "Desc", "Hours".
            print("Enter Work Logs (Excess will be calculated automatically)")
            self.add_line_items(preset, suggestions)

        elif preset == "milestone":
            milestones = contract.get("milestones", {})
            if not milestones:
                print("No milestones defined.")
                self.add_line_items(preset, suggestions)
            else:
                opts = []
                for k, v in milestones.items():
                    opts.append(
                        Choice(
                            title=f"{v.get('description')} ({v.get('amount')})", value=k
                        )
                    )

                selected_ms = questionary.checkbox(
                    "Select Milestones to Bill:", choices=opts, style=style
                ).ask()

                if selected_ms:
                    self.data["milestones_refs"] = selected_ms
                    # Ask dates for each
                    dates_list = []
                    for ms in selected_ms:
                        d = questionary.text(
                            f"Date for {ms} (YYYY-MM-DD):",
                            default=str(date.today()),
                            style=style,
                        ).ask()
                        dates_list.append({"date_completed": d})
                    self.data["line_items"] = dates_list

        else:
            # Hourly / Generic
            self.add_line_items(preset, suggestions)

    def run_standalone_mode(self):
        clients = [k for k in self.state.clients.keys() if not k.startswith(".")]
        clients.sort()

        self.data["client_id"] = questionary.select(
            "Select Client:", choices=clients, style=style
        ).ask()

        preset = questionary.select(
            "Preset:", choices=["flat_fee", "rate", "milestone"], style=style
        ).ask()
        self.data["billing_preset"] = preset
        self.data["billing_terms"] = {}

        # Terms based on Preset
        print("\n-- Billing Terms --")

        # Currency is always needed
        currencies = self.state.scan_values("currency", ["INR"])
        self.data["billing_terms"]["currency"] = questionary.select(
            "Currency:", choices=currencies, style=style
        ).ask()

        if preset == "rate":
            units = self.state.scan_values("unit", ["hour"])
            self.data["billing_terms"]["unit"] = questionary.select(
                "Unit Name:", choices=units, style=style
            ).ask()

            self.data["billing_terms"]["rate"] = float(
                questionary.text(
                    "Unit Rate:", default="0", style=style, validate=validate_float
                ).ask()
            )

        self.data["line_items"] = []
        self.add_line_items(preset, [])

    def add_line_items(self, preset_id, suggestions=[]):
        # Resolve Schema
        preset_config = self.state.presets.get(preset_id, {})
        # Fallback columns if missing
        columns = list(
            preset_config.get("work_table", {}).get(
                "columns", ["date", "description", "quantity"]
            )
        )
        headers = preset_config.get("work_table", {}).get("headers", {})

        # Logic Fix: Ensure essential fields are asked even if not in columns
        if preset_id in ["flat_fee", "milestone"] and "amount" not in columns:
            columns.append("amount")
        if (
            preset_id in ["rate", "retainer"]
            and "quantity" not in columns
            and "hours" not in columns
        ):
            columns.append("quantity")

        print(f"\n-- Add Line Items --")

        while True:
            item = {}
            skip_entry = False

            # Iterate configured columns
            for idx, col_key in enumerate(columns):
                if col_key == "status":
                    continue

                # Get User-Friendly Prompt
                header_key = f"col{idx + 1}"
                prompt_text = headers.get(header_key, col_key.title())

                # Defaults
                default_val = ""
                if col_key == "date":
                    default_val = str(date.today())
                if col_key in ["quantity", "hours"]:
                    default_val = "1.0"

                val = ""
                if col_key == "description" and suggestions:
                    # Use autocomplete for description
                    val = questionary.autocomplete(
                        f"{prompt_text}:",
                        choices=suggestions,
                        default=default_val,
                        validate=lambda x: True,
                    ).ask()
                else:
                    # Add validation for numbers
                    validator = None
                    if col_key in ["hours", "qty", "quantity", "amount"]:
                        validator = validate_float

                    val = questionary.text(
                        f"{prompt_text}:",
                        default=default_val,
                        style=style,
                        validate=validator,
                    ).ask()

                # Map back to InvoiceItem schema
                if col_key in ["hours", "qty", "quantity"]:
                    try:
                        item["quantity"] = float(val)
                    except (ValueError, TypeError):
                        item["quantity"] = 0.0
                elif col_key == "owner":
                    item["owner"] = val
                elif col_key == "date":
                    item["date"] = val
                elif col_key == "description":
                    item["description"] = val
                    if not val:
                        skip_entry = True
                else:
                    item[col_key] = val

            if skip_entry:
                if not questionary.confirm(
                    "Entry empty. Stop adding?", default=True, style=style
                ).ask():
                    continue
                else:
                    break

            self.data["line_items"].append(item)

            if not questionary.confirm(
                "Add another item?", default=True, style=style
            ).ask():
                break


if __name__ == "__main__":
    try:
        CLIWizard().run()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
