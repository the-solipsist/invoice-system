# AGENTS.md

This file provides context for AI agents working on this invoice generation system codebase.

## Project Overview

This is a Python-based invoice generation system that produces PDF invoices from YAML data files. It uses a composable billing engine that separates mathematical logic from business configurations and client-specific terms.

**Core Tech Stack:** Python 3 (managed via `uv`), PyYAML, Jinja2, WeasyPrint

## Directory Structure

```text
.
├── config/
│   └── billing.yaml       # Universal Formulas & Business Presets
├── data/                  # Data Layer
│   ├── profiles/          # Entities (clients.yaml, self.yaml, banks.yaml)
│   ├── contracts/         # Engagement terms (contract_series, billing_preset)
│   └── invoices/          # Instance data (line_items, date)
├── app/                   # Logic Layer
│   ├── modules/           # models.py, fee_calculator.py (Domain)
│   ├── services/          # context_builder.py, financials_service.py, 
│   │                      # view_model_service.py, hledger_service.py
│   └── templates/         # invoice.html, invoice.css
├── output/                # Generated PDFs & Sidecar YAMLs
├── generate_invoice.py    # CLI Controller & Orchestrator
├── tests/                 # Unit tests & Regression tools
└── docs/                  # Technical documentation & Compliance
    ├── BILLING_ARCHITECTURE.md  # Billing system schema
    ├── LEGACY_FIELDS.md         # Legacy field mappings
    └── gst/                     # GST/GSTR-1 compliance docs
```

## Architecture Principles

### 1. Three-Tier Configuration Model

The billing system uses three layers of abstraction:

1. **Universal Formulas** (`config/billing.yaml`): Abstract math blocks using `flat_rate` and `unit_rate` primitives
2. **Invoice Presets** (`config/billing.yaml`): Binds formulas to presentation rules (table headers, row labels)
3. **Engagement Terms** (`data/contracts/*.yaml` or `data/invoices/*.yaml`): Client-specific values (rate, threshold, label, unit_name)

For detailed schema, see [docs/BILLING_ARCHITECTURE.md](docs/BILLING_ARCHITECTURE.md)

### 2. Layered Assembly Pipeline

Invoice generation follows this strict sequence:
1. **Data Assembly (`ContextBuilder`)**: Merges YAMLs, resolves profiles, calculates sequence IDs → `ResolvedInvoice`
2. **Business Logic (`FinancialsService`)**: Orchestrates math engine and applies tax rules (GST/LUT)
3. **Presentation Mapping (`ViewModelService`)**: Maps business objects to template context
4. **Orchestration (`InvoiceController`)**: Coordinates services and handles file I/O

### 3. Domain vs. Application Layer Separation

**`app/modules/` (Domain - "What"):**
- Pydantic models defining data structures (`models.py`, `config_models.py`)
- Pure logic without side effects (`FeeCalculator` - math only)

**`app/services/` (Application - "How"):**
- I/O, orchestration, state management
- `ContextBuilder`: Assembles data from YAMLs
- `FinancialsService`: Applies business rules (GST, currency)
- `NumberingService`: Manages canonical file naming
- `ViewModelService`: Prepares data for Jinja2 templates

## Code Conventions

### When Fixing Issues

**Rule: YAML > Code Workarounds**
- Fix data and configuration in YAML files (`data/contracts`, `config/billing.yaml`) rather than adding edge-case logic in Python code
- Code should remain generic and robust; business logic variations belong in data/configuration

**Rule: Legacy Cleanup**
- Remove deprecated fields (e.g., `billing_type`, `project_title`) from invoice YAMLs
- Keep files compliant with the current schema
- Note: `unit_name` at root was removed (2026-02-04) - now properly nested in `billing_terms`
- See [docs/LEGACY_FIELDS.md](docs/LEGACY_FIELDS.md) for complete catalog

### When Adding Features

