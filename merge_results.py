"""
STEP 4 — Write results back into your original companies table.

Reads:
  companies.csv       your original universe (all columns preserved)
  snapshot.csv        price / volume / percent_change  (from bulk fetch)
  summary.csv         historical coverage per symbol   (from bulk fetch)

Writes:
  companies_updated.csv    original table with price, volume, percentage,
                           historical data columns filled in
  companies_updated.xlsx   same thing as an Excel file

Run:  python merge_results.py
(Requires: pip install openpyxl   — for the Excel output)
"""

import os
import sys
import pandas as pd

COMPANIES_FILE = "companies.csv"   # change if you kept the original filename


def read_table(path):
    """Read csv/tsv with auto delimiter detection."""
    with open(path, encoding="utf-8-sig") as f:
        sample = f.read(4096)
    delim = "\t" if sample.count("\t") > sample.count(",") else ","
    return pd.read_csv(path, delimiter=delim, dtype=str)


def main():
    for f in (COMPANIES_FILE, "snapshot.csv", "summary.csv"):
        if not os.path.exists(f):
            sys.exit(f"{f} not found in this folder.")

    companies = read_table(COMPANIES_FILE)
    snapshot = pd.read_csv("snapshot.csv")
    summary = pd.read_csv("summary.csv")

    # Normalise the join key
    companies["_sym"] = companies["Symbol"].str.strip()
    snapshot["_sym"] = snapshot["symbol"].str.strip()
    summary["_sym"] = summary["symbol"].str.strip()

    snap_map = snapshot.set_index("_sym")[["price", "volume", "percent_change"]]
    summ = summary.set_index("_sym")
    summ["historical"] = summ["first_date"].astype(str) + " to " + summ["last_date"].astype(str)

    # Fill the existing columns of the original table
    companies["price"] = companies["_sym"].map(snap_map["price"])
    companies["volume"] = companies["_sym"].map(snap_map["volume"])
    companies["percentage"] = companies["_sym"].map(snap_map["percent_change"])
    companies["historical data"] = companies["_sym"].map(summ["historical"])

    # Bonus column: number of trading days of history downloaded
    companies["days_of_data"] = companies["_sym"].map(summ["rows"])

    companies = companies.drop(columns=["_sym"])

    companies.to_csv("companies_updated.csv", index=False)
    try:
        companies.to_excel("companies_updated.xlsx", index=False)
        excel_note = "and companies_updated.xlsx"
    except ImportError:
        excel_note = "(install openpyxl for the Excel version: pip install openpyxl)"

    filled = companies["price"].notna().sum()
    hist = companies["historical data"].notna().sum()
    total = len(companies)
    print(f"Total companies:            {total}")
    print(f"Snapshot filled (price):    {filled}  |  missing: {total - filled}")
    print(f"Historical range filled:    {hist}  |  missing: {total - hist}")
    print(f"\nWritten: companies_updated.csv {excel_note}")

    missing = companies.loc[companies["historical data"].isna(), "Symbol"].tolist()
    if missing:
        print(f"\nSymbols still without historical data ({len(missing)}):")
        print(", ".join(missing))
        print("\nRe-run fetch_historical_bulk.py to retry errored symbols, "
              "then run this merge again.")


if __name__ == "__main__":
    main()