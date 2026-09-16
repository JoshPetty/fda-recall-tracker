import json
import os
from datetime import datetime, timedelta

from adapters.openfda_food import OpenFDAFoodAdapter

adapter = OpenFDAFoodAdapter()
records = adapter.fetch(since=datetime.now() - timedelta(days=30))
print(f"fetched {len(records)} records")

os.makedirs("tests/fixtures/openfda_food", exist_ok=True)
for r in records[:15]:
    path = f"tests/fixtures/openfda_food/{r.source_id}.json"
    with open(path, "w") as f:
        json.dump(r.payload, f, indent=2)
    print(f"wrote {path}")