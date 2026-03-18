import pandas as pd

# Cargar datos
df = pd.read_parquet('query_3_actions_all_equipment.parquet')

# Convertir event_ts a datetime
df['event_ts_dt'] = pd.to_datetime(df['event_ts'], utc=True)

# Ver diferencia entre event_ts y change_date
print("=== COMPARACIÓN event_ts vs change_date ===")
sample = df[['record_id', 'machine_code', 'event_ts', 'event_ts_dt', 'change_date', 'action_type_name']].head(20)
print(sample.to_string())

# Ver un record con múltiples acciones
print("\n=== RECORD CON MÚLTIPLES ACCIONES ===")
multi_rid = df.groupby('record_id').filter(lambda x: len(x) > 1)['record_id'].iloc[0]
multi_sample = df[df['record_id'] == multi_rid][['action_id', 'event_ts', 'event_ts_dt', 'change_date', 'action_type_name', 'machine_code']].sort_values('event_ts_dt')
print(f"record_id: {multi_rid}")
print(multi_sample.to_string())

# Calcular duración
if len(multi_sample) > 1:
    duration = (multi_sample['event_ts_dt'].max() - multi_sample['event_ts_dt'].min()).total_seconds() / 3600
    print(f"\nDuración calculada: {duration:.2f} horas")

# Ver records con una sola acción
print("\n=== RECORDS CON UNA SOLA ACCIÓN (primeros 5) ===")
single_rids = df.groupby('record_id').filter(lambda x: len(x) == 1)['record_id'].head(5).tolist()
for rid in single_rids:
    single = df[df['record_id'] == rid][['record_id', 'event_ts_dt', 'action_type_name', 'machine_code']]
    print(single.to_string())
    print()
