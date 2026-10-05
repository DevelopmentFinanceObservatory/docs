```python
from oda_reader import bulk_download_dac1

for chunk in bulk_download_dac1(as_iterator=True):
    # process each chunk here
    ...
```

!!! warning "Heads up"
DAC1 is a zipped CSV, so `as_iterator=True` leaves peak memory unchanged. It reads the whole
file first and hands it back in slices, the same profile as
`download_crs_file(as_iterator=True)`. See the caveat under
[Processing a Year-Specific File in Chunks](#processing-a-year-specific-file-in-chunks). Only
what you accumulate chunk-by-chunk afterward is bounded.

## DAC2b Bulk Download

OECD publishes the full DAC2b table as one zipped CSV.
