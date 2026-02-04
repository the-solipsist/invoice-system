# Billing Architecture Reference

This document defines the architecture, ontology, and configuration schema for the composable billing system.

## 1. Core Concepts

The system separates **Math** (Universal Formulas) from **Business Logic** (Invoice Presets) and **Engagement Details** (Contracts).

### The Three Layers

1.  **Formulas (`pricing_formulas`)**: Abstract mathematical logic (e.g., "A fixed fee plus a unit rate"). Defined in `config/billing.yaml`.
2.  **Presets (`invoice_presets`)**: Business configurations that bind a formula to specific labels and table layouts. Defined in `config/billing.yaml`.
3.  **Contracts**: The specific instance of an engagement, defining the actual numbers and overrides. Defined in `contracts/*.yaml`.

---

## 2. Ontology & Schema

### A. Global Configuration (`config/billing.yaml`)

#### 1. Pricing Formulas
Defines the calculation logic using two primitives: `flat_rate` and `unit_rate`.

| Key | Type | Description |
| :--- | :--- | :--- |
| **`components`** | `List` | Ordered calculation blocks. |
| `type` | `Enum` | `flat_rate` (Fixed Sum) \| `unit_rate` (Qty × Rate). |
| `id` | `String` | **Unique Logical ID**. Links the math result to the text template (e.g., `retainer_fee`). |
| `amount` | `String` | *(flat_rate)* Variable placeholder (e.g., `"{base_amount}"`). If omitted, sums item amounts. |
| `rate` | `String` | *(unit_rate)* Variable placeholder (e.g., `"{rate}"`). If omitted, uses item rates. |
| `min_quantity` | `String` | *(unit_rate)* Floor/Threshold. Default: `0`. |
| `max_quantity` | `String` | *(unit_rate)* Ceiling/Cap. Default: `Infinity`. |

#### 2. Invoice Presets
Defines the "Look and Feel" and default values.

| Key | Type | Description |
| :--- | :--- | :--- |
| **`formula_id`** | `String` | Reference to a Formula ID. |
| **`display_title`** | `String` | PDF Header (e.g., "Retainer Invoice"). |
| **`work_table`** | `Dict` | Configuration for the "Work Items" table. |
| `headers` | `Dict` | Keys: `col1`, `col2`, `col3`. Value: Header Text (interpolated). |
| `columns` | `List` | **Ordered Field List**. Values: `date`, `description`, `owner`, `quantity`, `status`. |
| `unit_name` | `String` | Default unit name (e.g., "hour"). |
| **`billing_table`** | `Dict` | Configuration for the "Billing" table. |
| `headers` | `Dict` | Keys: `col1`, `col2`, `col3`. |
| `row_templates` | `Dict` | Map of Component IDs to Text Templates. |
| `[id].label` | `String` | Template for Column 1. |
| `[id].details` | `String` | Template for Column 2. |
| **`defaults`** | `Dict` | Default values for variables (e.g., `unit: "hour"`). |

---

### B. Contract Definition (`contracts/*.yaml`)

| Key | Type | Description |
| :--- | :--- | :--- |
| **`contract_series`** | `Bool` | `true` = Sequence 01, 02... \| `false` = Sequence 00. |
| **`billing_preset_id`** | `String` | Reference to an Invoice Preset. |
| **`billing_terms`** | `Dict` | Values for the variables (e.g., `base_amount: 5000`). |

---

### C. Variable Context (Interpolation)

These variables are available in Formula Logic and Row Templates:

*   **`{qty}`**: Calculated billable quantity.
*   **`{rate}`**: Formatted rate.
*   **`{amount}`**: Formatted total amount.
*   **`{unit}`**: The singular unit name (e.g., "hour").
*   **`{units}`**: The pluralized unit name (e.g., "hours"). Automatically handles "1 hour" vs "2 hours".
*   **`{unit_name}`**: The raw override from `billing_terms` (useful for table headers).
*   **`{threshold}`**: The value of min/max quantity.
*   **`{date}`, `{month}`, `{year}`**: Invoice date details.
*   **`{...}`**: Any custom key from `billing_terms` OR Item Meta (for grouped items).

---

## 3. Logic & Rules

### Grouping & Summarization (Code Logic)
*   **`flat_rate`**:
    *   If `amount` is set: Creates **one row** with that amount.
    *   If `amount` is missing: Groups items by Description + Meta. Creates **multiple rows** (one per unique item).
*   **`unit_rate`**:
    *   If `rate` is set: Sums `quantity` of all items. Creates **one row**.
    *   If `rate` is missing: Groups items by Rate. Creates **multiple rows** (one per rate).

### Backward Compatibility
Legacy keys (`billing_type`, `params`) are mapped to the new architecture in two places:
1.  **Model Validation:** `billing_type` is copied to `billing_preset`.
2.  **Context Builder:** Old keys like `included_hours` and `rate_per_hour` are mapped to `threshold` and `rate`.
3.  **Config Aliases:** Legacy types (`flat_fee_milestones`) exist as explicit Presets in `billing.yaml`.

To migrate a contract fully: rename `billing_type` to `billing_preset`, rename `params` keys to match `billing_terms`, and switch to a modern Preset ID.