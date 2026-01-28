# Multi-Technical Alerts Dashboard

Interactive web dashboard for oil analysis visualization and monitoring.

## Features

- **Authentication**: Role-based access (admin, CDA viewer, EMIN viewer)
- **Stewart Limits Tab**: View and filter statistical thresholds by machine/component/essay
- **Machines Overview Tab**: Monitor machine health with status distribution and priority tables
- **Reports Detail Tab**: Analyze individual samples with radar charts, time series, and AI recommendations

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Run Pipeline (Generate Data)

First, process your data to generate the Gold layer:

```bash
python main.py
```

This creates:
- `data/oil/processed/cda_classified.parquet`
- `data/oil/processed/emin_classified.parquet`
- `data/oil/processed/cda_machine_status.parquet`
- `data/oil/processed/emin_machine_status.parquet`
- `data/oil/processed/stewart_limits.json` and `.parquet`

### 3. Start Dashboard

```bash
# Option 1: Run directly
python dashboard/app.py

# Option 2: Run as module (from project root)
python -m dashboard.app
```

The dashboard will be available at: **http://localhost:8050**

## Login Credentials

| Username   | Password  | Access       |
|------------|-----------|--------------|
| admin      | admin123  | CDA + EMIN   |
| cda_user   | cda123    | CDA only     |
| emin_user  | emin123   | EMIN only    |

## Dashboard Tabs

### Tab 1: Stewart Limits
- Filter by machine, component, or essay name
- Color-coded thresholds:
  - **Green**: Marginal (90th percentile)
  - **Yellow**: Condenatorio (95th percentile)
  - **Red**: Crítico (98th percentile)

### Tab 2: Machines Overview
- **Status pie chart**: Distribution of Normal/Alerta/Anormal machines
- **Priority table**: Top 10 machines requiring attention
- **Machine details**: Component-level status breakdown

### Tab 3: Reports Detail
- **Radar chart**: Visualize essay values vs. thresholds by GroupElement
- **Time series**: Track essay trends over time with threshold lines
- **AI recommendations**: View OpenAI-generated maintenance suggestions
- **Breached essays**: Detailed table of threshold violations

## Color Scheme

- **Normal**: Green (#28a745)
- **Alerta**: Yellow/Amber (#ffc107)
- **Anormal**: Red (#dc3545)

## Architecture

```
dashboard/
├── app.py              # Main application entry point
├── auth.py             # User authentication
├── layout.py           # Page layouts (login, main dashboard)
├── components/         # Reusable UI components
│   ├── charts.py       # Plotly charts (pie, radar, time series)
│   ├── filters.py      # Dropdowns and filters
│   └── tables.py       # DataTables with conditional styling
├── tabs/               # Tab content
│   ├── tab_limits.py   # Stewart Limits tab
│   ├── tab_machines.py # Machines Overview tab
│   └── tab_reports.py  # Reports Detail tab
└── callbacks/          # Interactive callbacks
    ├── auth_callbacks.py
    ├── limits_callbacks.py
    ├── machines_callbacks.py
    └── reports_callbacks.py
```

## Production Deployment

For production, use a WSGI server like Gunicorn:

```bash
gunicorn dashboard.app:server --bind 0.0.0.0:8050 --workers 4
```

Or use Docker:

```bash
docker-compose up -d
```

## Customization

### Change User Credentials

Edit `dashboard/auth.py` and update the `USERS` dictionary:

```python
USERS = {
    'your_user': {
        'password': hash_password('your_password'),
        'role': 'admin',
        'clients': ['CDA', 'EMIN']
    }
}
```

### Modify Thresholds

Edit classification thresholds in `src/processing/classification.py`:

```python
REPORT_THRESHOLDS = {
    'Normal': 3,    # Change report-level thresholds
    'Anormal': 8
}

MACHINE_THRESHOLDS = {
    'Normal': 2,    # Change machine-level thresholds
    'Anormal': 10
}
```

## Troubleshooting

### No Data Available
- Ensure you've run `python main.py` to process data
- Check that files exist in `data/oil/processed/`

### Import Errors
- Verify all dependencies installed: `pip install -r requirements.txt`
- Check Python version: requires Python 3.11+

### Port Already in Use
- Change port in `dashboard/app.py`: `app.run_server(port=8051)`

## Support

For issues or questions, refer to:
- Project documentation in `docs/`
- Architecture specification in `repo_modular.md`
- Implementation status in `IMPLEMENTATION_STATUS.md`
