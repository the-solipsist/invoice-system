import yaml
import glob
from pathlib import Path
from datetime import datetime, date
from typing import List, Dict, Any, Optional
from collections import Counter

from app.config import InvoiceConfig
from app.services.context_builder import InvoiceContextBuilder
from app.modules.models import InvoiceRegistry


class WizardState:
    def __init__(self):
        self.config = InvoiceConfig.load_default()
        self.builder = InvoiceContextBuilder(self.config)
        self.registry = InvoiceRegistry.load(self.config.registry_path)

        # Cache
        self._contracts = None
        self._clients = None
        self._presets = None
        self._banks = None
        self._scanned_values = {}

    @property
    def contracts(self) -> List[Dict]:
        if self._contracts is None:
            self._contracts = self._load_contracts()
        return self._contracts

    @property
    def clients(self) -> Dict[str, Dict]:
        if self._clients is None:
            with open(self.config.profiles_dir / "clients.yaml", "r") as f:
                self._clients = yaml.safe_load(f)
        return self._clients

    @property
    def banks(self) -> Dict[str, Dict]:
        if self._banks is None:
            with open(self.config.profiles_dir / "banks.yaml", "r") as f:
                self._banks = yaml.safe_load(f)
        return self._banks

    @property
    def presets(self) -> Dict[str, Dict]:
        if self._presets is None:
            with open(self.config.billing_config_path, "r") as f:
                data = yaml.safe_load(f)
                self._presets = data.get("invoice_presets", {})
        return self._presets

    def _load_contracts(self) -> List[Dict]:
        """Load contracts and sort by recency of usage."""
        contracts = []
        files = glob.glob(str(self.config.contracts_dir / "*.yaml"))

        # 1. Load Raw
        for f in files:
            try:
                with open(f, "r") as stream:
                    data = yaml.safe_load(stream)
                    data["file_id"] = Path(f).stem
                    contracts.append(data)
            except (yaml.YAMLError, IOError, OSError):
                continue

        # 2. Determine Recency
        # Scan registry/invoices to find last invoice date for each contract
        # Usage heuristic: Count frequency and find max date
        contract_dates = {}

        # We can scan the registry entries? Registry has canonical IDs but maybe not contract IDs.
        # Better: Scan invoice files? Too slow?
        # Fast: Registry keys are filenames. Check filenames for clues? No.
        # Robust: Scan all invoices (40 files is fast).

        invoice_files = glob.glob(str(self.config.invoices_dir / "*.yaml"))
        for inv_path in invoice_files:
            try:
                with open(inv_path, "r") as f:
                    inv = yaml.safe_load(f)
                    cid = inv.get("contract_id")
                    inv_date = inv.get("date")
                    if cid and inv_date:
                        # Parse date
                        # Format YYYY-MM-DD
                        try:
                            d = datetime.strptime(str(inv_date), "%Y-%m-%d").date()
                            if cid not in contract_dates or d > contract_dates[cid]:
                                contract_dates[cid] = d
                        except ValueError:
                            pass
            except (yaml.YAMLError, IOError, OSError):
                pass

        # 3. Sort
        def sort_key(c):
            cid = c.get("id", c["file_id"])
            last_date = contract_dates.get(cid, date(2000, 1, 1))
            return last_date

        contracts.sort(key=sort_key, reverse=True)
        return contracts

    def get_last_invoice(self, contract_id: str) -> Optional[Dict]:
        """Find the most recent invoice for a contract."""
        last_date = date(2000, 1, 1)
        last_inv = None

        invoice_files = glob.glob(str(self.config.invoices_dir / "*.yaml"))
        for inv_path in invoice_files:
            try:
                with open(inv_path, "r") as f:
                    inv = yaml.safe_load(f)
                    if inv.get("contract_id") == contract_id:
                        d_str = str(inv.get("date", "2000-01-01"))
                        try:
                            d = datetime.strptime(d_str, "%Y-%m-%d").date()
                            if d > last_date:
                                last_date = d
                                last_inv = inv
                        except ValueError:
                            pass
            except (yaml.YAMLError, IOError, OSError):
                pass
        return last_inv

    def get_contract_defaults(self, contract_id: str) -> Dict[str, Any]:
        """Resolve the effective configuration for a contract."""
        contract = next((c for c in self.contracts if c.get("id") == contract_id), None)
        if not contract:
            return {}

        preset_id = contract.get("billing_preset", "flat_fee")
        preset = self.presets.get(preset_id, {})

        # Merge Terms
        # Preset Defaults < Contract Terms
        defaults = preset.get("defaults", {})
        terms = contract.get("billing_terms", {})

        merged_terms = {**defaults, **terms}

        return {
            "preset": preset_id,
            "terms": merged_terms,
            "contract": contract,
            "preset_config": preset,
        }

    def scan_values(self, key: str, default_options: List[str] = []) -> List[str]:
        """Scan all contracts, invoices, config, and profiles for unique values of a key."""
        if key in self._scanned_values:
            return self._scanned_values[key]

        values = set(default_options)

        # 1. Scan Contracts
        for c in self.contracts:
            if key in c:
                values.add(str(c[key]))
            if "billing_terms" in c and key in c["billing_terms"]:
                values.add(str(c["billing_terms"][key]))

        # 2. Scan Invoices
        invoice_files = glob.glob(str(self.config.invoices_dir / "*.yaml"))
        for inv_path in invoice_files:
            try:
                with open(inv_path, "r") as f:
                    inv = yaml.safe_load(f)
                    if key in inv:
                        values.add(str(inv[key]))
                    if "billing_terms" in inv and key in inv["billing_terms"]:
                        values.add(str(inv["billing_terms"][key]))
            except (yaml.YAMLError, IOError, OSError):
                pass

        # 3. Scan Config (Presets Defaults)
        for preset in self.presets.values():
            defaults = preset.get("defaults", {})
            if key in defaults:
                values.add(str(defaults[key]))

        # 4. Scan Profiles (e.g. sender currency)
        # self.clients is a Dict[id, client_data]
        for client in self.clients.values():
            if key in client:
                values.add(str(client[key]))

        result = sorted(list(values))
        self._scanned_values[key] = result
        return result

    def suggest_filename(self, client_id: str, date_obj: date) -> str:
        """Suggest a filename: YYYY-MM-client.yaml"""
        # Resolve client slug
        slug = client_id.lower().replace("_", "-")
        # Try to find client name?
        client = self.clients.get(client_id)
        if client:
            # Use a short slug if possible, else client_id
            slug = client.get("id", client_id).replace("_", "-")

        return f"{date_obj.strftime('%Y-%m')}-{slug}.yaml"
