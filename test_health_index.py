"""
Test script for Health Index functionality.

Run this script to verify that all Health Index components work correctly.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import pandas as pd
from dashboard.components.health_index_charts import (
    create_health_index_timeline,
    create_health_index_heatmap,
    create_health_index_bar_chart,
    create_health_index_distribution,
    create_health_status_pie,
    get_hi_color,
    get_hi_status
)
from dashboard.components.health_index_tables import (
    create_health_index_detail_table,
    create_critical_units_table,
    create_system_summary_table
)

# Colors for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'


def print_header(text):
    """Print section header."""
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}{text.center(60)}{RESET}")
    print(f"{BLUE}{'='*60}{RESET}\n")


def print_success(text):
    """Print success message."""
    print(f"{GREEN}✓ {text}{RESET}")


def print_error(text):
    """Print error message."""
    print(f"{RED}✗ {text}{RESET}")


def print_warning(text):
    """Print warning message."""
    print(f"{YELLOW}⚠ {text}{RESET}")


def test_data_loading():
    """Test data loading."""
    print_header("TEST 1: DATA LOADING")
    
    data_path = Path(r"C:\Users\panch\Desktop\Coddi\CDA\Dashboard\tds_alerts_dashboard\data\telemetry\golden\cda\Health_Index\health_index.parquet")
    
    if not data_path.exists():
        print_error(f"Data file not found at: {data_path}")
        return None
    
    print_success(f"Data file found: {data_path}")
    
    try:
        df = pd.read_parquet(data_path)
        print_success(f"Data loaded successfully: {len(df):,} records")
        print(f"  - Shape: {df.shape}")
        print(f"  - Columns: {df.columns.tolist()}")
        print(f"  - Date range: {df['start_time'].min()} to {df['end_time'].max()}")
        print(f"  - Units: {sorted(df['Unit'].unique())}")
        print(f"  - Systems: {sorted(df['component'].unique())}")
        print(f"  - Models: {sorted(df['truck_model'].unique())}")
        return df
    except Exception as e:
        print_error(f"Error loading data: {e}")
        return None


def test_color_functions(df):
    """Test color and status functions."""
    print_header("TEST 2: COLOR AND STATUS FUNCTIONS")
    
    test_values = [0.3, 0.6, 0.9]
    
    for val in test_values:
        color = get_hi_color(val)
        status = get_hi_status(val)
        print_success(f"HI={val:.1f} → Color={color}, Status={status}")


def test_chart_creation(df):
    """Test chart creation functions."""
    print_header("TEST 3: CHART CREATION")
    
    charts = [
        ("Timeline", create_health_index_timeline, df),
        ("Heatmap", create_health_index_heatmap, df),
        ("Bar Chart", create_health_index_bar_chart, df),
        ("Distribution", create_health_index_distribution, df),
        ("Pie Chart", create_health_status_pie, df)
    ]
    
    for chart_name, chart_func, data in charts:
        try:
            fig = chart_func(data)
            if fig:
                print_success(f"{chart_name} created successfully")
            else:
                print_warning(f"{chart_name} returned None/empty")
        except Exception as e:
            print_error(f"{chart_name} failed: {e}")


def test_table_creation(df):
    """Test table creation functions."""
    print_header("TEST 4: TABLE CREATION")
    
    tables = [
        ("Detail Table", create_health_index_detail_table, df),
        ("Critical Units Table", create_critical_units_table, df),
        ("System Summary Table", create_system_summary_table, df, "Motor")
    ]
    
    for table_name, table_func, *args in tables:
        try:
            table = table_func(*args)
            if table:
                print_success(f"{table_name} created successfully")
            else:
                print_warning(f"{table_name} returned None/empty")
        except Exception as e:
            print_error(f"{table_name} failed: {e}")


def test_statistics(df):
    """Test data statistics."""
    print_header("TEST 5: DATA STATISTICS")
    
    try:
        # Overall stats
        avg_hi = df['health_index'].mean()
        print_success(f"Average HI: {avg_hi:.4f}")
        
        # Status distribution
        critical = (df['health_index'] < 0.5).sum()
        warning = ((df['health_index'] >= 0.5) & (df['health_index'] < 0.8)).sum()
        healthy = (df['health_index'] >= 0.8).sum()
        total = len(df)
        
        print_success(f"Critical (< 0.5): {critical:,} ({critical/total*100:.2f}%)")
        print_success(f"Warning (0.5-0.8): {warning:,} ({warning/total*100:.2f}%)")
        print_success(f"Healthy (≥ 0.8): {healthy:,} ({healthy/total*100:.2f}%)")
        
        # By unit
        print("\n  Top 5 units by average HI:")
        hi_by_unit = df.groupby('Unit')['health_index'].mean().sort_values(ascending=False).head()
        for unit, hi in hi_by_unit.items():
            status_emoji = "🟢" if hi >= 0.8 else "🟡" if hi >= 0.5 else "🔴"
            print(f"    {status_emoji} {unit}: {hi:.4f}")
        
        # By system
        print("\n  Average HI by system:")
        hi_by_system = df.groupby('component')['health_index'].mean().sort_values(ascending=False)
        for system, hi in hi_by_system.items():
            status_emoji = "🟢" if hi >= 0.8 else "🟡" if hi >= 0.5 else "🔴"
            print(f"    {status_emoji} {system}: {hi:.4f}")
            
    except Exception as e:
        print_error(f"Statistics calculation failed: {e}")


def test_filtering(df):
    """Test data filtering."""
    print_header("TEST 6: DATA FILTERING")
    
    # Filter by model
    try:
        df_789c = df[df['truck_model'] == 'CAT 789C']
        df_789d = df[df['truck_model'] == 'CAT 789D']
        print_success(f"CAT 789C records: {len(df_789c):,}")
        print_success(f"CAT 789D records: {len(df_789d):,}")
    except Exception as e:
        print_error(f"Model filtering failed: {e}")
    
    # Filter by system
    try:
        for system in df['component'].unique():
            df_sys = df[df['component'] == system]
            avg_hi = df_sys['health_index'].mean()
            print_success(f"{system}: {len(df_sys):,} records, avg HI={avg_hi:.4f}")
    except Exception as e:
        print_error(f"System filtering failed: {e}")
    
    # Filter by HI range
    try:
        critical = df[df['health_index'] < 0.5]
        warning = df[(df['health_index'] >= 0.5) & (df['health_index'] < 0.8)]
        healthy = df[df['health_index'] >= 0.8]
        print_success(f"Critical units: {critical['Unit'].nunique()} unique units in critical state")
        print_success(f"Warning units: {warning['Unit'].nunique()} unique units in warning state")
        print_success(f"Healthy units: {healthy['Unit'].nunique()} unique units in healthy state")
    except Exception as e:
        print_error(f"HI range filtering failed: {e}")


def main():
    """Run all tests."""
    print(f"\n{BLUE}{'*'*60}{RESET}")
    print(f"{BLUE}HEALTH INDEX FUNCTIONALITY TEST SUITE{RESET}".center(60))
    print(f"{BLUE}{'*'*60}{RESET}")
    
    # Test 1: Load data
    df = test_data_loading()
    if df is None or df.empty:
        print_error("\nCannot proceed with tests - data loading failed")
        return
    
    # Test 2: Color functions
    test_color_functions(df)
    
    # Test 3: Chart creation
    test_chart_creation(df)
    
    # Test 4: Table creation
    test_table_creation(df)
    
    # Test 5: Statistics
    test_statistics(df)
    
    # Test 6: Filtering
    test_filtering(df)
    
    # Summary
    print_header("TEST SUMMARY")
    print_success("All tests completed!")
    print(f"\n{YELLOW}Note: Visual inspection of dashboard required for full validation{RESET}")
    print(f"{YELLOW}Run the dashboard and navigate to Monitoring → Health Index{RESET}\n")


if __name__ == '__main__':
    main()
