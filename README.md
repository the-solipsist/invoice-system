# Invoice Generation System

⚠️ **PERSONAL PROJECT - NOT FOR GENERAL USE**

This is a personal invoice generation system built for my own use. It is shared publicly for reference and educational purposes only. This is not intended to be a general-purpose tool for others.

## Overview

A Python-based invoice generation system that produces PDF invoices from YAML data files. Features include:

- **Composable Billing Engine**: Separates mathematical logic from business configurations
- **Multi-Jurisdiction Support**: Configurable for different tax systems (demonstrated with GST)
- **Smart Numbering**: Auto-increments sequence numbers with support for one-off projects
- **Export Handling**: Letter of Undertaking (LUT) support for zero-rated exports
- **Accounting Integration**: Optional hledger journal generation

## Architecture

The system follows a three-tier configuration model:

1. **Universal Formulas** (`config/billing.yaml`): Abstract math primitives (`flat_rate`, `unit_rate`)
2. **Invoice Presets** (`config/billing.yaml`): Business configurations binding formulas to presentation
3. **Engagement Terms** (`data/contracts/*.yaml`, `data/invoices/*.yaml`): Client-specific values

### Layered Pipeline

1. **Data Assembly** (`ContextBuilder`): Merges YAMLs, resolves profiles, calculates IDs
2. **Business Logic** (`FinancialsService`): Applies tax rules and currency logic
3. **Presentation** (`ViewModelService`): Maps to Jinja2 template context
4. **Output** (`InvoiceController`): Generates PDFs and sidecar YAMLs

## Quick Start

### Prerequisites
- Python 3.10+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Installation
```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/invoice-system.git
cd invoice-system

# Install dependencies
uv pip install -r requirements.txt
# or: pip install -r requirements.txt
```

### Running with Sample Data

The repository includes synthetic sample data for demonstration:

```bash
# Generate a sample invoice
uv run generate_invoice.py data/invoices/2024-05_sample_retainer_01.yaml

# Run all tests
uv run python tests/test_suite.py
```

### Using Your Own Data

1. **Update profiles**: Edit `data/profiles/` with your business and client information
2. **Create contracts**: Add contract YAMLs to `data/contracts/`
3. **Generate invoices**: Create invoice YAMLs referencing contract IDs

See `data/yaml_templates/` for examples.

## Documentation

- **[AGENTS.md](AGENTS.md)** - Detailed architecture and development guidelines
- **[docs/BILLING_ARCHITECTURE.md](docs/BILLING_ARCHITECTURE.md)** - Billing system schema

## Important Notes

⚠️ **This is a personal project with the following characteristics:**

- Designed for my specific workflow and requirements
- May contain assumptions specific to my business context
- Not actively maintained as a general-purpose tool
- Sample data included is entirely synthetic

**If you want to use this:**
1. Review all code to understand assumptions
2. Replace all sample data in `data/` with your own
3. Update configuration in `config/` for your jurisdiction
4. Test thoroughly before using for actual business

## License

[Add your license here - e.g., MIT, Apache-2.0, or proprietary]

## Tech Stack

- **Python 3.10+** with type hints
- **Pydantic** for data validation
- **Jinja2** for templating
- **WeasyPrint** for PDF generation
- **PyYAML** for data files

## Directory Structure

```
.
├── app/                    # Application code
│   ├── modules/           # Domain models and pure logic
│   ├── services/          # Application services
│   └── templates/         # HTML/CSS for PDF
├── config/                # Configuration files
├── data/                  # Data files (sample data included)
│   ├── profiles/         # Business, client, bank profiles
│   ├── contracts/        # Contract terms
│   └── invoices/         # Invoice data
├── docs/                  # Documentation
├── tests/                 # Test suite
└── generate_invoice.py    # Main entry point
```

## Version Control

This repository is designed to work with [jj](https://github.com/martinvonz/jj) (Jujutsu VCS) but is compatible with standard git.

## Disclaimer

This software is provided as-is for educational and reference purposes. The author makes no warranties about its fitness for any particular purpose. Use at your own risk.
