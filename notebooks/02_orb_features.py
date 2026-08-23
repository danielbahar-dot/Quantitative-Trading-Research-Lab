from pathlib import Path
import pandas as pd


# ============================================================
# 1. PROJECT PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

FILE_PATH = (
    PROJECT_ROOT
    / "data"
    / "MNQ_raw_cleaned_ET.csv"
)


# ============================================================
# 2. LOAD DATA
# ============================================================

df = pd.read_csv(FILE_PATH)

df["timestamp_et"] = pd.to_datetime(
    df["timestamp_et"],
    utc=True
)

df["timestamp_et"] = (
    df["timestamp_et"]
    .dt.tz_convert("America/New_York")
)

# NinjaTrader stamps 1-minute bars at bar end:
# timestamp_et = bar_end_time (bar_start_time = timestamp_et - 1 minute).

df["session_date"] = pd.to_datetime(
    df["session_date"]
).dt.date

df = (
    df
    .set_index("timestamp_et")
    .sort_index()
)


# ============================================================
# 3. OPENING RANGE PARAMETERS
# ============================================================

OR_DURATIONS = [
    5,
    10,
    15,
    20,
    30
]


# ============================================================
# 4. FUNCTION TO CALCULATE ONE OPENING RANGE
# ============================================================

def calculate_opening_range(
    session_df,
    duration_minutes
):
    """
    Calculate opening range statistics for one trading session.

    Opening range begins at 09:30 ET market time. NinjaTrader timestamps are
    bar-end labels, so the first OR bar is stamped 09:31.

    Examples:
        5 min  = 09:31 through 09:35
        10 min = 09:31 through 09:40
        15 min = 09:31 through 09:45
        20 min = 09:31 through 09:50
        30 min = 09:31 through 10:00
    """

    market_open = pd.Timestamp("09:30")
    first_bar_end = market_open + pd.Timedelta(minutes=1)
    last_bar_end = market_open + pd.Timedelta(minutes=duration_minutes)

    opening_range = session_df.between_time(
        first_bar_end.time(),
        last_bar_end.time(),
        inclusive="both"
    )

    # We require the exact number of expected 1-minute bars.
    # If even one is missing, we do not trust this OR.
    expected_times = pd.date_range(
        first_bar_end,
        periods=duration_minutes,
        freq="min"
    ).time

    if (
        len(opening_range) != duration_minutes
        or not all(opening_range.index.time == expected_times)
    ):
        return None

    or_high = opening_range["high"].max()
    or_low = opening_range["low"].min()

    or_mid = (
        or_high + or_low
    ) / 2

    or_width = (
        or_high - or_low
    )

    return {
        "or_high": or_high,
        "or_low": or_low,
        "or_mid": or_mid,
        "or_width": or_width,
        "bars_found": len(opening_range)
    }


# ============================================================
# 5. CALCULATE OR FOR EVERY SESSION
# ============================================================

results = []

for session_date, session_df in df.groupby(
    "session_date"
):

    contracts = (
        session_df["contract"]
        .dropna()
        .unique()
    )

    contract = (
        contracts[0]
        if len(contracts) == 1
        else "MULTIPLE"
    )

    for duration in OR_DURATIONS:

        result = calculate_opening_range(
            session_df,
            duration
        )

        if result is None:

            results.append({
                "session_date": session_date,
                "contract": contract,
                "or_minutes": duration,
                "valid_or": False,
                "or_high": None,
                "or_low": None,
                "or_mid": None,
                "or_width": None
            })

        else:

            results.append({
                "session_date": session_date,
                "contract": contract,
                "or_minutes": duration,
                "valid_or": True,
                "or_high": result["or_high"],
                "or_low": result["or_low"],
                "or_mid": result["or_mid"],
                "or_width": result["or_width"]
            })


# ============================================================
# 6. CREATE OPENING RANGE DATAFRAME
# ============================================================

or_df = pd.DataFrame(results)


# ============================================================
# 7. SUMMARY
# ============================================================

print("\n=== OPENING RANGE SUMMARY ===")

summary = (
    or_df
    .groupby("or_minutes")["valid_or"]
    .agg(
        valid_sessions="sum",
        total_sessions="count"
    )
)

summary["invalid_sessions"] = (
    summary["total_sessions"]
    - summary["valid_sessions"]
)

print(summary)


# ============================================================
# 8. SHOW INVALID SESSIONS
# ============================================================

print("\n=== INVALID OPENING RANGES ===")

invalid = or_df[
    or_df["valid_or"] == False
]

print(
    invalid[
        [
            "session_date",
            "contract",
            "or_minutes"
        ]
    ]
)


# ============================================================
# 9. SHOW SAMPLE SESSION
# ============================================================

SAMPLE_DATE = pd.Timestamp(
    "2024-06-21"
).date()

print("\n=== SAMPLE SESSION ===")
print(SAMPLE_DATE)

sample = or_df[
    or_df["session_date"] == SAMPLE_DATE
]

print(
    sample[
        [
            "or_minutes",
            "or_high",
            "or_low",
            "or_mid",
            "or_width",
            "valid_or"
        ]
    ]
)


# ============================================================
# 10. SAVE RESULTS
# ============================================================

OUTPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "mnq_or_levels.csv"
)

OUTPUT_PATH.parent.mkdir(
    parents=True,
    exist_ok=True
)

or_df.to_csv(
    OUTPUT_PATH,
    index=False
)

print("\nSaved OR levels to:")
print(OUTPUT_PATH)

print("\n=== OR FEATURE BUILD COMPLETE ===")
