from abc import ABC, abstractmethod
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Any, Optional, Union
import datetime

# ==========================================
# HELPERS
# ==========================================


def to_dec(v):
    if v is None:
        return Decimal("0.00")
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v))
    return Decimal(str(v).replace(",", ""))


def format_currency(value):
    try:
        val = to_dec(value)
        return "{:,.2f}".format(val)
    except (ValueError, TypeError, ArithmeticError):
        return str(value)


def format_qty(value):
    try:
        val = to_dec(value)
        # Remove trailing zeros if integer? Or standard 2 decimals?
        # Standardize on 2 decimals for consistency unless int
        if val % 1 == 0:
            return "{:.0f}".format(val)
        return "{:.2f}".format(val)
    except (ValueError, TypeError, ArithmeticError):
        return str(value)


# ==========================================
# COMPONENT PRIMITIVES
# ==========================================


class BillingComponent(ABC):
    def __init__(self, comp_def: Dict[str, Any], row_template: Dict[str, str]):
        self.comp_def = comp_def
        self.id = comp_def.get("id")
        self.row_template = row_template  # {'label': ..., 'details': ...}

    @abstractmethod
    def calculate(
        self, items: List[Any], context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Returns a list of calculated rows:
        [ { "label": str, "details": str, "amount": Decimal }, ... ]
        """
        pass

    def resolve_val(self, key: str, context: Dict[str, Any], default=None) -> Any:
        """Resolves a value from context, handling {placeholders}."""
        val = self.comp_def.get(key)
        if val is None:
            return default

        # If it's a placeholder string like "{base_amount}"
        if isinstance(val, str) and val.startswith("{") and val.endswith("}"):
            var_name = val[1:-1]
            return context.get(var_name, default)

        return val

    def format_text(self, template: str, context: Dict[str, Any]) -> str:
        if not template:
            return ""
        try:
            return template.format(**context)
        except KeyError:
            return template  # Graceful degradation
        except ValueError:
            return template


class FlatRateComponent(BillingComponent):
    def calculate(
        self, items: List[Any], context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        # 1. Determine Amount Source
        amount_val = self.resolve_val("amount", context)

        # Case A: Explicit Amount (from Contract Params)
        if amount_val is not None:
            final_amount = to_dec(amount_val)
            if final_amount == 0:
                return []

            render_ctx = {**context, "amount": format_currency(final_amount)}
            label = self.format_text(self.row_template.get("label", ""), render_ctx)
            details = self.format_text(self.row_template.get("details", ""), render_ctx)

            return [{"label": label, "details": details, "amount": final_amount}]

        # Case B: Sum of Items (Milestones/Reimbursements)
        # Logic: Group by description (or meta identifier) to create multiple rows if distinct items exist
        else:
            rows = []
            # Grouping key strategy: (description, number)
            # If items have different descriptions, we probably want distinct rows.
            # If items are "Misc Expenses", we might want to sum them?
            # Current requirement: Milestones need distinct rows.

            # Simple grouping by description + meta properties
            groups = []  # List of (item, total_amt)

            for item in items:
                amt = getattr(item, "amount", None)
                if not amt:
                    continue

                final_amount = to_dec(amt)

                # Merge item meta into context for interpolation (e.g. {number})
                item_meta = getattr(item, "meta", {})

                render_ctx = {
                    **context,
                    **item_meta,
                    "amount": format_currency(final_amount),
                }
                if item.description:
                    render_ctx["description"] = item.description

                # Resolve label format from context (defaults/params)
                label_fmt = context.get("label")
                if label_fmt:
                    render_ctx["label"] = self.format_text(label_fmt, render_ctx)

                label = self.format_text(self.row_template.get("label", ""), render_ctx)
                details = self.format_text(
                    self.row_template.get("details", ""), render_ctx
                )

                rows.append(
                    {"label": label, "details": details, "amount": final_amount}
                )

            return rows


class UnitRateComponent(BillingComponent):
    def calculate(
        self, items: List[Any], context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        # 1. Resolve Configuration
        rate_val = self.resolve_val("rate", context)
        min_qty = to_dec(self.resolve_val("min_quantity", context, 0))
        # Handle max_quantity logic if needed (infinity default)
        max_q_val = self.resolve_val("max_quantity", context)
        max_qty = to_dec(max_q_val) if max_q_val is not None else Decimal("Infinity")

        # Use unit_name if present (common override), else unit
        unit_display = context.get("unit_name") or context.get("unit", "unit")
        unit_base = unit_display.lower()
        if unit_base.endswith("s"):
            unit_base = unit_base[:-1]  # naive singularize

        rows = []

        # Case A: Fixed Rate (Retainer Excess / Simple Hourly)
        # Logic: Sum all quantities, apply one rate.
        if rate_val is not None:
            rate = to_dec(rate_val)
            total_qty = Decimal("0.00")

            for item in items:
                q = getattr(item, "quantity", 0)
                if q:
                    total_qty += to_dec(q)

            # Apply Bounds
            billable_qty = total_qty
            if max_qty != Decimal("Infinity"):
                billable_qty = min(billable_qty, max_qty)

            billable_qty = max(Decimal("0.00"), billable_qty - min_qty)

            if billable_qty > 0:
                amount = billable_qty * rate

                render_ctx = {
                    **context,
                    "qty": format_qty(billable_qty),
                    "rate": format_currency(rate),
                    "amount": format_currency(amount),
                    "unit": unit_base,
                    "units": unit_base + "s" if billable_qty != 1 else unit_base,
                    "threshold": format_qty(min_qty)
                    if min_qty > 0
                    else format_qty(max_qty),
                }

                label = self.format_text(self.row_template.get("label", ""), render_ctx)
                details = self.format_text(
                    self.row_template.get("details", ""), render_ctx
                )

                rows.append({"label": label, "details": details, "amount": amount})

        # Case B: Dynamic Rates (Items have different rates)
        # Logic: Group items by rate, generate row per group.
        else:
            # Group by rate
            groups = {}  # rate -> total_qty

            for item in items:
                q = getattr(item, "quantity", 0)
                # Check item rate override, then contract default?
                # Actually if rate_val is None, we MUST find rate on item
                r = getattr(item, "rate", None)
                if r is None:
                    continue  # Skip items with no rate? Or error?

                r_dec = to_dec(r)
                if r_dec not in groups:
                    groups[r_dec] = Decimal("0.00")
                groups[r_dec] += to_dec(q)

            for rate, qty in groups.items():
                amount = qty * rate

                render_ctx = {
                    **context,
                    "qty": format_qty(qty),
                    "rate": format_currency(rate),
                    "amount": format_currency(amount),
                    "unit": unit_base,
                    "units": unit_base + "s" if qty != 1 else unit_base,
                }

                label = self.format_text(self.row_template.get("label", ""), render_ctx)
                details = self.format_text(
                    self.row_template.get("details", ""), render_ctx
                )

                rows.append({"label": label, "details": details, "amount": amount})

        return rows


# ==========================================
# FEE CALCULATOR ENGINE
# ==========================================


class FeeCalculator:
    def __init__(self, config: Any):
        """
        config: The BillingConfig Pydantic model (or dict for backward compat).
        """
        if hasattr(config, "pricing_formulas"):
            self.formulas = config.pricing_formulas
            self.presets = config.invoice_presets
        else:
            self.formulas = config.get("pricing_formulas", {})
            self.presets = config.get("invoice_presets", {})

    def calculate(
        self,
        preset_id: str,
        items: List[Any],
        params: Dict[str, Any],
        date_obj: datetime.date,
    ) -> Dict[str, Any]:
        # 1. Resolve Preset & Formula
        preset = self.presets.get(preset_id)
        if not preset:
            raise ValueError(f"Unknown invoice preset: {preset_id}")

        formula_id = getattr(preset, "formula_id", None) or preset.get("formula_id")
        formula = self.formulas.get(formula_id)
        if not formula:
            raise ValueError(f"Unknown pricing formula: {formula_id}")

        # 2. Build Evaluation Context
        # Merge Defaults < Params
        defaults = getattr(preset, "defaults", {}) or preset.get("defaults", {})
        context = {**defaults, **params}

        # Add Date Variables
        context["date"] = date_obj.strftime("%Y-%m-%d")
        context["year"] = str(date_obj.year)
        context["month"] = date_obj.strftime("%B")

        financials = {"lines": [], "subtotal": Decimal("0.00")}

        # 3. Execute Components
        # row_templates might be in billing_table or direct
        if hasattr(preset, "row_templates"):
            row_templates = preset.row_templates
        else:
            billing_table = preset.get("billing_table", {})
            row_templates = billing_table.get("row_templates", {})

        # components logic
        comp_list = getattr(formula, "components", []) or formula.get("components", [])

        for comp_def in comp_list:
            # handle comp_def as model or dict
            c_type = getattr(comp_def, "type", None) or comp_def.get("type")
            c_id = getattr(comp_def, "id", None) or comp_def.get("id")

            # Get the template for this component ID
            template = row_templates.get(c_id, {})
            # convert template to dict if it's a model
            if hasattr(template, "model_dump"):
                template = template.model_dump()

            # same for comp_def
            c_def_dict = (
                comp_def if isinstance(comp_def, dict) else comp_def.model_dump()
            )

            component = None
            if c_type == "flat_rate":
                component = FlatRateComponent(c_def_dict, template)
            elif c_type == "unit_rate":
                component = UnitRateComponent(c_def_dict, template)

            if component:
                rows = component.calculate(items, context)
                for row in rows:
                    financials["lines"].append(row)
                    financials["subtotal"] += row["amount"]

        return financials

    def get_preset_config(self, preset_id: str):
        return self.presets.get(preset_id, {})
