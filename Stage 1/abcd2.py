import pandas as pd
import numpy as np

# Load merged dataset
df = pd.read_csv("merged_dataset.csv")

# Columns used to generate the target score
score_cols = [
    "market_value_in_eur",
    "highest_market_value_in_eur",
    "total_goals",
    "total_assists",
    "total_minutes",
    "international_caps",
    "value_growth"
]

# Convert selected columns to numeric
for col in score_cols:
    df[col] = pd.to_numeric(df[col], errors="coerce")

# Fill missing values with median
for col in score_cols:
    df[col] = df[col].fillna(df[col].median())

# Rank-based normalization so all columns are comparable
def pct_rank(series):
    return series.rank(pct=True, method="average")

# Create a composite score using existing columns
df["_future_potential_raw"] = (
    0.25 * pct_rank(df["market_value_in_eur"]) +
    0.20 * pct_rank(df["highest_market_value_in_eur"]) +
    0.15 * pct_rank(df["total_goals"]) +
    0.15 * pct_rank(df["total_assists"]) +
    0.10 * pct_rank(df["total_minutes"]) +
    0.10 * pct_rank(df["international_caps"]) +
    0.05 * pct_rank(df["value_growth"])
)

# Scale raw score to 0-100
raw_min = df["_future_potential_raw"].min()
raw_max = df["_future_potential_raw"].max()

df["Player Future Potential Score"] = (
    ((df["_future_potential_raw"] - raw_min) / (raw_max - raw_min)) * 100
).round().astype(int)

# Create categorical rating from the score
df["Player Future Potential Rating"] = pd.cut(
    df["Player Future Potential Score"],
    bins=[-1, 39, 69, 100],
    labels=["Underperforming", "Average", "Outperforming"]
)

# Remove temporary column
df.drop(columns=["_future_potential_raw"], inplace=True)

# Save final dataset
df.to_csv("merged_dataset_with_target_final.csv", index=False)

print("Target columns created successfully.")
print(df[["Player Future Potential Score", "Player Future Potential Rating"]].head())
print("\nClass distribution:")
print(df["Player Future Potential Rating"].value_counts())