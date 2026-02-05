"""Test script to debug layout issues."""

import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from dashboard.layout import create_app_layout, create_login_page

# Test creating the app layout
print("=" * 50)
print("Testing create_app_layout()...")
print("=" * 50)

try:
    layout = create_app_layout()
    print(f"✓ Layout created successfully")
    print(f"  Type: {type(layout)}")
    print(f"  Has children: {hasattr(layout, 'children')}")
    if hasattr(layout, 'children'):
        print(f"  Number of children: {len(layout.children)}")
        for i, child in enumerate(layout.children):
            print(f"    Child {i}: {type(child).__name__} - id={getattr(child, 'id', 'no-id')}")
except Exception as e:
    print(f"✗ Error creating layout: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 50)
print("Testing create_login_page()...")
print("=" * 50)

try:
    login_page = create_login_page()
    print(f"✓ Login page created successfully")
    print(f"  Type: {type(login_page)}")
    print(f"  Has children: {hasattr(login_page, 'children')}")
except Exception as e:
    print(f"✗ Error creating login page: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 50)
print("Testing callback registration...")
print("=" * 50)

try:
    import dash
    import dash_bootstrap_components as dbc
    
    test_app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
    test_app.layout = create_app_layout()
    
    # Register callbacks
    from dashboard.callbacks.auth_callbacks import register_auth_callbacks
    register_auth_callbacks(test_app)
    
    print(f"✓ Callbacks registered successfully")
    print(f"  Number of callbacks: {len(test_app.callback_map)}")
    for callback_id, callback in test_app.callback_map.items():
        print(f"    {callback_id}")
    
except Exception as e:
    print(f"✗ Error registering callbacks: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 50)
print("Test completed")
print("=" * 50)
