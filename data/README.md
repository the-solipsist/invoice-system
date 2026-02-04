# Sample Data Notice

All data in this repository is **synthetic and for demonstration purposes only**.

## What This Means

- **Business Names**: Fictional companies (e.g., "Sample Corporation Ltd.")
- **Tax IDs**: Dummy GSTIN/PAN numbers (e.g., "07ABCDE1234F1Z5")
- **Addresses**: Placeholder locations
- **Bank Details**: Sample account numbers (not real)
- **Invoice Data**: Synthetic billing data

## Using Real Data

To use this system with real business data:

1. Replace files in `data/profiles/` with your actual:
   - Business profile (`self.yaml`)
   - Client list (`clients.yaml`)
   - Bank accounts (`banks.yaml`)

2. Add your contracts to `data/contracts/`

3. Create invoices in `data/invoices/`

4. Replace placeholder assets in `data/assets/`:
   - `logo.svg` - Your business logo
   - `signature.svg` - Your signature image

## Data Privacy

**Never commit real business data to a public repository.**

If you fork or clone this repository:
- Keep your private data in a separate private repository
- Or ensure your fork is private
- Add `data/` to `.gitignore` if using real data

## Template Structure

The sample data demonstrates the expected YAML structure. Use these as templates for your own data files.
