"""
Script de diagnóstico para verificar rutas de mantenciones.
Ejecutar: python debug_maintenance_paths.py
"""

from pathlib import Path
import os

def check_maintenance_paths():
    """Verificar todas las rutas posibles para datos de mantenciones."""
    
    base_path = Path(__file__).parent
    clients = ['cda', 'CDA', 'emin', 'EMIN']
    
    print("=" * 80)
    print("DIAGNÓSTICO DE RUTAS DE MANTENCIONES")
    print("=" * 80)
    print(f"\nBase path: {base_path}")
    print()
    
    for client in clients:
        print(f"\n--- Cliente: {client} ---")
        
        # Ruta con minúsculas
        path_lower = base_path / "data" / "mantentions" / "golden" / client.lower() / "Maintance_Labeler_Views"
        print(f"Lower: {path_lower}")
        print(f"  Existe: {path_lower.exists()}")
        if path_lower.exists():
            files = list(path_lower.glob("*.parquet"))
            print(f"  Archivos: {len(files)}")
            for f in files:
                print(f"    - {f.name}")
        
        # Ruta con mayúsculas
        path_upper = base_path / "data" / "mantentions" / "golden" / client.upper() / "Maintance_Labeler_Views"
        print(f"Upper: {path_upper}")
        print(f"  Existe: {path_upper.exists()}")
        if path_upper.exists():
            files = list(path_upper.glob("*.parquet"))
            print(f"  Archivos: {len(files)}")
            for f in files:
                print(f"    - {f.name}")
    
    print("\n" + "=" * 80)
    print("VERIFICACIÓN DE LOADERS")
    print("=" * 80)
    
    # Probar con el loader real
    try:
        from src.data.loaders import _get_mantentions_data_path, load_maintenance_actions_all_equipment, load_business_kpis
        
        for client in ['CDA', 'cda', 'EMIN', 'emin']:
            print(f"\n--- Cliente: {client} ---")
            path = _get_mantentions_data_path(client)
            print(f"  Path retornado: {path}")
            print(f"  Existe: {path.exists()}")
            
            # Intentar cargar datos
            try:
                df_actions = load_maintenance_actions_all_equipment(client=client)
                print(f"  ✓ Actions loaded: {len(df_actions)} rows")
            except Exception as e:
                print(f"  ✗ Error loading actions: {e}")
            
            try:
                df_kpis = load_business_kpis(client=client)
                print(f"  ✓ KPIs loaded: {len(df_kpis)} rows")
            except Exception as e:
                print(f"  ✗ Error loading KPIs: {e}")
    
    except Exception as e:
        print(f"ERROR importando loaders: {e}")
    
    print("\n" + "=" * 80)
    print("VERIFICACIÓN DE REPOSITORY")
    print("=" * 80)
    
    try:
        from src.data.maintenance_repository import get_repository
        
        for client in ['CDA', 'cda']:
            print(f"\n--- Cliente: {client} ---")
            repo = get_repository(mode="parquet", client=client)
            print(f"  Repository client: {repo.client}")
            
            try:
                df_status = repo.get_status_counts()
                print(f"  ✓ Status counts: {len(df_status)} rows")
                print(f"    Data: {df_status.to_dict('records')}")
            except Exception as e:
                print(f"  ✗ Error getting status: {e}")
            
            try:
                df_downtime = repo.get_downtime_mtd()
                print(f"  ✓ Downtime MTD: {len(df_downtime)} rows")
                print(f"    Data: {df_downtime.to_dict('records')}")
            except Exception as e:
                print(f"  ✗ Error getting downtime: {e}")
    
    except Exception as e:
        print(f"ERROR importando repository: {e}")
    
    print("\n" + "=" * 80)
    print("FIN DEL DIAGNÓSTICO")
    print("=" * 80)


if __name__ == "__main__":
    check_maintenance_paths()
