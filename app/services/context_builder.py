import os
import yaml
import logging
import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, Tuple, List

from app.config import InvoiceConfig
from app.modules.models import (
    InvoiceModel,
    ClientModel,
    SenderModel,
    InvoiceItem,
    ResolvedInvoice,
    InvoiceRegistry,
)
from app.modules.fee_calculator import FeeCalculator
from app.services.numbering import NumberingService


class InvoiceContextBuilder:
    """Handles the Data Assembly layer: resolving all YAML inputs into a unified state."""

    def __init__(self, config: InvoiceConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.rules = config.business_rules
        self.billing_config = config.billing
        self.fee_calculator = FeeCalculator(self.billing_config)

    @staticmethod
    def load_yaml(path):
        with open(path, "r") as f:
            return yaml.safe_load(f)

    def load_profiles(self):
        """Load all profile databases."""
        return {
            "clients": self.load_yaml(self.config.profiles_dir / "clients.yaml"),
            "banks": self.load_yaml(self.config.profiles_dir / "banks.yaml"),
            "self": self.load_yaml(self.config.profiles_dir / "self.yaml"),
        }

    def resolve_invoice(
        self,
        invoice_model: InvoiceModel,
        raw_data: dict,
        registry: InvoiceRegistry,
        source_filename: str,
    ) -> ResolvedInvoice:
        """Entry point for the assembly layer."""
        # 1. Config Resolution
        if invoice_model.contract_id:
            contract_path = (
                self.config.contracts_dir / f"{invoice_model.contract_id}.yaml"
            )
            with open(contract_path, "r") as f:
                contract = yaml.safe_load(f)
            config_dict = self.merge_contract(invoice_model, contract)
            self.expand_milestones(
                invoice_model, contract, config_dict["params"], raw_data
            )
        else:
            config_dict = self.build_config_from_invoice(invoice_model)

        # 2. Profiles & Date
        inv_date_obj = datetime.datetime.strptime(invoice_model.date, "%Y-%m-%d").date()
        profiles = self.load_profiles()
        client, sender, bank = self.resolve_entities(
            config_dict, profiles, inv_date_obj
        )

        # 3. Numbering
        numbering = NumberingService(self.config)
        if not config_dict.get("work_seq"):
            config_dict["work_seq"] = numbering.get_next_work_sequence(
                client.prefix,
                profiles["clients"],
                current_filename=source_filename,
                current_date=invoice_model.date,
            )

        is_series = config_dict.get("contract_series", True)
        if invoice_model.invoice_sequence_number == "00":
            is_series = False
        is_oneoff = not is_series

        invoice_number = numbering.get_next_invoice_number(
            client.prefix,
            config_dict["work_seq"],
            inv_date_obj.strftime("%y%m%d"),
            source_filename,
            is_oneoff,
            registry,
            override_number=invoice_model.invoice_number,
        )
        canonical_number = numbering.calculate_canonical_id(
            client.prefix,
            config_dict["work_seq"],
            inv_date_obj,
            source_filename,
            is_oneoff,
            manual_seq=invoice_model.invoice_sequence_number,
        )

        return ResolvedInvoice(
            invoice_model=invoice_model,
            config_dict=config_dict,
            client=client,
            sender=sender,
            bank=bank,
            invoice_number=invoice_number,
            canonical_number=canonical_number,
            inv_date=inv_date_obj,
            is_post_gst=inv_date_obj >= self.rules.tax_rules.gst_threshold_date,
        )

    def merge_contract(self, invoice_model: InvoiceModel, contract: dict) -> dict:
        invoice_data = invoice_model.model_dump(exclude_unset=True)
        merged_params = contract.get("params", {}).copy()
        merged_params.update(contract.get("billing_terms", {}))
        merged_params.update(invoice_data.get("billing_terms", {}))
        merged_params.update(invoice_data.get("params", {}))

        billing_preset = (
            invoice_model.billing_preset
            or contract.get("billing_preset")
            or invoice_model.billing_type
            or contract.get("billing_type")
        )

        # Hardcoded alias removal: 'retainer_excess' is now handled via config/billing.yaml

        client_overrides = contract.get("client", {}).copy()
        client_overrides.update(invoice_data.get("client", {}))
        sender_overrides = contract.get("sender", {}).copy()
        sender_overrides.update(invoice_data.get("sender", {}))
        bank_overrides = contract.get("bank", {}).copy()
        bank_overrides.update(invoice_data.get("bank", {}))
        labels = contract.get("labels", {}).copy()
        labels.update(invoice_data.get("labels", {}))
        merged_params.update(labels)

        if "rate" not in merged_params:
            if "rate_per_unit" in merged_params:
                merged_params["rate"] = merged_params["rate_per_unit"]
            elif "rate_per_hour" in merged_params:
                merged_params["rate"] = merged_params["rate_per_hour"]
        if "included_hours" in merged_params and "threshold" not in merged_params:
            merged_params["threshold"] = merged_params["included_hours"]

        return {
            "client_id": contract["client_id"],
            "bank_id": contract["bank_id"],
            "sender_id": contract["sender_id"],
            "work_seq": invoice_model.work_sequence_number
            or contract.get("work_sequence_number"),
            "billing_preset": billing_preset,
            "params": merged_params,
            "po": invoice_model.po_number or contract.get("po_number"),
            "contract_ref": invoice_model.contract_ref or contract.get("contract_ref"),
            "service": invoice_model.service or contract.get("service"),
            "sac": invoice_model.sac_code
            or contract.get("sac_code")
            or self.rules.tax_rules.default_sac_code,
            "payment_terms": invoice_model.payment_terms
            or contract.get("payment_terms")
            or self.rules.invoice_defaults.payment_terms,
            "contact_id": invoice_model.contact_id or contract.get("contact_id"),
            "labels": labels,
            "client_overrides": client_overrides,
            "sender_overrides": sender_overrides,
            "bank_overrides": bank_overrides,
            "contract_series": contract.get("contract_series", True),
        }

    def build_config_from_invoice(self, invoice_model: InvoiceModel) -> dict:
        if not invoice_model.client_id:
            raise ValueError("client_id required")
        if not invoice_model.sender_id:
            raise ValueError("sender_id required")
        if not invoice_model.bank_id:
            raise ValueError("bank_id required")

        btype = invoice_model.billing_type
        bpreset = invoice_model.billing_preset
        if not bpreset and btype:
            bpreset = btype

        params = invoice_model.params.copy()
        params.update(invoice_model.billing_terms)

        return {
            "client_id": invoice_model.client_id,
            "bank_id": invoice_model.bank_id,
            "sender_id": invoice_model.sender_id,
            "work_seq": invoice_model.work_sequence_number,
            "billing_type": btype,
            "billing_preset": bpreset,
            "params": params,
            "po": invoice_model.po_number,
            "contract_ref": invoice_model.contract_ref,
            "service": invoice_model.service,
            "sac": invoice_model.sac_code or self.rules.tax_rules.default_sac_code,
            "payment_terms": invoice_model.payment_terms
            or self.rules.invoice_defaults.payment_terms,
            "contact_id": invoice_model.contact_id,
            "labels": invoice_model.labels,
            "client_overrides": invoice_model.client
            if isinstance(invoice_model.client, dict)
            else invoice_model.client.model_dump(exclude_unset=True),
            "sender_overrides": invoice_model.sender
            if isinstance(invoice_model.sender, dict)
            else invoice_model.sender.model_dump(exclude_unset=True),
            "bank_overrides": invoice_model.bank,
            "contract_series": invoice_model.contract_series
            if invoice_model.contract_series is not None
            else True,
        }

    def expand_milestones(
        self, invoice_model: InvoiceModel, contract: dict, params: dict, raw_data: dict
    ):
        milestone_refs = invoice_model.milestones_refs
        if not milestone_refs or "milestones" not in contract:
            return

        total_value = Decimal(str(params.get("total_contract_value", 0)))
        currency = params.get("currency", "INR")
        overrides = raw_data.get("line_items", [])
        invoice_model.line_items = []

        for idx, ref in enumerate(milestone_refs):
            milestone_def = contract["milestones"].get(ref)
            if not milestone_def:
                continue

            percentage = Decimal(str(milestone_def.get("percentage", 0)))
            amount = (
                Decimal(str(milestone_def["amount"]))
                if "amount" in milestone_def
                else (total_value * (percentage / 100)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            )

            description = milestone_def.get("description", f"Milestone: {ref}")
            override_date = None
            if idx < len(overrides):
                override = overrides[idx]
                override_date = override.get("date_completed") or override.get("date")

            invoice_model.line_items.append(
                InvoiceItem(
                    description=description,
                    date=override_date,
                    amount=amount,
                    quantity=Decimal("1.00"),
                    meta={
                        "number": milestone_def.get("number", "--"),
                        "percentage": milestone_def.get("percentage", 0),
                        "currency": currency,
                        "total_value": str(total_value),
                    },
                )
            )

    def resolve_entities(
        self, config_dict: dict, profiles: dict, invoice_date: datetime.date
    ) -> Tuple[ClientModel, SenderModel, dict]:
        client_data = profiles["clients"][config_dict["client_id"]].copy()
        client_data.update(config_dict["client_overrides"])
        client_data["id"] = config_dict["client_id"]
        client = ClientModel(**client_data)

        bank_id = config_dict.get("bank_id") or self.rules.default_banks.get(
            client.gst_category, self.rules.default_banks.get("default")
        )
        bank = profiles["banks"][bank_id].copy()
        bank.update(config_dict["bank_overrides"])

        sender_id = (
            "consultant"
            if invoice_date >= self.rules.tax_rules.gst_threshold_date
            else config_dict["sender_id"]
        )
        sender_profile = profiles["self"]["profiles"][sender_id].copy()

        # Resolve LUT
        lut_data = profiles["self"].get("lut_order_number", {})
        lut_number = lut_data.get("current")

        # Check history if invoice is in previous FY
        year = invoice_date.year
        if invoice_date.month >= 4:
            start_year, end_year = year, year + 1
        else:
            start_year, end_year = year - 1, year

        fy_key = f"fy{str(start_year)[-2:]}-{str(end_year)[-2:]}"

        if "history" in lut_data and fy_key in lut_data["history"]:
            lut_number = lut_data["history"][fy_key]

        sender_data = sender_profile.copy()
        sender_data.update(config_dict["sender_overrides"])
        # Only add LUT for overseas/export clients
        if lut_number and client.gst_category == "overseas":
            sender_data["lut_number"] = lut_number

        sender = SenderModel(**sender_data)

        for key in ["logo_path", "signature_path"]:
            val = getattr(sender, key)
            if val:
                asset_filename = os.path.basename(val)
                setattr(sender, key, str(self.config.assets_dir / asset_filename))

        return client, sender, bank
