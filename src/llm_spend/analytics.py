"""The analytics service that calculates meaningful insights from the raw data returned by APIs"""

from llm_spend.schema import COST_COLUMNS
import pandas as pd

def spend_by(df, group_by, start, end):
    start = pd.to_datetime(start)
    end = pd.to_datetime(end)
    missing = set(COST_COLUMNS) - set(df.columns)
    if missing: 
        raise ValueError(f"missing columns: {sorted(missing)}")

    if group_by not in df.columns:
        raise ValueError(f"'{group_by}' is not a valid column")

    df_filtered_by_date = df[(df["date"] >= start) & (df["date"] <= end)]
    
    df_grouped = (
        df_filtered_by_date
        .groupby(group_by)["cost_usd"]
        .sum()
        .reset_index()
        .sort_values(by="cost_usd", ascending=False)  # Sort largest to smallest
        .reset_index(drop=True)  # Clean up and re-sort the row index after sorting
        .rename(columns={group_by: "group"})
    )

    total = df_grouped["cost_usd"].sum()

    if total <= 0:
        df_grouped["share"] = 0.0

    else:
        df_grouped["share"] = df_grouped["cost_usd"] / total
    
    return df_grouped