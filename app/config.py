import os
import yaml
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field
from app.modules.config_models import BusinessRulesConfig, BillingConfig

class InvoiceConfig(BaseModel):
    root_dir: Path
    
    # Fields derived from root_dir, calculated during initialization
    data_dir: Path = Field(default=None)
    config_dir: Path = Field(default=None)
    output_dir: Path = Field(default=None)
    templates_dir: Path = Field(default=None)
    profiles_dir: Path = Field(default=None)
    contracts_dir: Path = Field(default=None)
    invoices_dir: Path = Field(default=None)
    assets_dir: Path = Field(default=None)
    registry_path: Path = Field(default=None)
    business_rules_path: Path = Field(default=None)
    billing_config_path: Path = Field(default=None)

    _business_rules: Optional[BusinessRulesConfig] = None
    _billing: Optional[BillingConfig] = None
    
    class Config:
        arbitrary_types_allowed = True

    def model_post_init(self, __context: Any) -> None:
        """Initialize dependent paths after root_dir is set."""
        if not self.data_dir: self.data_dir = self.root_dir / "data"
        if not self.config_dir: self.config_dir = self.root_dir / "config"
        if not self.output_dir: self.output_dir = self.root_dir / "output"
        if not self.templates_dir: self.templates_dir = self.root_dir / "app" / "templates"
        if not self.profiles_dir: self.profiles_dir = self.data_dir / "profiles"
        if not self.contracts_dir: self.contracts_dir = self.data_dir / "contracts"
        if not self.invoices_dir: self.invoices_dir = self.data_dir / "invoices"
        if not self.assets_dir: self.assets_dir = self.data_dir / "assets"
        if not self.registry_path: self.registry_path = self.data_dir / "invoice_registry.json"
        if not self.business_rules_path: self.business_rules_path = self.config_dir / "business_rules.yaml"
        if not self.billing_config_path: self.billing_config_path = self.config_dir / "billing.yaml"

    @property
    def business_rules(self) -> BusinessRulesConfig:
        if self._business_rules is None:
            with open(self.business_rules_path, 'r') as f:
                raw = yaml.safe_load(f)
            self._business_rules = BusinessRulesConfig(**raw)
        return self._business_rules

    @property
    def billing(self) -> BillingConfig:
        if self._billing is None:
            with open(self.billing_config_path, 'r') as f:
                raw = yaml.safe_load(f)
            self._billing = BillingConfig.from_dict(raw)
        return self._billing

    @classmethod
    def load_default(cls) -> 'InvoiceConfig':
        app_dir = Path(__file__).parent
        root_dir = app_dir.parent
        return cls(root_dir=root_dir)

def setup_logging(config: InvoiceConfig):
    log_dir = config.root_dir / "logs"
    os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_dir / 'invoice_generation.log'),
            logging.StreamHandler()
        ]
    )

# Singleton instance
config = InvoiceConfig.load_default()
