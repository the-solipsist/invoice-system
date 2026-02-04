from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Union
from datetime import date

# --- Turnover Models ---

class TurnoverStats(BaseModel):
    gt: float = Field(description="Preceding FY aggregate turnover")
    cur_gt: float = Field(description="Current FY cumulative turnover")

# --- Business Rules Models ---

class TaxRules(BaseModel):
    default_gst_rate: float = 0.18
    cgst_rate: float = 0.09
    sgst_rate: float = 0.09
    igst_rate: float = 0.18
    gst_threshold_date: date = date(2024, 4, 16)
    default_sac_code: str = "998399"
    lut_text_template: str = "Supply meant for export under LUT No. {lut_number} without payment of integrated tax."

class HledgerRules(BaseModel):
    account_width: int = 50
    client_slugs: Dict[str, str] = {}
    bank_aliases: Dict[str, str] = {}

class Gstr1Defaults(BaseModel):
    version: str = "GSTR1_V1.0"
    hash_prefix: str = "V04||"
    default_hsn_desc: str = ""
    default_user_desc: str = ""
    default_uqc: str = "NA"

class InvoiceDefaults(BaseModel):
    payment_terms: str = "Net 30"

class BusinessRulesConfig(BaseModel):
    tax_rules: TaxRules
    state_map: Dict[str, str]
    default_banks: Dict[str, str]
    hledger: HledgerRules
    gstr1: Gstr1Defaults
    invoice_defaults: InvoiceDefaults

# --- Billing Config Models ---

class ComponentDef(BaseModel):
    type: str
    id: str
    amount: Optional[Union[str, float]] = None
    rate: Optional[Union[str, float]] = None
    min_quantity: Optional[Union[str, float]] = None
    max_quantity: Optional[Union[str, float]] = None

class PricingFormula(BaseModel):
    components: List[ComponentDef]

class TableConfig(BaseModel):
    headers: Dict[str, str]
    columns: Optional[List[str]] = None
    unit_name: Optional[str] = None

class PresetRowTemplate(BaseModel):
    label: str
    details: str

class InvoicePreset(BaseModel):
    formula_id: str
    display_title: str = "Invoice"
    work_table: Optional[TableConfig] = None
    billing_table: TableConfig
    row_templates: Dict[str, PresetRowTemplate] = Field(alias="row_templates", default_factory=dict)
    defaults: Dict[str, Any] = {}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InvoicePreset":
        # Handle the nesting of row_templates inside billing_table in the YAML
        if "billing_table" in data and "row_templates" in data["billing_table"]:
            data["row_templates"] = data["billing_table"].pop("row_templates")
        return cls(**data)

class BillingConfig(BaseModel):
    pricing_formulas: Dict[str, PricingFormula]
    invoice_presets: Dict[str, InvoicePreset]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BillingConfig":
        presets = {}
        for k, v in data.get("invoice_presets", {}).items():
            presets[k] = InvoicePreset.from_dict(v)
        return cls(
            pricing_formulas=data.get("pricing_formulas", {}),
            invoice_presets=presets
        )
