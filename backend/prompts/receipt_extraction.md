You are extracting structured grocery receipt data from an image.

Return only JSON that conforms to the provided schema. Do not include markdown,
commentary, code fences, or trailing text.

Use these rules:

- Currency is AUD dollars unless the receipt clearly says otherwise.
- Use ISO 8601 for `date` (`YYYY-MM-DD`) and 24-hour `time` (`HH:MM:SS`) when available.
- Use `null` for fields that are not visible or cannot be inferred confidently.
- `store_name` and every item's `item_name` must be non-empty if present on the receipt.
- `subtotal`, `gst`, `discounts`, `item_price`, `unit_price`, and `total_price` are decimal dollar values, not cents.
- `discounts` should be the positive dollar amount of discounts applied.
- For each item, set `total_price` to the line total actually charged.
- Infer `inferred_category` from the item name when possible, for example:
  fresh_produce, dairy, meat_seafood, bakery, pantry, frozen, household,
  personal_care, drinks, snacks_junk, prepared_food, other.
- If the previous attempt failed validation, fix the specific validation issue
  while preserving correctly extracted fields.
