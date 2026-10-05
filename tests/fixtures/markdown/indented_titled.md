`fetch_allocations_holdings()` returns four columns: `entity`, `indicator` (`holdings` or
`allocations`), `value`, and `date`. Called with no argument it returns the latest month
available. Pass a specific month as a `(year, month)` tuple.

!!! warning "Heads up"

    SDR and WEO order their date arguments differently. `sdr.fetch_allocations_holdings((2021, 4))` takes `(year, month)` as integers, for April 2021. `weo.fetch_data(("April", 2021))` takes `(month, year)`, with the month as a name. Check which module you're calling before passing a tuple.

## What just happened

1. `weo.fetch_data()` picked whichever source, API or bulk archive, serves the requested release.