1. Check if the feature can be implemented via configuration changes in `config/billing.yaml` before modifying code
2. Follow the existing layered architecture - don't skip layers
3. Add Pydantic models for new data structures
4. Keep the FeeCalculator as pure math logic

### When Editing Code

1. Use existing libraries and patterns (check `requirements.txt`)
2. Mimic code style from existing files in the same directory
3. Don't add comments unless explicitly asked
4. Follow the established import patterns and naming conventions

## Testing

**Unit Tests:**
```bash
uv run python tests/test_suite.py
```

**Financial Regression Check (Dry Run):**
```bash
uv run python tests/check_regression.py [filter]
```

## Operational Rules

### Standalone Invoices
- Use `contract_series: false` in the invoice YAML for one-off projects
- This generates `00` invoice sequence in the ID (e.g., `BZ-01-00-...`)

### Billing Labels
- Keep global defaults in `config/billing.yaml` simple (e.g., "Fee")
- Override with `billing_terms: { label: "Article" }` in specific invoice or contract YAML
- Avoid coupling "Description" to "Label" by default

### Historical Stability
- Prefer explicit `work_sequence_number` in historical invoices over auto-numbering
- Prevents race conditions where file processing order could alter historical IDs

## Numbering Logic

### ID Types
- **Invoice Number (Face ID)**: The number printed on the PDF. Preserves historical IDs from the registry
- **Canonical ID (File ID)**: `{PREFIX}-{WORK_SEQ}-{INV_SEQ}-{DATE}` where `INV_SEQ` is `00` for standalone projects or `01`, `02`... for ongoing series

### Stability
Rank calculation uses a **Stable Sort** (Date + Filename) to ensure IDs remain deterministic across generations

## Tax Logic

**Effective Date:** GST applies only to invoices dated **on or after April 16, 2024**

**Rules:**
- **Export (`overseas`)**: 0% Tax + LUT Notification
- **Intra-State**: CGST (9%) + SGST (9%)
- **Inter-State**: IGST (18%)

For GSTR-1 filing details, see [docs/gst/GSTR1_VALIDATION_RULES.md](docs/gst/GSTR1_VALIDATION_RULES.md)

## Usage Examples

**Generate Invoice:**
```bash
uv run generate_invoice.py data/invoices/2026-01-meta.yaml
```

**Smart Detection (processes new invoices only):**
```bash
uv run generate_invoice.py
```

**Force regenerate all invoices:**
```bash
uv run generate_invoice.py --force
```

**Generate with hledger journal:**
```bash
uv run generate_invoice.py data/invoices/your_invoice.yaml --hledger
```

**Log payment receipt:**
```bash
uv run generate_invoice.py --receipt
```

## Key Files to Understand

- `app/invoice_controller.py:62-127` - Main orchestration flow
- `app/services/context_builder.py:36-86` - Data assembly logic
- `app/modules/fee_calculator.py:251-314` - Math engine
- `app/services/financials_service.py:27-69` - Tax and currency logic
- `app/modules/models.py:89-163` - InvoiceModel with validation
- `config/billing.yaml` - All billing formulas and presets

## Version Control

This repo uses **jj** (Jujutsu VCS) in `jj git --no-colocate` mode.

**Common Commands:**
```bash
# View recent history
jj log -s

# Create new change
jj new

# Describe change
jj describe -m "message"

# Show diff
jj diff

# Move to specific change
jj edit <change-id>
```

For more on jj workflow, see: https://github.com/martinvonz/jj

## Documentation

This AGENTS.md file contains essential context for working on the codebase. For detailed documentation:

- **Billing System**: [docs/BILLING_ARCHITECTURE.md](docs/BILLING_ARCHITECTURE.md) - Detailed billing ontology and schema
- **Legacy Fields**: [docs/LEGACY_FIELDS.md](docs/LEGACY_FIELDS.md) - Catalog of deprecated field mappings
- **GST Compliance**: [docs/gst/](docs/gst/) - GSTR-1 validation rules and evidence logs
- **User Guide**: [README.md](README.md) - Quick start and feature overview
