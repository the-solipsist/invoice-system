import re
import datetime
import json
import os
from decimal import Decimal
from typing import List, Optional, Union, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator

# Regex Patterns
GSTIN_PATTERN = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"
PAN_PATTERN = r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$"

class InvoiceItem(BaseModel):
    description: Optional[str] = None
    date: Optional[Union[str, datetime.date]] = None
    quantity: Decimal = Field(default=Decimal('1.00')) 
    amount: Optional[Union[str, Decimal]] = None
    rate: Optional[Union[str, Decimal]] = None
    unit: Optional[str] = None # Added unit override support
    owner: Optional[str] = None
    meta: Dict[str, Any] = {}

    @model_validator(mode='before')
    @classmethod
    def map_aliases_to_quantity(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Map various unit keys to 'quantity' and set 'unit'
            if 'hours' in data:
                data['quantity'] = data.pop('hours')
                data['unit'] = 'hour'
            elif 'sessions' in data:
                data['quantity'] = data.pop('sessions')
                data['unit'] = 'session'
            elif 'words' in data:
                data['quantity'] = data.pop('words')
                data['unit'] = 'word'
            elif 'articles' in data:
                data['quantity'] = data.pop('articles')
                data['unit'] = 'article'
        return data

    @field_validator('amount', 'rate', 'quantity', mode='before')
    def parse_currency(cls, v):
        if v is None: return None
        if isinstance(v, float): return Decimal(str(v))
        if isinstance(v, str): return Decimal(v)
        return v

class BaseEntity(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    state_code: Optional[str] = None
    address: Optional[str] = None
    billing_address: Optional[str] = None # Legacy/Fallback
    shipping_address: Optional[str] = None
    currency: str = "INR"

    @field_validator('gstin')
    def validate_gstin(cls, v):
        if v and not re.match(GSTIN_PATTERN, v):
            raise ValueError(f"Invalid GSTIN format: {v}")
        return v

    @field_validator('pan')
    def validate_pan(cls, v):
        if v and not re.match(PAN_PATTERN, v):
            raise ValueError(f"Invalid PAN format: {v}")
        return v
    
    def get_primary_address(self) -> str:
        """Returns address, falling back to legacy billing_address or empty string."""
        return self.address or self.billing_address or ""

class ClientModel(BaseEntity):
    prefix: Optional[str] = None
    gst_category: str = "regular"
    contacts: List[Dict[str, Any]] = []

class SenderModel(BaseEntity):
    legal_name: Optional[str] = None # Replaced proprietor
    logo_path: Optional[str] = None
    signature_path: Optional[str] = None
    contact_email: Optional[str] = None
    lut_number: Optional[str] = None
    lut_expiry: Optional[str] = None

class InvoiceModel(BaseModel):
    # Required
    date: str # YYYY-MM-DD
    
    # Engagement Axis (New Architecture)
    contract_series: Optional[bool] = None # True: 01,02... | False: 00
    billing_preset: Optional[str] = None   # Replaces billing_type
    
    # Optional / Context Dependent
    contract_id: Optional[str] = None
    client_id: Optional[str] = None
    sender_id: Optional[str] = None
    bank_id: Optional[str] = None
    work_sequence_number: Optional[str] = None
    billing_type: Optional[str] = None # For backward compat (input only)
    
    # Updated Schema Keys
    po_number: Optional[str] = None
    contract_ref: Optional[str] = None # Renamed from contract_number
    service: Optional[str] = None      # Renamed from service_description
    sac_code: Optional[str] = None
    payment_terms: Optional[str] = "Net 30"
    contact_id: Optional[str] = None
    
    milestones_refs: Optional[List[str]] = None 
    line_items: List[InvoiceItem] = []
    params: Dict[str, Any] = {}
    billing_terms: Dict[str, Any] = {} # Added
    labels: Dict[str, str] = {}
    
    # Overrides
    client: Union[ClientModel, Dict[str, Any]] = Field(default_factory=dict)
    sender: Union[SenderModel, Dict[str, Any]] = Field(default_factory=dict)
    bank: Dict[str, Any] = {}
    
    invoice_sequence_number: Optional[str] = None
    invoice_number: Optional[str] = None # Explicit override for Face ID (Legacy support)

    @field_validator('date')
    def validate_date(cls, v):
        try:
            datetime.datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Incorrect data format, should be YYYY-MM-DD")
        return v
    
    @model_validator(mode='before')
    @classmethod
    def map_legacy_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Map legacy 'billing_type' to 'billing_preset'
            if 'billing_type' in data and 'billing_preset' not in data:
                # We now have specific presets for all legacy types in config/billing.yaml
                # so we can just copy it over directly.
                data['billing_preset'] = data['billing_type']
                
                # Implicit One-off for single types
                if data['billing_type'] in ['flat_fee_single', 'rate_single', 'reimbursement']:
                    if 'contract_series' not in data:
                        data['contract_series'] = False
            
            # Map legacy 'invoice_sequence_number: 00' to contract_series: False
            if 'contract_series' not in data:
                 if data.get('invoice_sequence_number') == '00':
                     data['contract_series'] = False
                 # Note: explicit 'billing_type' logic (e.g. rate_single forces oneoff) 
                 # is handled in Controller logic or Config loading, not Model validation usually,
                 # but we can infer it if needed. For now, default to None (Controller decides).

            if 'contract_number' in data and 'contract_ref' not in data:
                data['contract_ref'] = data.pop('contract_number')
            if 'service_description' in data and 'service' not in data:
                data['service'] = data.pop('service_description')
        return data

# --- Registry Models ---

class RegistryEntry(BaseModel):
    canonical_id: str
    content_hash: str
    actual_id: Optional[str] = None  # For legacy support
    payment_received: Optional[Union[bool, str]] = None # New: tracks payment status/date
    last_generated: datetime.datetime = Field(default_factory=datetime.datetime.now)

class InvoiceRegistry(BaseModel):
    entries: Dict[str, RegistryEntry] = {}
    
    def get_entry(self, filename: str) -> Optional[RegistryEntry]:
        return self.entries.get(filename)
    
    def update_entry(self, filename: str, canonical_id: str, content_hash: str, actual_id: Optional[str] = None):
        if filename in self.entries:
            entry = self.entries[filename]
            entry.canonical_id = canonical_id
            entry.content_hash = content_hash
            entry.actual_id = actual_id
            entry.last_generated = datetime.datetime.now()
        else:
            self.entries[filename] = RegistryEntry(
                canonical_id=canonical_id,
                content_hash=content_hash,
                actual_id=actual_id
            )
    
    def mark_as_paid(self, filename: str, receipt_date: str):
        if filename in self.entries:
            self.entries[filename].payment_received = receipt_date
        else:
            raise ValueError(f"Invoice {filename} not found in registry.")
    
    def save(self, path: Union[str, os.PathLike]):
        # Ensure path is string
        path_str = str(path)
        # Dump model to dict
        data = self.model_dump(mode='json') 
        
        # Sort entries by date (extracted from canonical_id suffix YYMMDD)
        # Canonical ID format: PREFIX-SEQ-SEQ-YYMMDD
        # If extraction fails, fall back to filename
        def sort_key(item):
            fname, entry = item
            cid = entry.get('canonical_id', '')
            # Extract last 6 chars?
            if cid and '-' in cid:
                parts = cid.split('-')
                if len(parts) >= 4:
                    # YYMMDD is usually the last part
                    date_part = parts[-1]
                    if len(date_part) == 6 and date_part.isdigit():
                         return date_part
            return fname

        sorted_entries = dict(sorted(data['entries'].items(), key=sort_key))

        with open(path_str, 'w') as f:
            json.dump(sorted_entries, f, indent=2, sort_keys=False)
    
    @classmethod
    def load(cls, path: Union[str, os.PathLike]) -> 'InvoiceRegistry':
        path_str = str(path)
        if not os.path.exists(path_str):
            return cls()
        with open(path_str, 'r') as f:
            try:
                data = json.load(f)
                return cls(entries=data)
            except json.JSONDecodeError:
                return cls()

class ResolvedInvoice(BaseModel):
    """Container for a fully resolved invoice state before business logic is applied."""
    invoice_model: InvoiceModel
    config_dict: Dict[str, Any]
    client: ClientModel
    sender: SenderModel
    bank: Dict[str, Any]
    invoice_number: str
    canonical_number: str
    inv_date: datetime.date
    is_post_gst: bool

    class Config:
        arbitrary_types_allowed = True