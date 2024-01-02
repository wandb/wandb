from typing import List

import polars as pl


def _merge_dfs(dfs: List[pl.DataFrame]) -> pl.DataFrame:
    # Ensure there are DataFrames in the list
    if len(dfs) == 0:
        return pl.DataFrame()

    if len(dfs) == 1:
        return dfs[0]

    merged_df = dfs[0]
    for df in dfs[1:]:
        merged_df = merged_df.join(df, how="outer", on=["_step"])
        col_pairs = [
            (c, f"{c}_right")
            for c in merged_df.columns
            if f"{c}_right" in merged_df.columns
        ]
        for col, right in col_pairs:
            new_col = merged_df[col].fill_null(merged_df[right])
            merged_df = merged_df.with_columns(new_col).drop(right)

    return merged_df
