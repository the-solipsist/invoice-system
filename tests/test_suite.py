import unittest
import os
import sys
import datetime
import tempfile
import shutil
from pathlib import Path
from decimal import Decimal
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.invoice_controller import generate
from app.services.numbering import NumberingService
from app.modules.fee_calculator import FeeCalculator
from app.modules.models import (
    InvoiceItem,
    InvoiceModel,
    ClientModel,
    SenderModel,
    InvoiceRegistry,
    RegistryEntry,
    ResolvedInvoice,
)
from app.services.context_builder import InvoiceContextBuilder
from app.services.financials_service import FinancialsService
from app.services.view_model_service import ViewModelService
from app.services.turnover_service import TurnoverService
from app.config import InvoiceConfig


class TestNumberingService(unittest.TestCase):
    def setUp(self):
        self.config = InvoiceConfig.load_default()
        self.service = NumberingService(self.config)

    def test_canonical_id_standalone(self):
        """Test that standalone invoices get '00' sequence."""
        dt = datetime.date(2025, 1, 1)
        # standalone = True
        cid = self.service.calculate_canonical_id(
            "TEST", "01", dt, "file.yaml", is_oneoff=True
        )
        self.assertTrue(cid.startswith("TEST-01-00"))
        self.assertTrue(cid.endswith("250101"))

    def test_canonical_id_series(self):
        """Test that series invoices get sequential numbers."""
        dt = datetime.date(2025, 1, 1)
        # we need a mock registry for sequence
        registry = InvoiceRegistry()
        # Mock finding existing files in numbering.py is hard without real files,
        # but calculate_canonical_id handles manual_seq
        cid = self.service.calculate_canonical_id(
            "TEST", "01", dt, "file.yaml", is_oneoff=False, manual_seq="05"
        )
        self.assertEqual(cid, "TEST-01-05-250101")


class TestTurnoverService(unittest.TestCase):
    def setUp(self):
        self.temp_out = tempfile.mkdtemp()
        self.service = TurnoverService(output_dir=self.temp_out)

    def tearDown(self):
        shutil.rmtree(self.temp_out)

    def test_fy_logic(self):
        """Test that cur_gt correctly aggregates from April of the same FY."""
        # Create a mock sidecar for April 2025
        sidecar = {
            "invoice": {"date": "2025-04-30", "number": "INV-1"},
            "financials": {"subtotal": 1000},
            "sender": {"gstin": "123"},
        }
        with open(os.path.join(self.temp_out, "inv1.yaml"), "w") as f:
            __import__("yaml").dump(sidecar, f)

        # Period: Dec 2025
        stats = self.service.calculate_turnover("122025")
        self.assertEqual(stats.cur_gt, 1000.0)

        # Period: March 2025 (belongs to FY 24-25)
        # cur_gt for March 2025 should be Apr 24 -> Mar 25
        stats_prev = self.service.calculate_turnover("032025")
        self.assertEqual(
            stats_prev.cur_gt, 0.0
        )  # April 25 is too late for FY 24-25 return


class TestFeeCalculator(unittest.TestCase):
    def test_retainer_threshold(self):
        """Test that retainer only bills excess if threshold exceeded."""
        config = {
            "pricing_formulas": {
                "retainer": {
                    "components": [
                        {"type": "flat_rate", "id": "base", "amount": 1000},
                        {
                            "type": "unit_rate",
                            "id": "excess",
                            "rate": 100,
                            "min_quantity": 5,
                        },
                    ]
                }
            },
            "invoice_presets": {
                "retainer": {
                    "formula_id": "retainer",
                    "billing_table": {
                        "row_templates": {
                            "base": {"label": "Base"},
                            "excess": {"label": "Excess"},
                        }
                    },
                }
            },
        }
        calc = FeeCalculator(config)

        # 1. Under threshold (4 hours)
        items = [InvoiceItem(description="Work", hours=4)]
        res = calc.calculate("retainer", items, {}, datetime.date.today())
        self.assertEqual(res["subtotal"], Decimal("1000.00"))

        # 2. Over threshold (7 hours)
        items = [InvoiceItem(description="Work", hours=7)]
        res = calc.calculate("retainer", items, {}, datetime.date.today())
        # 1000 + (7-5)*100 = 1200
        self.assertEqual(res["subtotal"], Decimal("1200.00"))


