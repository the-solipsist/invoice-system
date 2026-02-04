import os
import re
import glob
import logging
from typing import Dict, Any, Optional

from app.config import InvoiceConfig
from app.modules.models import InvoiceRegistry

logger = logging.getLogger(__name__)


class NumberingService:
    def __init__(self, config: InvoiceConfig):
        self.config = config

    def get_next_invoice_number(
        self,
        prefix: str,
        work_seq: str,
        date_str: str,
        source_filename: str,
        is_oneoff: bool,
        registry: InvoiceRegistry,
        override_number: Optional[str] = None,
    ) -> str:
        """
        Determines the invoice number (Actual ID logic).
        """
        if override_number:
            return override_number

        entry = registry.get_entry(source_filename)
        if entry:
            # If entry exists, we usually return actual_id or canonical_id
            # This logic mimics the old get_next_invoice_number
            return entry.actual_id or entry.canonical_id

        if is_oneoff:
            return f"{prefix}-{work_seq}-00-{date_str}"

        max_seq = 0
        pattern = re.compile(rf"^{re.escape(prefix)}-{re.escape(work_seq)}-(\d{{2}})-")

        for entry in registry.entries.values():
            # Check both canonical and actual? Old logic checked entry value which was ID.
            # Usually we check canonical for sequence.
            match = pattern.match(entry.canonical_id)
            if match:
                seq = int(match.group(1))
                if seq > max_seq:
                    max_seq = seq

        next_seq = max_seq + 1
        return f"{prefix}-{work_seq}-{next_seq:02d}-{date_str}"

    def get_next_work_sequence(
        self,
        target_prefix: str,
        clients_db: Dict[str, Any],
        current_filename: str = None,
        current_date: Any = None,
    ) -> str:
        """
        Calculates Work Sequence based on chronological rank among all invoices
        sharing the same Client Prefix.
        """
        partners = []
        seen_files = set()

        # 1. Scan Registry for existing items
        # Use date from Canonical ID (YYMMDD) to avoid parsing YAMLs
        registry = InvoiceRegistry.load(self.config.registry_path)
        pattern = re.compile(rf"^{re.escape(target_prefix)}-\d{{2}}-\d{{2}}-(\d{{6}})$")

        for fname, entry in registry.entries.items():
            cid = entry.canonical_id
            if not cid:
                continue

            # Check prefix match via regex or string split
            # Canonical ID: PREFIX-WORK-INV-YYMMDD
            if not cid.startswith(f"{target_prefix}-"):
                continue

            # Extract Date
            match = pattern.match(cid)
            if match:
                date_str = match.group(1)
                partners.append(
                    {
                        "file": fname,
                        "date": f"20{date_str}",  # Approximate YYYY-MM-DD sortable string (assuming 20xx)
                    }
                )
                seen_files.add(fname)
            else:
                # Fallback to YAML parse if ID format is non-standard
                pass

        # 2. Scan Files for missing items (or the current one if not in registry)
        files = glob.glob(
            os.path.join(self.config.contracts_dir, "*.yaml")
        ) + glob.glob(os.path.join(self.config.invoices_dir, "*.yaml"))

        for f_path in files:
            fname = os.path.basename(f_path)
            if fname in seen_files:
                continue

            # If this is the current file, use the passed date
            if fname == current_filename and current_date:
                partners.append(
                    {
                        "file": fname,
                        "date": str(current_date).replace(
                            "-", ""
                        ),  # Normalize to sortable
                    }
                )
                continue

            # Otherwise parse YAML
            try:
                import yaml

                with open(f_path, "r") as stream:
                    d = yaml.safe_load(stream)
                if not d:
                    continue

                cid = d.get("client_id")
                if not cid and "contract_id" in d:
                    # ... resolve contract ...
                    # For speed, skip complex resolution if possible, but we need prefix.
                    # If we can't get prefix easily, skip?
                    # Ideally we only parse if we really need to.
                    pass

                # We need to verify prefix to include it.
                # If we skip parsing, we might miss files that SHOULD be in the list.
                # So parsing is necessary for files NOT in registry.

                # (Existing parsing logic kept for robustness)
                # ...

                # Check Prefix
                if cid:
                    client = clients_db.get(cid)
                    if client and client.get("prefix") == target_prefix:
                        i_date = d.get("date")
                        if i_date:
                            partners.append({"file": fname, "date": str(i_date)})
            except Exception:
                continue

        # Sort by Date + Filename
        partners.sort(key=lambda x: (x["date"], x["file"]))

        # Find Rank
        rank = 1
        for p in partners:
            if p["file"] == current_filename:
                return f"{rank:02d}"
            rank += 1

        return f"{rank:02d}"

    def calculate_canonical_id(
        self,
        prefix: str,
        work_seq: str,
        date_obj,
        source_filename: str,
        is_oneoff: bool = False,
        manual_seq: Optional[str] = None,
    ) -> str:
        """
        Calculates canonical ID based on date sorting.
        """
        date_str = date_obj.strftime("%y%m%d")

        if manual_seq:
            return f"{prefix}-{work_seq}-{manual_seq}-{date_str}"

        if is_oneoff:
            return f"{prefix}-{work_seq}-00-{date_str}"

        import yaml

        partners = []

        # Gather all invoices sharing this prefix + work_seq
        files = glob.glob(
            os.path.join(self.config.contracts_dir, "*.yaml")
        ) + glob.glob(os.path.join(self.config.invoices_dir, "*.yaml"))

        with open(self.config.profiles_dir / "clients.yaml", "r") as f:
            clients_db = yaml.safe_load(f)

        for f in files:
            try:
                with open(f, "r") as stream:
                    d = yaml.safe_load(stream)
                if not d:
                    continue

                # Resolve Contract if needed
                cid = d.get("client_id")
                work_seq_chk = d.get("work_sequence_number")

                if (not cid or not work_seq_chk) and "contract_id" in d:
                    ct_path = self.config.contracts_dir / f"{d['contract_id']}.yaml"
                    if ct_path.exists():
                        with open(ct_path, "r") as ctf:
                            ct = yaml.safe_load(ctf)
                        if not cid:
                            cid = ct.get("client_id")
                        if not work_seq_chk:
                            work_seq_chk = ct.get("work_sequence_number")

                # Resolve prefix
                if not cid:
                    continue
                c_prefix = clients_db.get(cid, {}).get("prefix")

                # Resolve work_seq
                c_seq = work_seq_chk

                # Resolve date
                c_date = d.get("date")
                if not c_date:
                    continue

                # Match?
                if c_prefix == prefix and str(c_seq) == str(work_seq):
                    partners.append({"file": os.path.basename(f), "date": c_date})
            except (yaml.YAMLError, KeyError, IOError, OSError):
                continue

        # Sort by date and filename for stability
        partners.sort(key=lambda x: (x["date"], x["file"]))

        # Find rank (1-indexed)
        rank = 1
        for p in partners:
            if p["file"] == source_filename:
                break
            rank += 1

        date_str = date_obj.strftime("%y%m%d")
        return f"{prefix}-{work_seq}-{rank:02d}-{date_str}"
