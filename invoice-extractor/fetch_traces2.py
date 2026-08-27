"""Dump raw output structure of the multipage span and its children."""
import json, os
os.environ["LANGCHAIN_API_KEY"]  = "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"
os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"

from langsmith import Client
client = Client()
PROJECT = "invoice-extractor"

runs = list(client.list_runs(project_name=PROJECT, is_root=True, limit=1))
latest = runs[0]
print(f"Latest: {latest.name}  {str(latest.start_time)[:19]}  {latest.status}\n")

children = list(client.list_runs(project_name=PROJECT, trace_id=latest.id))
children_sorted = sorted(children, key=lambda x: str(x.start_time))

# Find model_extract_invoice spans
for c in children_sorted:
    if c.name == "model_extract_invoice":
        print(f"\n{'='*60}")
        print(f"model_extract_invoice  start={str(c.start_time)[:19]}")
        print(f"  outputs type: {type(c.outputs)}")
        out = c.outputs
        if out is not None:
            raw = json.dumps(out, default=str)
            print(f"  outputs (first 1200 chars):\n{raw[:1200]}")

# Find model_extract_multipage
print(f"\n{'='*60}")
print("model_extract_multipage outputs:")
for c in children_sorted:
    if c.name == "model_extract_multipage":
        out = c.outputs
        if out is not None:
            raw = json.dumps(out, default=str)
            print(f"  type={type(out)}  keys={list(out.keys()) if isinstance(out, dict) else 'list'}")
            print(f"  first 2000 chars:\n{raw[:2000]}")
        break
