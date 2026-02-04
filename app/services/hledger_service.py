import datetime
from typing import List, Dict, Any, Optional
from app.modules.models import InvoiceModel
from app.services.financials_service import FinancialsService


class HledgerService:
    """Generates hledger journal entries with strict formatting and alignment."""

    def __init__(self, config, fee_calculator):
        self.config = config
        self.financials_service = FinancialsService(config, fee_calculator)
        self.hledger_rules = config.business_rules.hledger
        self.account_width = self.hledger_rules.account_width

    def get_client_slug(self, client_id: str) -> str:
        mapping = self.hledger_rules.client_slugs
        if not client_id:
            return "Unknown"
        return mapping.get(client_id, client_id.split("_")[0].capitalize())

    def _format_amt(self, amount: float, currency: str) -> str:
        """Formats amount with commodity, right-aligned."""
        val = f"₹{amount:,.2f}" if currency == "INR" else f"{currency} {amount:,.2f}"
        return val.rjust(18)

    def _print_posting(
        self, account: str, amount: float, currency: str, comment: str = ""
    ):
        """Prints a single aligned hledger posting line."""
        formatted_amt = self._format_amt(amount, currency)
        line = f"    {account.ljust(self.account_width)}  {formatted_amt}"
        if comment:
            line += f"  ; {comment}"
        print(line)

    def print_work_and_invoice(
        self, gen_result: Dict[str, Any], item_finished_dates: List[str]
    ):
        inv_model = gen_result["invoice_model"]
        config_dict = gen_result["config_dict"]
        client = gen_result["client"]
        invoice_num = gen_result["invoice_number"]

        client_slug = self.get_client_slug(client.id)
        service = config_dict.get("service") or "Consulting"
        project = (
            service.split(" - ")[0].replace("Virtual ", "").split(" for ")[0].title()
        )
        contract_ref = config_dict.get("contract_ref")
        po = config_dict.get("po")

        # 1. Work Done Entries
        for idx, item in enumerate(inv_model.line_items):
            fin = self.financials_service.perform_calculation(
                config_dict["billing_preset"],
                config_dict["params"],
                [item],
                client,
                gen_result["sender"],
                datetime.datetime.strptime(inv_model.date, "%Y-%m-%d").date(),
            )

            f_date = item_finished_dates[idx]
            tax_type = fin["tax_lines"][0]["label"] if fin["tax_lines"] else "GST"

            print(
                f"\n{f_date} {client_slug} | Business | {project} | Work Done  ; invoice:{invoice_num}"
            )

            accrued = f"Assets:Accrued:Fees:{client_slug}"
            if contract_ref:
                accrued += f":{contract_ref}"
            if po:
                accrued += f":{po}"

            self._print_posting(accrued, fin["final_total"], client.currency)
            if fin["tax_total"] > 0:
                self._print_posting(
                    f"Liabilities:Tax:GST:{tax_type}:{f_date[:7]}",
                    -float(fin["tax_total"]),
                    client.currency,
                )

            income = f"Income:Profession:Fees:{client_slug}"
            if contract_ref:
                income += f":{contract_ref}"
            self._print_posting(income, -float(fin["subtotal"]), client.currency)

        # 2. Invoice Entry
        print(
            f"\n{inv_model.date} {client_slug} | Business | {project} | Invoice  ; invoice:{invoice_num}"
        )
        receivable = f"Assets:Receivable:Fees:{client_slug}"
        if contract_ref:
            receivable += f":{contract_ref}"
        self._print_posting(
            receivable, float(gen_result["financials"]["final_total"]), client.currency
        )

        accrued = f"Assets:Accrued:Fees:{client_slug}"
        if contract_ref:
            accrued += f":{contract_ref}"
        if po:
            accrued += f":{po}"
        self._print_posting(
            accrued, -float(gen_result["financials"]["final_total"]), client.currency
        )

    def print_receipt(
        self,
        gen_result: Dict[str, Any],
        receipt_date: str,
        bank: str,
        tds_amount: Optional[str] = None,
        exchange_rate: Optional[str] = None,
    ):
        client = gen_result["client"]
        config_dict = gen_result["config_dict"]
        client_slug = self.get_client_slug(client.id)
        service = config_dict.get("service") or "Consulting"
        project = (
            service.split(" - ")[0].replace("Virtual ", "").split(" for ")[0].title()
        )
        contract_ref = config_dict.get("contract_ref")
        total = float(gen_result["financials"]["final_total"])

        print(
            f"\n{receipt_date} {client_slug} | Business | {project} | Receipt  ; invoice:{gen_result['invoice_number']}"
        )

        if client.currency != "INR":
            rate = float(exchange_rate or 1.0)
            inr_val = total * rate
            bank_id = self.hledger_rules.bank_aliases.get(bank, bank)
            bank_acc = f"Assets:Savings:{bank_id}"

            self._print_posting(
                bank_acc, inr_val, "INR", f"rate: {rate} INR / {client.currency}"
            )
            self._print_posting(
                f"Equity:Trading:Currency:INR-{client.currency}:INR", -inr_val, "INR"
            )
            self._print_posting(
                f"Equity:Trading:Currency:INR-{client.currency}:{client.currency}",
                total,
                client.currency,
            )

            receivable = f"Assets:Receivable:Fees:{client_slug}"
            if contract_ref:
                receivable += f":{contract_ref}"
            self._print_posting(receivable, -total, client.currency)
        else:
            tds = float(tds_amount or 0.0)
            self._print_posting(f"Assets:Savings:{bank}", total - tds, "INR")
            if tds > 0:
                year = datetime.datetime.strptime(receipt_date, "%Y-%m-%d").year
                fy = (
                    f"FY{str(year - 1)[-2:]}-{str(year)[-2:]}"
                    if datetime.datetime.strptime(receipt_date, "%Y-%m-%d").month < 4
                    else f"FY{str(year)[-2:]}-{str(year + 1)[-2:]}"
                )
                self._print_posting(
                    f"Expenses:Tax:Income:{fy}:TDS:{client_slug}", tds, "INR"
                )

            receivable = f"Assets:Receivable:Fees:{client_slug}"
            if contract_ref:
                receivable += f":{contract_ref}"
            self._print_posting(receivable, -total, "INR")