class TestGstLogic(unittest.TestCase):
    def setUp(self):
        self.config = InvoiceConfig.load_default()
        # Ensure test date is post-GST
        self.date = datetime.date(2025, 1, 1)
        self.calc = MagicMock()
        self.service = FinancialsService(self.config, self.calc)

    def test_intra_state_gst(self):
        """Test CGST/SGST for same state."""
        self.calc.calculate.return_value = {"subtotal": Decimal("1000.00"), "lines": []}
        client = ClientModel(state_code="33", gst_category="regular")
        sender = SenderModel(state_code="33")

        fin = self.service.perform_calculation("any", {}, [], client, sender, self.date)
        self.assertEqual(fin["tax_total"], Decimal("180.00"))
        self.assertEqual(fin["tax_lines"][0]["label"], "CGST")
        self.assertEqual(fin["tax_lines"][1]["label"], "SGST")

    def test_inter_state_gst(self):
        """Test IGST for different state."""
        self.calc.calculate.return_value = {"subtotal": Decimal("1000.00"), "lines": []}
        client = ClientModel(state_code="06", gst_category="regular")  # Haryana
        sender = SenderModel(state_code="33")  # TN

        fin = self.service.perform_calculation("any", {}, [], client, sender, self.date)
        self.assertEqual(fin["tax_total"], Decimal("180.00"))
        self.assertEqual(fin["tax_lines"][0]["label"], "IGST")


class TestContextBuilder(unittest.TestCase):
    def setUp(self):
        self.config = InvoiceConfig.load_default()
        self.builder = InvoiceContextBuilder(self.config)

    def test_merge_contract_overrides(self):
        """Test that invoice data overrides contract data correctly."""
        invoice = InvoiceModel(
            date="2025-01-15",
            contract_id="test_contract",
            billing_terms={"rate": 5000, "threshold": 10},
            params={"currency": "USD"},
        )

        contract = {
            "client_id": "test_client",
            "bank_id": "test_bank",
            "sender_id": "test_sender",
            "billing_preset": "retainer",
            "billing_terms": {"rate": 3000, "base_amount": 10000},
            "params": {"currency": "INR", "unit_name": "Hours"},
        }

        result = self.builder.merge_contract(invoice, contract)

        # Invoice billing_terms should override contract
        self.assertEqual(result["params"]["rate"], 5000)
        self.assertEqual(result["params"]["threshold"], 10)
        # But base_amount from contract should remain
        self.assertEqual(result["params"]["base_amount"], 10000)
        # Invoice params should override contract params
        self.assertEqual(result["params"]["currency"], "USD")
        # But unit_name from contract should remain
        self.assertEqual(result["params"]["unit_name"], "Hours")

    def test_build_config_from_invoice_standalone(self):
        """Test building config for standalone invoice without contract."""
        invoice = InvoiceModel(
            date="2025-01-15",
            client_id="test_client",
            sender_id="test_sender",
            bank_id="test_bank",
            billing_preset="flat_fee",
            billing_terms={"label": "Consulting Fee"},
            params={"amount": 50000},
        )

        result = self.builder.build_config_from_invoice(invoice)

        self.assertEqual(result["client_id"], "test_client")
        self.assertEqual(result["sender_id"], "test_sender")
        self.assertEqual(result["bank_id"], "test_bank")
        self.assertEqual(result["billing_preset"], "flat_fee")
        self.assertEqual(result["params"]["label"], "Consulting Fee")
        self.assertEqual(result["params"]["amount"], 50000)

    def test_build_config_missing_required_fields(self):
        """Test that missing required fields raise ValueError."""
        invoice = InvoiceModel(date="2025-01-15")

        with self.assertRaises(ValueError):
            self.builder.build_config_from_invoice(invoice)


