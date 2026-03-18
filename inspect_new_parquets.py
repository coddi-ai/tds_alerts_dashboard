"""Script to inspect new parquet files structure."""
import pandas as pd

files = ['query_3_actions_all_equipment.parquet', 'query_4_business_kpis.parquet']

for file in files:
    try:
        df = pd.read_parquet(file)
        print(f"\n{'='*80}")
        print(f"FILE: {file}")
        print(f"{'='*80}")
        print(f"Shape: {df.shape}")
        print(f"\nColumns: {list(df.columns)}")
        print(f"\nData types:\n{df.dtypes}")
        print(f"\nFirst 5 rows:\n{df.head(5)}")
        print(f"\nSample unique values:")
        for col in df.columns:
            unique_count = df[col].nunique()
            print(f"  {col}: {unique_count} unique values")
            if unique_count <= 15:
                print(f"    Sample values: {list(df[col].unique())[:10]}")
    except Exception as e:
        print(f"\nError reading {file}: {e}")

print("\n" + "="*80)
print("Inspection complete!")
