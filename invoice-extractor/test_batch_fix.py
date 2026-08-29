"""Test the batch ambiguity correction against the real invoice scenario."""
from ocr_corrector import flag_ambiguous_batches, _batch_alternatives

# Test 1: _batch_alternatives generates correct candidates
alts = _batch_alternatives('ABVG0002')
assert 'ABWG0002' in alts, f"Expected ABWG0002 in alternatives, got {alts}"
print(f"PASS  alternatives('ABVG0002') = {alts}")

alts2 = _batch_alternatives('ENV261280A')
assert 'EMV261280A' in alts2, f"Expected EMV261280A, got {alts2}"
print(f"PASS  alternatives('ENV261280A') = {alts2}")

alts3 = _batch_alternatives('RFJ826001')
assert 'RF1826001' in alts3, f"Expected RF1826001, got {alts3}"
print(f"PASS  alternatives('RFJ826001') = {alts3}")

# Test 2: Same-invoice cross-correction
# ABWG0002 appears on item 3 correctly (no ambiguous chars? W is ambiguous)
# ABVG0002 appears on item 7 (V confused for W)
# Since both W and V are ambiguous, let's simulate: item 3 extracted first
# with ABWG0002, item 7 extracted later with ABVG0002.
# The two-pass registry should catch this.
items = [
    {'description': 'SHELCAL HD 12 TABS', 'Batch': 'GAZG0007'},   # no ambiguity
    {'description': 'SHELCAL HD TAB',      'Batch': 'DMB526019A'}, # no ambiguity
    {'description': 'STALIX DM TAB',       'Batch': 'ABWG0002'},   # W is ambiguous but appears first
    {'description': 'TORPANEL 4 TAB',      'Batch': 'ABVG0002'},   # WRONG: V should be W
]

result = flag_ambiguous_batches(items)

# Item 3 (ABWG0002) was seen first — added to full_registry
# Item 4 (ABVG0002) should be corrected to ABWG0002 via registry
torpanel = result[3]
assert torpanel['Batch'] == 'ABWG0002', \
    f"FAIL: TORPANEL batch should be ABWG0002, got {torpanel['Batch']}"
print(f"PASS  ABVG0002 -> ABWG0002 via cross-item registry correction")

# Test 3: Truly isolated ambiguous batch with no match → flagged for review
items2 = [
    {'description': 'SOME DRUG', 'Batch': 'XYZ1234'},   # no ambiguity
    {'description': 'OTHER DRUG', 'Batch': 'ABVG9999'},  # V is ambiguous, no matching ABWG9999
]
result2 = flag_ambiguous_batches(items2)
other = result2[1]
assert other.get('_batch_ambiguous') is True, \
    f"FAIL: isolated ambiguous batch should be flagged"
assert 'ABWG9999' in other.get('_batch_alternatives', []), \
    f"FAIL: alternatives should contain ABWG9999"
print(f"PASS  Isolated ABVG9999 flagged with alternatives: {other['_batch_alternatives']}")

# Test 4: Non-ambiguous batches are untouched and not flagged
items3 = [
    {'description': 'DRUG A', 'Batch': 'CPG7M002'},
    {'description': 'DRUG B', 'Batch': 'GAXG0008'},
    {'description': 'DRUG C', 'Batch': '2F79N007'},
]
result3 = flag_ambiguous_batches(items3)
for item in result3:
    assert item.get('_batch_ambiguous') is None, \
        f"FAIL: {item['Batch']} should not be flagged"
print(f"PASS  Clean batches CPG7M002, GAXG0008, 2F79N007 untouched")

print()
print("ALL TESTS PASSED")