class TestViewModelService(unittest.TestCase):
    def setUp(self):
        self.config = InvoiceConfig.load_default()
        self.fee_calc = FeeCalculator(self.config.billing)
        self.service = ViewModelService(self.config, self.fee_calc)

    def test_build_context_basic_structure(self):
        """Test that build_context returns all required keys."""
        invoice = InvoiceModel(date="2025-01-15", line_items=[])
        client = ClientModel(
            id="test", name="Test Client", currency="INR", prefix="TST"
        )
        sender = SenderModel(id="sender", name="Test Sender")

        resolved = ResolvedInvoice(
            invoice_model=invoice,
            config_dict={"billing_preset": "flat_fee", "params": {}, "sac": "998399"},
            client=client,
            sender=sender,
            bank={"name": "Test Bank"},
            invoice_number="INV-001",
            canonical_number="TST-01-01-250115",
            inv_date=datetime.date(2025, 1, 15),
            is_post_gst=True,
        )

        financials = {
            "subtotal": Decimal("1000.00"),
            "tax_total": Decimal("180.00"),
            "lines": [],
        }
        context = self.service.build_context(resolved, financials)

        # Check all required top-level keys
        self.assertIn("invoice", context)
        self.assertIn("sender", context)
        self.assertIn("client", context)
        self.assertIn("bank", context)
        self.assertIn("items", context)
        self.assertIn("table_view", context)
        self.assertIn("financials", context)
        self.assertIn("headers", context)

        # Check invoice keys
        inv = context["invoice"]
        self.assertEqual(inv["number"], "INV-001")
        self.assertEqual(inv["canonical_number"], "TST-01-01-250115")
        self.assertEqual(inv["currency"], "INR")
        self.assertTrue(inv["is_post_gst"])

    def test_build_context_with_line_items(self):
        """Test table view generation with line items."""
        items = [
            InvoiceItem(
                description="Task 1", quantity=Decimal("5.00"), date="2025-01-10"
            ),
            InvoiceItem(
                description="Task 2",
                quantity=Decimal("3.50"),
                date="2025-01-12",
                owner="AJ",
            ),
        ]
        invoice = InvoiceModel(date="2025-01-15", line_items=items)
        client = ClientModel(
            id="test", name="Test Client", currency="INR", prefix="TST"
        )
        sender = SenderModel(id="sender", name="Test Sender")

        resolved = ResolvedInvoice(
            invoice_model=invoice,
            config_dict={
                "billing_preset": "rate",
                "params": {"unit_name": "Hours"},
                "sac": "998399",
            },
            client=client,
            sender=sender,
            bank={},
            invoice_number="INV-001",
            canonical_number="TST-01-01-250115",
            inv_date=datetime.date(2025, 1, 15),
            is_post_gst=True,
        )

        financials = {"subtotal": Decimal("850.00"), "lines": []}
        context = self.service.build_context(resolved, financials)

        # Check items are preserved
        self.assertEqual(len(context["items"]), 2)

        # Check table view has rows
        self.assertEqual(len(context["table_view"]["rows"]), 2)

    def test_build_pos_string_overseas(self):
        """Test place of supply for overseas clients."""
        invoice = InvoiceModel(date="2025-01-15", line_items=[])
        client = ClientModel(
            id="test",
            name="Test Client",
            currency="USD",
            prefix="TST",
            gst_category="overseas",
            state_code="96",
        )
        sender = SenderModel(id="sender", name="Test Sender", state_code="33")

        resolved = ResolvedInvoice(
            invoice_model=invoice,
            config_dict={"billing_preset": "flat_fee", "params": {}, "sac": "998399"},
            client=client,
            sender=sender,
            bank={},
            invoice_number="INV-001",
            canonical_number="TST-01-01-250115",
            inv_date=datetime.date(2025, 1, 15),
            is_post_gst=True,
        )

        financials = {"subtotal": Decimal("1000.00"), "lines": []}
        context = self.service.build_context(resolved, financials)

        self.assertIn("Export", context["invoice"]["place_of_supply"])


class TestFeeCalculatorEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = {
            "pricing_formulas": {
                "flat_fee": {"components": [{"type": "flat_rate", "id": "fee"}]},
                "unit_rate": {
                    "components": [
                        {"type": "unit_rate", "id": "hourly", "rate": "{rate}"}
                    ]
                },
                "retainer": {
                    "components": [
                        {"type": "flat_rate", "id": "base", "amount": "{base_amount}"},
                        {
                            "type": "unit_rate",
                            "id": "excess",
                            "rate": "{excess_rate}",
                            "min_quantity": "{threshold}",
                        },
                    ]
                },
            },
            "invoice_presets": {
                "flat_fee": {
                    "formula_id": "flat_fee",
                    "billing_table": {
                        "row_templates": {"fee": {"label": "Fee", "details": "Fixed"}}
                    },
                    "defaults": {"label": "Fee", "details": "Fixed Fee"},
                },
                "unit_rate": {
                    "formula_id": "unit_rate",
                    "billing_table": {
                        "row_templates": {
                            "hourly": {"label": "Hours", "details": "{qty} @ {rate}"}
                        }
                    },
                    "defaults": {
                        "unit": "hour",
                        "unit_name": "Hours",
                        "billing_label": "Hours",
                    },
                },
                "retainer": {
                    "formula_id": "retainer",
                    "billing_table": {
                        "row_templates": {
                            "base": {"label": "Retainer"},
                            "excess": {"label": "Excess"},
                        }
                    },
                    "defaults": {"billing_label": "Retainer"},
                },
            },
        }
        self.calc = FeeCalculator(self.config)

    def test_zero_quantity_items(self):
        """Test handling of items with zero quantity."""
        items = [
            InvoiceItem(description="Task 1", quantity=Decimal("0.00")),
            InvoiceItem(description="Task 2", quantity=Decimal("5.00")),
        ]

        result = self.calc.calculate(
            "unit_rate", items, {"rate": 100}, datetime.date.today()
        )
        # Should only bill for the 5 hours
        self.assertEqual(result["subtotal"], Decimal("500.00"))

    def test_empty_items_list(self):
        """Test calculation with no line items."""
        result = self.calc.calculate(
            "flat_fee", [], {"label": "Fee", "details": "Test"}, datetime.date.today()
        )
        # Flat fee without amount should return empty
        self.assertEqual(result["subtotal"], Decimal("0.00"))
        self.assertEqual(len(result["lines"]), 0)

    def test_multiple_rate_groups(self):
        """Test grouping items by different rates."""
        items = [
            InvoiceItem(
                description="Senior", quantity=Decimal("5.00"), rate=Decimal("200.00")
            ),
            InvoiceItem(
                description="Junior", quantity=Decimal("10.00"), rate=Decimal("100.00")
            ),
            InvoiceItem(
                description="Senior", quantity=Decimal("3.00"), rate=Decimal("200.00")
            ),
        ]

        result = self.calc.calculate("unit_rate", items, {}, datetime.date.today())

        # Should have 2 lines: one for rate 200, one for rate 100
        self.assertEqual(len(result["lines"]), 2)

        # Check amounts: (5+3)*200 = 1600, 10*100 = 1000
        amounts = [line["amount"] for line in result["lines"]]
        self.assertIn(Decimal("1600.00"), amounts)
        self.assertIn(Decimal("1000.00"), amounts)
        self.assertEqual(result["subtotal"], Decimal("2600.00"))

    def test_exact_threshold_boundary(self):
        """Test retainer calculation exactly at threshold."""
        items = [InvoiceItem(description="Work", hours=Decimal("5.00"))]

        result = self.calc.calculate(
            "retainer",
            items,
            {"base_amount": 1000, "excess_rate": 100, "threshold": 5},
            datetime.date.today(),
        )

        # At exactly threshold, no excess should be billed
        self.assertEqual(result["subtotal"], Decimal("1000.00"))

    def test_retainer_no_excess(self):
        """Test retainer under threshold doesn't bill excess."""
        items = [InvoiceItem(description="Work", hours=Decimal("3.00"))]

        result = self.calc.calculate(
            "retainer",
            items,
            {"base_amount": 1000, "excess_rate": 100, "threshold": 5},
            datetime.date.today(),
        )

        # Only base amount, no excess line
        self.assertEqual(result["subtotal"], Decimal("1000.00"))
        # Should have only 1 line (base)
        self.assertEqual(len(result["lines"]), 1)


