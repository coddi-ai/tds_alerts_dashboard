"""
Script to generate dummy maintenance data for testing.
Run this to populate sample data for the Mantenciones General dashboard.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.data.dummy_generator import generate_dummy_tables, export_tables


def main():
    """Generate and export dummy maintenance data."""
    print("=" * 60)
    print("Generador de Datos Dummy - Mantenciones General")
    print("=" * 60)
    print()
    
    # Generate tables
    print("Generando tablas dummy...")
    tables = generate_dummy_tables(
        n_machines=25,
        n_systems=5,
        subsystems_per_system=3,
        components_per_subsystem=4,
        days_back=60,
        seed=7
    )
    
    print("\n✓ Tablas generadas exitosamente!")
    print("\nResumen de datos:")
    print("-" * 60)
    for name, df in tables.items():
        print(f"  {name:20s}: {len(df):5d} registros")
    
    # Export to CSV
    output_dir = "data/mantentions/dummy"
    print(f"\nExportando a {output_dir}...")
    export_tables(tables, output_dir)
    
    print("\n" + "=" * 60)
    print("✓ Datos dummy generados y exportados exitosamente!")
    print("=" * 60)
    print()
    print("Los datos están disponibles en:", output_dir)
    print()
    print("Ahora puedes:")
    print("  1. Ejecutar el dashboard con: python dashboard/app.py")
    print("  2. Navegar a: Monitoring > Mantentions")
    print("  3. Hacer clic en 'Refrescar' para cargar los datos")
    print()


if __name__ == "__main__":
    main()
