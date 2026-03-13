"""
Generador de datos dummy para la vista de Mantenciones General.
Respeta el data contract: MACHINES, SYSTEMS, SUBSYSTEMS, COMPONENTS, RECORDS, JOBS, ACTIONS.
"""

import uuid
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict


def _uuid():
    """Generate a UUID string."""
    return str(uuid.uuid4())


def generate_dummy_tables(
    n_machines=25,
    n_systems=5,
    subsystems_per_system=3,
    components_per_subsystem=4,
    days_back=60,
    seed=7,
) -> Dict[str, pd.DataFrame]:
    """
    Generate dummy tables for maintenance dashboard.
    
    Args:
        n_machines: Number of machines to generate
        n_systems: Number of systems
        subsystems_per_system: Subsystems per each system
        components_per_subsystem: Components per each subsystem
        days_back: Days of historical data
        seed: Random seed for reproducibility
        
    Returns:
        Dictionary with DataFrames for each table
    """
    rng = np.random.default_rng(seed)
    now = datetime.now()

    # ---- SYSTEMS / SUBSYSTEMS / COMPONENTS ----
    systems = []
    for i in range(n_systems):
        systems.append({
            "system_id": _uuid(),
            "system_name": f"Sistema {chr(65+i)}",
            "active": True,
            "created_at": now,
            "updated_at": now,
        })
    df_systems = pd.DataFrame(systems)

    subsystems = []
    for s in systems:
        for j in range(subsystems_per_system):
            subsystems.append({
                "subsystem_id": _uuid(),
                "system_id": s["system_id"],
                "subsystem_name": f"{s['system_name']} / Sub {j+1}",
                "is_repairable": bool(rng.integers(0, 2)),
                "active": True,
                "created_at": now,
                "updated_at": now,
            })
    df_subsystems = pd.DataFrame(subsystems)

    components = []
    for ss in subsystems:
        for k in range(components_per_subsystem):
            components.append({
                "component_id": _uuid(),
                "subsystem_id": ss["subsystem_id"],
                "component_name": f"{ss['subsystem_name']} / Comp {k+1}",
                "active": True,
                "created_at": now,
                "updated_at": now,
            })
    df_components = pd.DataFrame(components)

    # ---- MACHINES ----
    machines = []
    for i in range(n_machines):
        machines.append({
            "machine_id": _uuid(),
            "machine_code": f"EQ{str(i+1).zfill(2)}",
            "site_id": "PLANTA-1",
            "asset_type": "EQUIPO",
            "model": "Modelo-X",
            "serial_number": f"SN-{100000+i}",
            "description": "Equipo dummy para demo",
            "created_at": now,
            "updated_at": now,
        })
    df_machines = pd.DataFrame(machines)

    # ---- MACHINE_SYSTEMS (cada máquina tiene 2..n sistemas) ----
    machine_systems = []
    for m in machines:
        chosen = rng.choice(df_systems["system_id"], size=rng.integers(2, min(4, n_systems)+1), replace=False)
        for sid in chosen:
            machine_systems.append({
                "machine_id": m["machine_id"],
                "system_id": sid,
                "active_from": now - timedelta(days=365),
                "active_to": None,
                "created_at": now,
            })
    df_machine_systems = pd.DataFrame(machine_systems)

    # ---- ACTION_TYPES ----
    action_types = [
        {"action_type_id": _uuid(), "action_type_name": "Reparación", "description": "Reparación", "active": True, "created_at": now, "updated_at": now},
        {"action_type_id": _uuid(), "action_type_name": "Reemplazo", "description": "Reemplazo", "active": True, "created_at": now, "updated_at": now},
        {"action_type_id": _uuid(), "action_type_name": "Inspección", "description": "Inspección", "active": True, "created_at": now, "updated_at": now},
        {"action_type_id": _uuid(), "action_type_name": "Lubricación", "description": "Lubricación", "active": True, "created_at": now, "updated_at": now},
    ]
    df_action_types = pd.DataFrame(action_types)

    # Helpers para scope consistente
    subsystems_by_system = df_subsystems.groupby("system_id")["subsystem_id"].apply(list).to_dict()
    components_by_subsystem = df_components.groupby("subsystem_id")["component_id"].apply(list).to_dict()

    # ---- RECORDS / JOBS / ACTIONS ----
    records = []
    jobs = []
    actions = []

    job_type_pool = ["Falla", "Mantención", "Inspección"]

    for m in machines:
        # 3..10 records por máquina
        n_records = rng.integers(3, 11)
        # decide si la máquina tiene un record ongoing
        has_ongoing = bool(rng.integers(0, 2))

        # genera eventos en el pasado
        event_starts = sorted([
            now - timedelta(days=int(rng.integers(1, days_back)), hours=int(rng.integers(0, 24)))
            for _ in range(n_records)
        ])

        for ridx, start in enumerate(event_starts):
            record_id = _uuid()
            # duración 0.5h..20h
            duration_hours = float(rng.uniform(0.5, 20.0))
            end = start + timedelta(hours=duration_hours)

            ongoing = False
            if has_ongoing and ridx == (len(event_starts) - 1):
                # último record queda en curso
                ongoing = True
                end = None

            records.append({
                "record_id": record_id,
                "machine_id": m["machine_id"],
                "source_system": "DUMMY",
                "source_work_order_id": f"OT-{rng.integers(10000,99999)}",
                "start_date": start,
                "end_date": end,
                "ongoing": ongoing,
                "original_text": None,
                "clean_text": None,
                "preproc_version": "v0",
                "created_at": now,
                "updated_at": now,
            })

            # jobs 1..3 por record
            n_jobs = rng.integers(1, 4)
            # sistemas instalados en la máquina
            installed_systems = df_machine_systems.loc[df_machine_systems["machine_id"] == m["machine_id"], "system_id"].tolist()

            for _ in range(n_jobs):
                job_id = _uuid()
                job_type = rng.choice(job_type_pool)

                system_id = rng.choice(installed_systems)
                # 70% define subsystem también, 30% solo system
                if rng.random() < 0.7:
                    subsystem_id = rng.choice(subsystems_by_system[system_id])
                else:
                    subsystem_id = None

                # job time: dentro del record
                job_start = start + timedelta(minutes=int(rng.integers(0, 60)))
                job_end = None if ongoing else min(
                    (end if end else now),
                    job_start + timedelta(hours=float(rng.uniform(0.2, 6.0)))
                )

                jobs.append({
                    "job_id": job_id,
                    "record_id": record_id,
                    "system_id": system_id,
                    "subsystem_id": subsystem_id,
                    "job_type": job_type,
                    "start_date": job_start,
                    "end_date": job_end,
                    "ongoing": ongoing and (job_end is None),
                    "notes": f"{job_type} - detalle dummy",
                    "created_at": now,
                    "updated_at": now,
                })

                # actions 1..5 por job
                n_actions = rng.integers(1, 6)
                for _a in range(n_actions):
                    action_id = _uuid()
                    action_type_id = rng.choice(df_action_types["action_type_id"])

                    # action subsystem obligatorio:
                    eff_subsystem = subsystem_id
                    if eff_subsystem is None:
                        eff_subsystem = rng.choice(subsystems_by_system[system_id])

                    # component opcional (50%)
                    if rng.random() < 0.5:
                        component_id = rng.choice(components_by_subsystem[eff_subsystem])
                    else:
                        component_id = None

                    performed_at = job_start + timedelta(minutes=int(rng.integers(0, 240)))

                    actions.append({
                        "action_id": action_id,
                        "job_id": job_id,
                        "action_type_id": action_type_id,
                        "subsystem_id": eff_subsystem,
                        "component_id": component_id,
                        "performed_at": performed_at,
                        "notes": "acción dummy",
                        "created_at": now,
                        "updated_at": now,
                    })

    df_records = pd.DataFrame(records)
    df_jobs = pd.DataFrame(jobs)
    df_actions = pd.DataFrame(actions)

    return {
        "machines": df_machines,
        "systems": df_systems,
        "subsystems": df_subsystems,
        "components": df_components,
        "machine_systems": df_machine_systems,
        "records": df_records,
        "jobs": df_jobs,
        "action_types": df_action_types,
        "actions": df_actions,
    }


def export_tables(tables: Dict[str, pd.DataFrame], out_dir: str) -> None:
    """
    Export generated tables to CSV files.
    
    Args:
        tables: Dictionary with DataFrames
        out_dir: Output directory
    """
    import os
    os.makedirs(out_dir, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(f"{out_dir}/{name}.csv", index=False)
        print(f"Exported {name}.csv with {len(df)} rows")


if __name__ == "__main__":
    # Generate and export dummy data
    print("Generating dummy tables...")
    tables = generate_dummy_tables()
    
    print("\nTable summary:")
    for name, df in tables.items():
        print(f"  {name}: {len(df)} rows")
    
    # Export to CSV
    export_tables(tables, "data/mantentions/dummy")
    print("\n✓ Dummy data exported successfully!")