class TestInvoiceRegistry(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.registry_path = os.path.join(self.temp_dir, "registry.json")

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_save_and_load(self):
        """Test registry persistence roundtrip."""
        registry = InvoiceRegistry()
        registry.update_entry(
            "invoice1.yaml", "TST-01-01-250115", "abc123hash", "INV-001"
        )

        registry.save(self.registry_path)

        # Load and verify
        loaded = InvoiceRegistry.load(self.registry_path)
        entry = loaded.get_entry("invoice1.yaml")

        self.assertIsNotNone(entry)
        self.assertEqual(entry.canonical_id, "TST-01-01-250115")
        self.assertEqual(entry.content_hash, "abc123hash")
        self.assertEqual(entry.actual_id, "INV-001")

    def test_mark_as_paid(self):
        """Test payment tracking."""
        registry = InvoiceRegistry()
        registry.update_entry("inv.yaml", "ID-001", "hash123")

        registry.mark_as_paid("inv.yaml", "2025-02-01")

        entry = registry.get_entry("inv.yaml")
        self.assertEqual(entry.payment_received, "2025-02-01")

    def test_mark_paid_nonexistent(self):
        """Test marking non-existent invoice as paid raises error."""
        registry = InvoiceRegistry()

        with self.assertRaises(ValueError):
            registry.mark_as_paid("nonexistent.yaml", "2025-02-01")

    def test_load_nonexistent_file(self):
        """Test loading from non-existent path returns empty registry."""
        registry = InvoiceRegistry.load("/nonexistent/path/registry.json")
        self.assertEqual(len(registry.entries), 0)

    def test_update_existing_entry(self):
        """Test updating an existing entry preserves other entries."""
        registry = InvoiceRegistry()
        registry.update_entry("inv1.yaml", "ID-001", "hash1")
        registry.update_entry("inv2.yaml", "ID-002", "hash2")

        # Update first entry
        registry.update_entry("inv1.yaml", "ID-001-NEW", "hash1-new", "ACT-001")

        # Both should exist
        self.assertEqual(registry.get_entry("inv1.yaml").canonical_id, "ID-001-NEW")
        self.assertEqual(registry.get_entry("inv2.yaml").canonical_id, "ID-002")


class TestValidationErrors(unittest.TestCase):
    def test_invalid_gstin_format(self):
        """Test that invalid GSTIN raises validation error."""
        with self.assertRaises(ValueError) as context:
            ClientModel(id="test", name="Test", gstin="INVALID123")

        self.assertIn("Invalid GSTIN", str(context.exception))

    def test_valid_gstin_accepted(self):
        """Test that valid GSTIN passes validation."""
        # Valid GSTIN format: 2 digits, 5 letters, 4 digits, 1 letter, 1 alphanumeric, Z, 1 alphanumeric
        client = ClientModel(id="test", name="Test", gstin="33AABCU9603R1ZM")
        self.assertEqual(client.gstin, "33AABCU9603R1ZM")

    def test_invalid_pan_format(self):
        """Test that invalid PAN raises validation error."""
        with self.assertRaises(ValueError) as context:
            ClientModel(id="test", name="Test", pan="INVALID")

        self.assertIn("Invalid PAN", str(context.exception))

    def test_valid_pan_accepted(self):
        """Test that valid PAN passes validation."""
        # Valid PAN format: 5 letters, 4 digits, 1 letter
        client = ClientModel(id="test", name="Test", pan="ABCDE1234F")
        self.assertEqual(client.pan, "ABCDE1234F")

    def test_invalid_date_format(self):
        """Test that invalid date format raises validation error."""
        with self.assertRaises(ValueError) as context:
            InvoiceModel(date="15-01-2025")  # Wrong format

        self.assertIn("Incorrect data format", str(context.exception))


class TestMilestoneExpansion(unittest.TestCase):
    def setUp(self):
        self.config = InvoiceConfig.load_default()
        self.builder = InvoiceContextBuilder(self.config)

    def test_milestone_percentage_calculation(self):
        """Test milestone amount calculation from percentage."""
        invoice = InvoiceModel(date="2025-01-15", milestones_refs=["m1", "m2"])

        contract = {
            "client_id": "test_client",
            "bank_id": "test_bank",
            "sender_id": "test_sender",
            "milestones": {
                "m1": {"percentage": 30, "description": "First Delivery"},
                "m2": {"percentage": 70, "description": "Final Delivery"},
            },
        }

        params = {"total_contract_value": 100000}
        raw_data = {"milestones_refs": ["m1", "m2"]}

        self.builder.expand_milestones(invoice, contract, params, raw_data)

        # Should create 2 line items
        self.assertEqual(len(invoice.line_items), 2)

        # Check amounts: 30% and 70% of 100000
        amounts = [item.amount for item in invoice.line_items]
        self.assertEqual(amounts[0], Decimal("30000.00"))
        self.assertEqual(amounts[1], Decimal("70000.00"))

    def test_milestone_fixed_amount(self):
        """Test milestone with fixed amount instead of percentage."""
        invoice = InvoiceModel(date="2025-01-15", milestones_refs=["m1"])

        contract = {
            "client_id": "test_client",
            "bank_id": "test_bank",
            "sender_id": "test_sender",
            "milestones": {
                "m1": {"amount": 50000, "description": "Fixed Price Milestone"}
            },
        }

        params = {}
        raw_data = {"milestones_refs": ["m1"]}

        self.builder.expand_milestones(invoice, contract, params, raw_data)

        self.assertEqual(len(invoice.line_items), 1)
        self.assertEqual(invoice.line_items[0].amount, Decimal("50000.00"))

    def test_milestone_no_refs(self):
        """Test that no milestones are expanded when refs are empty."""
        invoice = InvoiceModel(date="2025-01-15", line_items=[])

        contract = {"milestones": {"m1": {"percentage": 50, "description": "Test"}}}

        params = {"total_contract_value": 100000}
        raw_data = {}

        original_items = invoice.line_items.copy()
        self.builder.expand_milestones(invoice, contract, params, raw_data)

        # Should not modify items when no refs
        self.assertEqual(invoice.line_items, original_items)

    def test_milestone_missing_ref(self):
        """Test handling of missing milestone reference."""
        invoice = InvoiceModel(date="2025-01-15", milestones_refs=["m1", "nonexistent"])

        contract = {
            "client_id": "test_client",
            "bank_id": "test_bank",
            "sender_id": "test_sender",
            "milestones": {"m1": {"percentage": 100, "description": "Only Milestone"}},
        }

        params = {"total_contract_value": 50000}
        raw_data = {"milestones_refs": ["m1", "nonexistent"]}

        self.builder.expand_milestones(invoice, contract, params, raw_data)

        # Should only create item for existing milestone (nonexistent is silently skipped)
        self.assertEqual(len(invoice.line_items), 1)
        self.assertEqual(invoice.line_items[0].amount, Decimal("50000.00"))


class TestGstLogicExtended(unittest.TestCase):
    def setUp(self):
        self.config = InvoiceConfig.load_default()
        self.calc = MagicMock()
        self.service = FinancialsService(self.config, self.calc)

    def test_overseas_export_lut(self):
        """Test that overseas exports get 0% tax with LUT notification."""
        self.calc.calculate.return_value = {"subtotal": Decimal("5000.00"), "lines": []}

        # Overseas client
        client = ClientModel(state_code="96", gst_category="overseas", currency="USD")
        sender = SenderModel(state_code="33", lut_number="LUT-2024-001")

        fin = self.service.perform_calculation(
            "any", {}, [], client, sender, datetime.date(2025, 1, 1)
        )

        # Should have 0 tax for export
        self.assertEqual(fin["tax_total"], Decimal("0.00"))
        self.assertEqual(len(fin["tax_lines"]), 0)

    def test_pre_gst_no_tax(self):
        """Test that pre-GST threshold date has no tax."""
        self.calc.calculate.return_value = {
            "subtotal": Decimal("10000.00"),
            "lines": [],
        }

        client = ClientModel(state_code="33", gst_category="regular")
        sender = SenderModel(state_code="33")

        # Date before GST threshold
        pre_gst_date = datetime.date(2024, 4, 15)
        fin = self.service.perform_calculation(
            "any", {}, [], client, sender, pre_gst_date
        )

        self.assertEqual(fin["tax_total"], Decimal("0.00"))

    def test_post_gst_intra_state(self):
        """Test post-GST intra-state has CGST+SGST."""
        self.calc.calculate.return_value = {
            "subtotal": Decimal("10000.00"),
            "lines": [],
        }

        client = ClientModel(state_code="33", gst_category="regular")
        sender = SenderModel(state_code="33")

        post_gst_date = datetime.date(2024, 4, 16)
        fin = self.service.perform_calculation(
            "any", {}, [], client, sender, post_gst_date
        )

        # CGST 9% + SGST 9% = 1800
        self.assertEqual(fin["tax_total"], Decimal("1800.00"))


class TestCurrencyHandling(unittest.TestCase):
    """Tests for non-INR currency handling in various services."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.service = TurnoverService(output_dir=self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_client_currency_non_inr(self):
        """Test that non-INR currency is preserved in client model."""
        client = ClientModel(id="test", name="Test Client", currency="USD")
        self.assertEqual(client.currency, "USD")

    def test_invoice_context_with_exchange_rate(self):
        """Test that exchange rate is included in context for non-INR."""
        config = InvoiceConfig.load_default()
        fee_calc = FeeCalculator(config.billing)
        service = ViewModelService(config, fee_calc)

        invoice = InvoiceModel(date="2025-01-15", line_items=[])
        client = ClientModel(
            id="test", name="Test Client", currency="USD", prefix="TST"
        )
        sender = SenderModel(id="sender", name="Test Sender")

        resolved = ResolvedInvoice(
            invoice_model=invoice,
            config_dict={
                "billing_preset": "flat_fee",
                "params": {"exchange_rate": 83.5},
                "sac": "998399",
            },
            client=client,
            sender=sender,
            bank={},
            invoice_number="INV-001",
            canonical_number="TST-01-01-250115",
            inv_date=datetime.date(2025, 1, 15),
            is_post_gst=True,
        )

        financials = {"subtotal": Decimal("1000.00"), "lines": []}
        context = service.build_context(resolved, financials)

        self.assertEqual(context["invoice"]["currency"], "USD")
        self.assertEqual(context["invoice"]["exchange_rate"], 83.5)

    def test_turnover_service_currency_conversion(self):
        """Test turnover calculation with USD invoice."""
        import yaml

        # Create a mock sidecar with USD currency
        sidecar = {
            "invoice": {"date": "2025-01-15", "number": "INV-1"},
            "financials": {"subtotal": 1000},
            "client": {"currency": "USD", "exchange_rate": 83.0},
            "sender": {"gstin": "33TEST1234G1Z5"},
        }

        with open(os.path.join(self.temp_dir, "inv1.yaml"), "w") as f:
            yaml.dump(sidecar, f)

        stats = self.service.calculate_turnover("012025")

        # Should have processed the invoice
        self.assertIsNotNone(stats)


if __name__ == "__main__":
    unittest.main()
