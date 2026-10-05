To start using the importer, instantiate it and call `get_data`:

```py
from bblocks.data_importers import GHED

ghed = GHED()
data = ghed.get_data()
```

Fetch with labels attached:

```py title="Fetch data with labels"
df_labeled = baci.get_data(include_product_labels=True, include_country_labels=True)
```

Other languages are left alone:

```bash
pip install bblocks-data-importers
```
