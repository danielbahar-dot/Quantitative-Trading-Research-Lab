from pathlib import Path
import pandas as pd


# ============================================================
# 1. LOCATE THE PROJECT AND DATA FILE
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

FILE_PATH = (
    PROJECT_ROOT
    / "data"
    / "MNQ_raw_cleaned_ET.csv"
)

print("\n=== FILE ===")
print(FILE_PATH)


# ============================================================
# 2. LOAD THE CSV
# ============================================================

df = pd.read_csv(FILE_PATH)

print("\n=== RAW DATA - FIRST 5 ROWS ===")
print(df.head())

print("\n=== COLUMNS ===")
print(df.columns.tolist())

print("\n=== RAW DATA TYPES ===")
print(df.dtypes)

print("\n=== RAW SHAPE ===")
print(df.shape)


# ============================================================
# 3. CONVERT timestamp_et TO A REAL DATETIME
# ============================================================

# The CSV already contains Eastern Time timestamps.
#
# Summer timestamps contain -04:00
# Winter timestamps contain -05:00
#
# We first interpret those offsets correctly by converting
# them internally to UTC, then convert back to America/New_York.
#
# This preserves the correct ET clock time and handles DST.

df["timestamp_et"] = pd.to_datetime(
    df["timestamp_et"],
    utc=True
)

df["timestamp_et"] = (
    df["timestamp_et"]
    .dt.tz_convert("America/New_York")
)


# ============================================================
# 4. USE TIMESTAMP AS THE DATAFRAME INDEX
# ============================================================

df = df.set_index("timestamp_et")

df = df.sort_index()


# ============================================================
# 5. BASIC INDEX VALIDATION
# ============================================================

print("\n=== DATETIME INDEX CHECK ===")
print(df.index[:5])

print("\nFirst timestamp:")
print(df.index.min())

print("\nLast timestamp:")
print(df.index.max())

print("\nTimezone:")
print(df.index.tz)


# ============================================================
# 6. BASIC DATA QUALITY CHECK
# ============================================================

print("\n=== DUPLICATE TIMESTAMPS ===")
print(df.index.duplicated().sum())

print("\n=== MISSING OHLC VALUES ===")
print(
    df[
        ["open", "high", "low", "close"]
    ].isna().sum()
)


# ============================================================
# 7. CONTRACTS FOUND
# ============================================================

print("\n=== CONTRACTS FOUND ===")

contracts = (
    df["contract"]
    .dropna()
    .unique()
)

for contract in contracts:
    print(contract)

print("\nNumber of contracts:")
print(len(contracts))


# ============================================================
# 8. SESSION DATE RANGE
# ============================================================

df["session_date"] = pd.to_datetime(
    df["session_date"]
).dt.date

print("\n=== SESSION DATE RANGE ===")

print("First session:")
print(df["session_date"].min())

print("Last session:")
print(df["session_date"].max())

print("Number of session dates:")
print(df["session_date"].nunique())


# ============================================================
# 9. FIND A SAMPLE SESSION WITH A 09:30 BAR
# ============================================================

rth_open_rows = df.between_time(
    "09:30",
    "09:30"
)

print("\n=== NUMBER OF 09:30 BARS ===")
print(len(rth_open_rows))


if len(rth_open_rows) == 0:

    print("\nERROR: No 09:30 ET bars were found.")

else:

    sample_timestamp = rth_open_rows.index[0]

    sample_date = sample_timestamp.date()

    print("\n=== SAMPLE DATE ===")
    print(sample_date)


    # --------------------------------------------------------
    # Get all rows belonging to this session date
    # --------------------------------------------------------

    sample_day = df[
        df["session_date"] == sample_date
    ]


    print("\n=== SAMPLE DAY CONTRACT ===")

    print(
        sample_day["contract"]
        .unique()
    )


    # --------------------------------------------------------
    # Show data around NY cash open
    # --------------------------------------------------------

    print("\n=== SAMPLE DATA 09:25 - 10:05 ET ===")

    columns_to_show = [
        "contract",
        "open",
        "high",
        "low",
        "close",
        "volume"
    ]

    print(
        sample_day
        .between_time(
            "09:25",
            "10:05"
        )[columns_to_show]
    )


# ============================================================
# 10. FINISHED
# ============================================================

print("\n=== DATA CHECK COMPLETE ===")