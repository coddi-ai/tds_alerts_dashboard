"""Script to inspect parquet files structure."""
import pandas as pd
import sys

files = ['query_1.parquet', 'query_2.parquet', 'query_3.parquet']

for file in files:
    try:
        df = pd.read_parquet(file)
        print(f"\n{'='*60}")
        print(f"FILE: {file}")
        print(f"{'='*60}")
        print(f"Shape: {df.shape}")
        print(f"\nColumns: {list(df.columns)}")
        print(f"\nData types:\n{df.dtypes}")
        print(f"\nFirst 3 rows:\n{df.head(3)}")
        print(f"\nSample values:")
        for col in df.columns:
            unique_count = df[col].nunique()
            print(f"  {col}: {unique_count} unique values")
            if unique_count <= 10:
                print(f"    Values: {df[col].unique().tolist()}")
    except Exception as e:
        print(f"\nError reading {file}: {e}")

print("\n" + "="*60)
print("Inspection complete!")
