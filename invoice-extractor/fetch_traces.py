"""Fetch and analyse latest LangSmith trace for invoice-extractor."""
import json, os
os.environ["LANGCHAIN_API_KEY"]  = "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"
os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"

from langsmith import Client
client = Client()
PROJECT = "invoice-extractor"

# ── Get latest run ────────────────────────────────────────────────
runs = list(client.list_runs(project_name=PROJECT, is_root=True, limit=3))
latest = runs[0]
print(f"Latest run: {latest.name}  start={str(latest.start_time)[:19]}  status={latest.status}")
print(f"Run ID: {latest.id}\n")

# ── Get all spans in this trace ───────────────────────────────────
children = list(client.list_runs(project_name=PROJECT, trace_id=latest.id))
children_sorted = sorted(children, key=lambda x: str(x.start_time))
print(f"Total spans: {len(children_sorted)}\n")

def safe_items(out):
    """Extract items list from output regardless of nesting."""
    if not out:
        return None
    if isinstance(out, list):
        return out
    if isinstance(out, dict):
        # Direct items key
        if "items" in out:
            return out["items"]
        # Nested under 'output'
        nested = out.get("output")
        if isinstance(nested, dict) and "items" in nested:
            return nested["items"]
        if isinstance(nested, list):
            return nested
    return None

print("=" * 70)
print("SPAN SUMMARY")
print("=" * 70)
for c in children_sorted:
    indent = "  " if c.parent_run_id == latest.id else "    "
    out = c.outputs or {}
    items = safe_items(out)
    item_count = f" → {len(items)} items" if items is not None else ""
    err = f" ERR={c.error[:80]}" if c.error else ""
    print(f"{indent}{c.name} | {c.run_type} | {c.status}{item_count}{err}")

# ── Focus on model_extract_invoice spans ─────────────────────────
print("\n" + "=" * 70)
print("MODEL EXTRACTION SPANS (items detail)")
print("=" * 70)
for c in children_sorted:
    if "model_extract" not in (c.name or ""):
        continue
    out = c.outputs or {}
    items = safe_items(out)
    start = str(c.start_time)[:19]
    print(f"\n[{start}] {c.name}  status={c.status}")
    if c.error:
        print(f"  ERROR: {c.error[:200]}")
    if items is not None:
        print(f"  Items extracted: {len(items)}")
        for i, item in enumerate(items, 1):
            desc  = str(item.get("description") or "?")[:45]
            batch = item.get("Batch") or "?"
            code  = item.get("item_code") or "?"
            qty   = item.get("quantity") or "?"
            hsn   = item.get("hsn_sac") or "?"
            tv    = item.get("taxable_value") or "?"
            cgst  = item.get("cgst_amount") or "?"
            print(f"    {i}. {desc} | batch={batch} | code={code} | qty={qty} | hsn={hsn} | taxable={tv} | cgst={cgst}")
    else:
        # Print output keys for non-items passes
        out_keys = list(out.keys()) if isinstance(out, dict) else type(out).__name__
        print(f"  Output keys: {out_keys}")
        # Print totals if present
        for key in ["invoice_amount","total_cgst_amount","total_sgst_amount","total_gst_amount","round_off","total_quantity"]:
            val = out.get(key) if isinstance(out, dict) else None
            if val is not None:
                print(f"  {key}: {val}")

# ── Check copy classification pass ───────────────────────────────
print("\n" + "=" * 70)
print("PAGE CLASSIFICATION SPANS")
print("=" * 70)
found_classify = False
for c in children_sorted:
    if c.name and "model_extract" in c.name:
        inp = c.inputs or {}
        # Look for the copy_type classification call
        msgs = inp.get("messages") or []
        for m in msgs:
            if isinstance(m, dict):
                content = m.get("content") or ""
                if isinstance(content, str) and "copy_type" in content.lower():
                    out = c.outputs or {}
                    items = safe_items(out)
                    print(f"  Classification call found: {c.name}")
                    print(f"  Output: {json.dumps(out, default=str)[:300]}")
                    found_classify = True
                    break
if not found_classify:
    print("  No page classification spans found (may not have run yet)")

# ── Look at multipage span inputs/outputs ────────────────────────
print("\n" + "=" * 70)
print("MULTIPAGE SPAN DETAIL")
print("=" * 70)
for c in children_sorted:
    if c.name == "model_extract_multipage":
        out = c.outputs or {}
        if isinstance(out, dict):
            items = safe_items(out)
            print(f"  Final items count: {len(items) if items else 0}")
            print(f"  invoice_amount: {out.get('invoice_amount')}")
            print(f"  total_quantity: {out.get('total_quantity')}")
            print(f"  round_off: {out.get('round_off')}")
            print(f"  total_cgst_amount: {out.get('total_cgst_amount')}")
            print(f"  total_sgst_amount: {out.get('total_sgst_amount')}")
            if items:
                print(f"  Items:")
                for i, item in enumerate(items, 1):
                    desc  = str(item.get("description") or "?")[:45]
                    batch = item.get("Batch") or "?"
                    code  = item.get("item_code") or "?"
                    print(f"    {i}. {desc} | batch={batch} | code={code}")
        break
