import os
import glob
import yaml
import datetime
import csv
import re
from typing import Dict, Tuple

from app.modules.config_models import TurnoverStats


class TurnoverService:
    """Calculates aggregate turnover (taxable value).
    Uses CSV as source of truth for Meta, sidecars for others.
    """

    def __init__(
        self,
        output_dir: str = "output",
        csv_path: str = "docs/2004-02-04_to_2026-01-07.csv",
    ):
        self.output_dir = output_dir
        self.csv_path = csv_path

    def _normalize_id(self, id_str: str) -> str:
        if not id_str:
            return ""
        return re.sub(r"[^A-Z0-9]", "", id_str.upper())

    def _load_meta_truth(self) -> Dict[str, float]:
        """Loads taxable values from the Meta truth CSV."""
        truth = {}
        if not os.path.exists(self.csv_path):
            return truth

        with open(self.csv_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                status = row.get("Invoice status", "").upper()
                if status not in ["PAID", "APPROVED"]:
                    continue

                norm_id = self._normalize_id(row.get("Invoice number", ""))
                amt_raw = row.get("Amount", "")

                # Parse amount
                # Format: "₹116,820.00 INR" or "$7,000.00 USD"
                try:
                    is_usd = "USD" in amt_raw
                    # Extract numeric part
                    val_str = re.sub(r"[^\d.]", "", amt_raw)
                    val = float(val_str)

                    if is_usd:
                        # We store the USD amount; conversion happens during scan using sidecar XR
                        taxable_inr = val
                        # Flag it as USD by storing as negative or a tuple?
                        # Let's store as a dict.
                        truth[norm_id] = {"val": val, "currency": "USD"}
                    else:
                        # Domestic: Convert to taxable (divide by 1.18)
                        taxable_inr = val / 1.18
                        truth[norm_id] = {"val": taxable_inr, "currency": "INR"}
                except (ValueError, KeyError, ZeroDivisionError):
                    continue
        return truth

    def calculate_turnover(self, fp: str) -> TurnoverStats:
        """
        Calculates 'gt' (Preceding FY) and 'cur_gt' (Current FY YTD).
        fp: MMYYYY (e.g., '122025')
        """
        # 1. Determine Periods
        month = int(fp[:2])
        year = int(fp[2:])
        if month >= 4:
            current_fy_start_year = year
        else:
            current_fy_start_year = year - 1

        preceding_fy_start = datetime.date(current_fy_start_year - 1, 4, 1)
        preceding_fy_end = datetime.date(current_fy_start_year, 3, 31)
        curr_cum_start = datetime.date(current_fy_start_year, 4, 1)
        if month == 12:
            curr_cum_end = datetime.date(year, 12, 31)
        else:
            curr_cum_end = datetime.date(year, month + 1, 1) - datetime.timedelta(
                days=1
            )

        # 2. Load Meta Truth
        meta_truth = self._load_meta_truth()

        # 3. Scan Sidecars
        gt = 0.0
        cur_gt = 0.0

        sidecars = glob.glob(os.path.join(self.output_dir, "*.yaml"))
        for path in sidecars:
            try:
                with open(path, "r") as f:
                    data = yaml.safe_load(f)

                inv_date_str = data["invoice"]["date"]
                inv_date = datetime.datetime.strptime(inv_date_str, "%Y-%m-%d").date()
                inv_num = data["invoice"]["number"]
                norm_id = self._normalize_id(inv_num)

                # Determine Taxable INR
                if norm_id in meta_truth:
                    entry = meta_truth[norm_id]
                    if entry["currency"] == "USD":
                        # Convert using Sidecar Exchange Rate (Authoritative for that date)
                        xr = float(data["invoice"].get("exchange_rate") or 1.0)
                        amount_inr = entry["val"] * xr
                    else:
                        amount_inr = entry["val"]
                else:
                    # Non-Meta or missing from CSV: Use sidecar financials
                    subtotal = float(data["financials"]["subtotal"])
                    ex_rate = float(data["invoice"].get("exchange_rate") or 1.0)
                    amount_inr = subtotal * ex_rate

                # Aggregate
                if preceding_fy_start <= inv_date <= preceding_fy_end:
                    gt += amount_inr

                if curr_cum_start <= inv_date <= curr_cum_end:
                    cur_gt += amount_inr

            except (yaml.YAMLError, ValueError, KeyError, TypeError):
                continue

        return TurnoverStats(gt=round(gt, 2), cur_gt=round(cur_gt, 2))
