import json, os
os.environ['LANGCHAIN_API_KEY']  = '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'
os.environ['LANGCHAIN_ENDPOINT'] = 'https://api.smith.langchain.com'
from langsmith import Client
client = Client()

runs = list(client.list_runs(project_name='invoice-extractor', is_root=True, limit=1))
latest = runs[0]
print(f"Run: {latest.id}  {str(latest.start_time)[:19]}\n")

children = list(client.list_runs(project_name='invoice-extractor', trace_id=latest.id))
children_sorted = sorted(children, key=lambda x: str(x.start_time))

for c in children_sorted:
    if c.name != 'model_extract_invoice':
        continue

    out = c.outputs or {}
    raw_out = out.get('output', out)
    raw_str = json.dumps(raw_out, default=str)

    # Classification calls
    if 'copy_type' in raw_str or 'ORIGINAL' in raw_str.upper() or 'TRIPLICATE' in raw_str.upper():
        print(f"CLASSIFY [{str(c.start_time)[:19]}]: {raw_str[:400]}")
        print()
        continue

    # Items calls
    items = None
    if isinstance(raw_out, list) and raw_out:
        first = raw_out[0]
        if isinstance(first, dict):
            items = first.get('items')
    elif isinstance(raw_out, dict):
        items = raw_out.get('items')

    if items is not None:
        print(f"ITEMS [{str(c.start_time)[:19]}]: {len(items)} items")
        for i, it in enumerate(items, 1):
            desc  = str(it.get('description') or '?')[:45]
            batch = it.get('Batch') or '?'
            code  = it.get('item_code') or '?'
            qty   = it.get('quantity') or '?'
            print(f"  {i}. {desc} | batch={batch} | code={code} | qty={qty}")
        print()
    else:
        # Non-items, non-classify — show keys
        keys = list(raw_out.keys()) if isinstance(raw_out, dict) else (
            list(raw_out[0].keys()) if isinstance(raw_out, list) and raw_out else '?')
        print(f"OTHER [{str(c.start_time)[:19]}]: keys={keys}")
        print()
