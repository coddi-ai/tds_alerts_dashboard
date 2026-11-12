"""Login events for "Administración > Registro de Usuarios" (documentation: registro_usuarios_specs.md, TR-1).

Layers, from the login handler to the dashboard:
  writer       one JSON object per login under auth_events/raw/ (never reads or overwrites)
  compaction   scheduled job: raw objects -> auth_events/daily/dt=YYYY-MM-DD/events.parquet
  data_access  the only reader the dashboard uses (events + registry)
  registry     auth_registry/clients.json and users.json, cached
  migration    one-off import of the legacy login log
"""
