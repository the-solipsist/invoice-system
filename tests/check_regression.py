import os
import sys
import shutil
import glob
import json
import argparse
import difflib
import yaml
from pathlib import Path
from unittest.mock import patch
import tempfile

# Add project root to path
ROOT = Path(__file__).parent.parent
sys.path.append(str(ROOT))

from app.invoice_controller import generate, config
from app.modules.models import InvoiceRegistry

def get_yaml_diff(old_str, new_str, filename):
    return list(difflib.unified_diff(
        old_str.splitlines(keepends=True),
        new_str.splitlines(keepends=True),
        fromfile=f"old/{filename}",
        tofile=f"new/{filename}"
    ))

def check_regression():
    parser = argparse.ArgumentParser(description="Full Invoice Regression Check")
    parser.add_argument("filter", nargs="?", help="Optional filter for filenames")
    args = parser.parse_args()

    # Paths
    data_dir = ROOT / "data"
    invoices_dir = data_dir / "invoices"
    output_dir = ROOT / "output"
    registry_path = data_dir / "invoice_registry.json"

    # 1. Load current Registry
    registry = InvoiceRegistry.load(registry_path)
    
    print("=== 1. Generating to Temporary Directory ===")
    
    source_files = sorted(list(invoices_dir.glob("*.yaml")))
    
    # Apply Filter
    if args.filter:
        source_files = [f for f in source_files if args.filter in f.name]
        print(f"Filtered source files: {len(source_files)} matching '{args.filter}'")
    
    errors = []
    checked_count = 0

    with tempfile.TemporaryDirectory() as temp_out:
        temp_out_path = Path(temp_out)
        
        with patch('app.invoice_controller.config.output_dir', new=temp_out_path), \
             patch('app.invoice_controller.HTML'):
            
            for source in source_files:
                try:
                    # Capture printed output to avoid cluttering
                    with open(os.devnull, 'w') as f, patch('sys.stdout', new=f):
                        generate(str(source), force=True)
                except Exception as e:
                    print(f"FAILED to generate {source.name}: {e}")

        print("\n=== 2. Comparing YAML Sidecars ===")
        
        for source_path in source_files:
            filename = source_path.name
            if filename not in registry.entries:
                continue
                
            entry = registry.entries[filename]
            safe_id = entry.canonical_id.replace("/", "_")
            
            old_path = output_dir / f"{safe_id}.yaml"
            new_path = temp_out_path / f"{safe_id}.yaml"
            
            if not old_path.exists():
                print(f"[SKIP] No historical sidecar for {filename}")
                continue
            
            if not new_path.exists():
                errors.append(f"{filename}: Missing new sidecar")
                print(f"[FAIL] {filename}: Missing new sidecar")
                continue

            checked_count += 1
            
            with open(old_path, 'r') as f:
                old_yaml_str = f.read()
                old_data = yaml.safe_load(old_yaml_str)
            with open(new_path, 'r') as f:
                new_yaml_str = f.read()
                new_data = yaml.safe_load(new_yaml_str)

            # Compare Data Objects
            if old_data != new_data:
                diff = get_yaml_diff(old_yaml_str, new_yaml_str, f"{safe_id}.yaml")
                errors.append(f"{filename}: Content mismatch")
                print(f"[FAIL] {filename}: YAML content changed")
                print("".join(diff))
            else:
                # print(f"[PASS] {filename}")
                pass

    print(f"\nChecked {checked_count} invoices.")
    if not errors:
        print("RESULT: ALL OUTPUTS MATCH EXACTLY. No changes found.")
        return True
    else:
        print(f"RESULT: FOUND {len(errors)} CHANGES.")
        return False

if __name__ == "__main__":
    success = check_regression()
    if not success:
        sys.exit(1)