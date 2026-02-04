from typing import Dict, Any, List
import datetime
from app.modules.models import ResolvedInvoice


def _get_val(obj, key, default=None):
    """Helper to get value from either Pydantic model or dict."""
    if hasattr(obj, key):
        return getattr(obj, key)
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default


class ViewModelService:
    """Prepares the final dictionary for template rendering."""

    def __init__(self, config, fee_calculator):
        self.config = config
        self.fee_calculator = fee_calculator

    def build_context(
        self, resolved: ResolvedInvoice, financials: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Maps business objects to a template-friendly dictionary."""
        config_dict = resolved.config_dict
        invoice_model = resolved.invoice_model

        preset_id = config_dict["billing_preset"]
        preset_config = self.fee_calculator.get_preset_config(preset_id)

        work_table_conf = _get_val(preset_config, "work_table", {})
        billing_table_conf = _get_val(preset_config, "billing_table", {})
        unit_name = config_dict["params"].get("unit_name") or _get_val(
            work_table_conf, "unit_name", "Quantity"
        )

        table_view = self._prepare_table_view(
            preset_config, invoice_model.line_items, invoice_model.date, unit_name
        )

        # Header Context
        def format_headers(headers, ctx):
            if not headers:
                return {}
            # headers might be a dict or a model? Usually a dict in TableConfig
            return {k: str(v).format(**ctx) for k, v in headers.items()}

        header_ctx = {"currency": resolved.client.currency, "unit_name": unit_name}

        contact_id = config_dict.get("contact_id")
        contact_obj = next(
            (c for c in resolved.client.contacts if c.get("id") == contact_id), None
        ) or (resolved.client.contacts[0] if resolved.client.contacts else {})
        contact_str = (
            f"{contact_obj.get('name', '')} / {contact_obj.get('email', '')}"
            if contact_obj.get("email")
            else contact_obj.get("name", "--")
        )

        return {
            "invoice": {
                "billing_preset": preset_id,
                "display_title": _get_val(preset_config, "display_title", "Invoice"),
                "number": resolved.invoice_number,
                "canonical_number": resolved.canonical_number,
                "date": invoice_model.date,
                "po": config_dict.get("po"),
                "contract_number": config_dict.get("contract_ref")
                or config_dict.get("project_title")
                or config_dict.get("contract_name"),
                "payment_terms": config_dict.get("payment_terms", "Net 30"),
                "service": config_dict.get("service"),
                "sac": config_dict.get("sac"),
                "currency": resolved.client.currency,
                "place_of_supply": self._build_pos_string(resolved),
                "is_post_gst": resolved.is_post_gst,
                "exchange_rate": config_dict.get("params", {}).get("exchange_rate"),
            },
            "sender": resolved.sender,
            "client": {**resolved.client.model_dump(), "contact": contact_str},
            "bank": resolved.bank,
            "items": invoice_model.line_items,
            "table_view": table_view,
            "financials": financials,
            "headers": {
                "work": format_headers(
                    _get_val(work_table_conf, "headers", {}), header_ctx
                ),
                "billing": format_headers(
                    _get_val(billing_table_conf, "headers", {}), header_ctx
                ),
            },
            "internal": {
                "config_dict": config_dict,
                "invoice_model": invoice_model,
                "client_obj": resolved.client,
            },
        }

    def _prepare_table_view(self, preset_config, items, invoice_date, unit_name):
        view = {"columns": [], "rows": []}

        work_conf = _get_val(preset_config, "work_table", {})
        columns = _get_val(work_conf, "columns", ["date", "description", "quantity"])
        view["columns"] = columns

        for item in items:
            row = []
            for col in columns:
                val = "--"
                if col == "date":
                    val = item.date or invoice_date
                elif col == "description":
                    val = item.description
                    if item.owner and "owner" not in columns:
                        val = f"[{item.owner}] {val}"
                elif col == "owner":
                    val = item.owner or "--"
                elif col == "quantity":
                    if unit_name and unit_name.lower() == "percentage":
                        pct = item.meta.get("percentage")
                        if pct:
                            val = f"{pct}%"
                    elif item.quantity:
                        if unit_name and unit_name.lower() in ["hour", "hours"]:
                            val = f"{item.quantity}h"
                        else:
                            val = f"{item.quantity}"
                row.append(val)
            view["rows"].append(row)
        return view

    def _build_pos_string(self, resolved: ResolvedInvoice) -> str:
        client = resolved.client
        sender = resolved.sender

        # Access state_map via business_rules model if available
        if hasattr(self.config, "business_rules"):
            state_map = self.config.business_rules.state_map
        else:
            state_map = getattr(self.config, "state_map", {})

        if client.gst_category == "overseas":
            state_name = state_map.get(client.state_code or "96", "Outside India")
            return f"{state_name} (Export)"
        else:
            target_state = (
                client.state_code
                if client.gst_category == "regular"
                else (client.state_code or sender.state_code)
            )
            state_name = state_map.get(target_state, "Unknown")
            return f"{state_name} ({target_state})"
