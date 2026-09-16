import pandas as pd
import pytest

from llm_spend.analytics import spend_by

def make_df():
    return pd.DataFrame({
        "date": pd.to_datetime([
            "2026-09-01",
            "2026-09-01",
            "2026-09-02",
            "2026-09-02",
            "2026-09-03",
            "2026-09-03",
            "2026-09-08",
            "2026-09-08",
            "2026-09-10",
            "2026-09-12",
        ]),
        "provider": [
            "anthropic",
            "openai",
            "anthropic",
            "anthropic",
            "openai",
            "anthropic",
            "openai",
            "anthropic",
            "anthropic",
            "openai",
        ],
        "org_unit": [
            "research",
            "support",
            "research",
            "platform",
            "support",
            "research",
            "platform",
            "support",
            "research",
            "platform",
        ],
        "model": [
            "claude-opus-5",
            "gpt-5",
            "claude-opus-5",
            "claude-sonnet-5",
            "gpt-5",
            "claude-opus-5",
            "gpt-5",
            "claude-sonnet-5",
            "claude-opus-5",
            "gpt-5",
        ],
        "line_item": ["tokens"] * 10,
        "cost_usd": [
            10.00,
            3.00,
            5.00,
            2.00,
            4.00,
            8.00,
            6.00,
            1.50,
            12.50,
            3.00,
        ],
    })

def test_full_range_groups_sorts_and_shares():

    result = spend_by(make_df(), "org_unit", "2026-09-01", "2026-09-12")

    # Extract all elements of the group column as a list and check if it is sorted
    assert result["group"].tolist() == ["research", "platform", "support"]

    # Check whether the total calculated spend correct. This safeguards against date filtering, grouping, summation errors
    assert result["cost_usd"].sum() == pytest.approx(55.0)

    # Check whether the sum of "share" values sum to 1. They should always sum to 1.
    assert result["share"].sum() == pytest.approx(1.0)


def test_narrower_range_changes_total():

    result = spend_by(make_df(), "org_unit", "2026-09-01", "2026-09-03")

    # Check whether df["date"] >= start & df["date"] <= end
    assert result["cost_usd"].sum() == pytest.approx(32.0)

def test_missing_column_raises():

    df = make_df().drop(columns=["cost_usd"])

    with pytest.raises(ValueError):
        spend_by(df,"org_unit", "2026-09-01", "2026-09-12")