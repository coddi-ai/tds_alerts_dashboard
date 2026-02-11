# Multi-Technical Alerts Dashboard - Overview

**Version**: 2.0.0  
**Last Updated**: February 4, 2026  
**Owner**: Technical Alerts Team

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Dashboard Purpose](#dashboard-purpose)
3. [Data Sources](#data-sources)
4. [Dashboard Architecture](#dashboard-architecture)
5. [Dashboard Sections](#dashboard-sections)
6. [Multi-Client Architecture](#multi-client-architecture)

---

## 🎯 Overview

The Multi-Technical Alerts Dashboard is a comprehensive fleet monitoring platform that provides **real-time insights into equipment health** by integrating multiple data sources. The dashboard enables maintenance teams to proactively identify issues, optimize equipment availability, and make data-driven decisions.

**Key Objective**: Allow users to understand the state of the fleet based on the latest available data across all monitoring techniques.

---

## 🚀 Dashboard Purpose

The dashboard consolidates data from multiple monitoring techniques to create **contextualized alerts** that point to deficiencies in fleet machine performance. These alerts are generated through sophisticated logic applied to:

- **Sensor data** (Telemetry)
- **Tribology analysis** (Oil)
- **Maintenance records** (Mantentions)

The platform provides intuitive visualizations that help users:
- ✅ Understand overall fleet health
- ✅ Identify machines requiring attention
- ✅ Track trends and patterns over time
- ✅ Access AI-generated recommendations
- ✅ Monitor alert triggers and thresholds

---

## 📊 Data Sources

The dashboard integrates four primary data sources:

### 1. **Oil (Tribology Analysis)**
- **Purpose**: Analyze oil samples to detect component wear and contamination
- **Frequency**: Periodic sampling (weekly/monthly)
- **Key Outputs**: Essay classifications, component health status, AI recommendations
- **Status**: ✅ **Fully Implemented**

### 2. **Telemetry (Sensor Data)**
- **Purpose**: Real-time monitoring of equipment sensors and operational parameters
- **Frequency**: Continuous streaming data
- **Key Outputs**: Sensor alerts, trend analysis, operational state tracking
- **Status**: 🔄 **In Progress**

### 3. **Mantentions (Maintenance Records)**
- **Purpose**: Track maintenance activities and intervention history
- **Frequency**: Weekly reports
- **Key Outputs**: Maintenance summaries, activity tracking per system
- **Status**: 🔄 **In Progress**

### 4. **Alerts (Consolidated)**
- **Purpose**: Unified view of all alerts across techniques
- **Frequency**: Real-time aggregation
- **Key Outputs**: Consolidated alerts with AI diagnosis, cross-technique correlation
- **Status**: 🔄 **In Progress**

---

## 🏗️ Dashboard Architecture

### Data Layer Structure

The dashboard follows a **Data Mesh architecture** with the following structure:

```
data/
├── oil/
│   ├── silver/{client}/
│   └── golden/{client}/
├── telemetry/
│   ├── silver/{client}/
│   └── golden/{client}/
├── mantentions/
│   └── golden/{client}/
└── alerts/
    └── golden/{client}/
```

**Path Pattern**: `data/{technique}/{layer}/{client}/{datafile}`

Where:
- **technique**: `oil`, `telemetry`, `mantentions`, `alerts`
- **layer**: `silver` (harmonized data), `golden` (analysis-ready outputs)
- **client**: Client identifier
- **datafile**: Specific data files based on data contracts

### Technology Stack

- **Frontend**: Dash (Plotly)
- **Data Processing**: Python, Pandas
- **Storage**: Parquet files (columnar format)
- **Deployment**: Docker containers
- **AI Integration**: LLM-based recommendations

---

## 🎨 Dashboard Sections

The dashboard is organized into three main sections, each serving a specific purpose:

### 1. **Overview Section**

**Purpose**: Provide a high-level summary of fleet health

**Features**:
- Overall fleet condition metrics
- Aggregated alert counts across all techniques
- Equipment availability statistics
- Key performance indicators (KPIs)

**Sub-sections**:
- **General**: Fleet-wide summary dashboard

**Data Sources**: All (Oil, Telemetry, Mantentions, Alerts)

**Status**: 🔄 In Progress

---

### 2. **Monitoring Section**

**Purpose**: Detailed monitoring and analysis per technique

**Features**:
- Technique-specific visualizations
- Drill-down capabilities for detailed analysis
- Historical trend analysis
- AI-generated insights

**Sub-sections**:

#### 2.1 **Alerts**
- **Purpose**: Unified view of all alerts across techniques
- **Tabs**:
  - **General**: Alert overview, counts, severity distribution
  - **Detail**: Individual alert inspection with AI diagnosis
- **Data Source**: `alerts/golden/{client}/consolidated_alerts.csv`
- **Status**: 🔄 Planned

#### 2.2 **Telemetry**
- **Purpose**: Sensor data monitoring and trend analysis
- **Features**: 
  - Real-time sensor readings
  - Trend snapshots
  - Alert triggers visualization
  - Operational state tracking
- **Data Sources**: 
  - `telemetry/silver/{client}/telemetry.parquet`
  - `telemetry/golden/{client}/alerts_data.csv`
- **Status**: 🔄 Planned

#### 2.3 **Mantentions**
- **Purpose**: Maintenance activity tracking
- **Features**:
  - Intervention history per unit
  - Maintenance frequency analysis
  - Activity breakdown by system
- **Data Source**: `mantentions/golden/{client}/ww-yyyy.csv`
- **Status**: 🔄 Planned

#### 2.4 **Oil**
- **Purpose**: Tribology analysis and component health
- **Features**:
  - Essay classifications
  - Radar charts for component analysis
  - Time series trends
  - AI recommendations
- **Data Sources**: 
  - `oil/golden/{client}/classified.parquet`
  - `oil/golden/{client}/machine_status.parquet`
- **Status**: ✅ **Fully Implemented**

---

### 3. **Limits Section**

**Purpose**: Display thresholds and triggers for alert generation

**Features**:
- Configurable limit tables
- Threshold visualization
- Statistical analysis of limits

**Sub-sections**:

#### 3.1 **Oil Limits**
- **Purpose**: Stewart Limits for essay classifications
- **Features**: 
  - Limits by machine/component/essay
  - Threshold distribution charts
  - Sample count statistics
- **Data Source**: `oil/golden/{client}/stewart_limits.parquet`
- **Status**: ✅ **Fully Implemented**

#### 3.2 **Telemetry Limits**
- **Purpose**: Sensor alert thresholds
- **Features**:
  - Trigger rules per state
  - Operational limits
  - System-specific thresholds
- **Data Source**: `telemetry/golden/{client}/data_rules.csv`
- **Status**: 🔄 Planned

---

## 🏢 Multi-Client Architecture

The dashboard is designed as a **SaaS platform** supporting multiple clients with isolated data:

### Client Isolation

- **Data Separation**: Each client has dedicated folders
- **Independent Processing**: Clients processed separately
- **Isolated Limits**: Thresholds calculated per client
- **Secure Access**: Authentication and authorization per client

### Client Selection

Users select their client context through a global dropdown that filters all dashboard views to show only relevant data.

### Scalability

The architecture supports:
- ✅ Adding new clients without code changes
- ✅ Different data sources per client
- ✅ Client-specific configurations
- ✅ Independent update schedules

---

## 📈 Alert Generation Logic

Alerts are generated through technique-specific logic:

### Oil Alerts
- Based on Stewart Limits (90th, 95th, 98th percentiles)
- Essay scoring system
- Component-level classification

### Telemetry Alerts
- Threshold-based detection
- State-aware limits (Operational, Idle, etc.)
- Trend analysis for anomaly detection

### Consolidated Alerts
- Cross-technique correlation
- AI-powered diagnosis
- System/subsystem/component mapping

---

## 🎯 User Benefits

1. **Proactive Maintenance**: Identify issues before failure
2. **Reduced Downtime**: Quick identification of critical alerts
3. **Data-Driven Decisions**: AI recommendations based on multiple data sources
4. **Fleet Visibility**: Comprehensive view of all equipment
5. **Cost Optimization**: Prioritize maintenance activities efficiently

---

## 📚 Related Documentation

- **Data Contracts**:
  - [Oil Data Contracts](../oil/DATA_CONTRACTS.md)
  - [Telemetry Data Contracts](../telemetry/data_contracts.md)
  - [Mantentions Data Contracts](../mantentions/data_contracts.md)
  - [Alerts Data Contracts](../alerts/data_contracts.md)

- **Technical Documentation**:
  - [Migration Plan](migration_plan.md)
  - [Deployment Guide](../../DEPLOY_GUIDE.md)
  - [Component Granularity](../oil/COMPONENT_GRANULARITY_FIX.md)

---

## 🔄 Version History

### Version 2.0.0 (February 2026)
- Multi-technique integration architecture
- Consolidated alerts system
- Enhanced navigation with sections/subsections
- Scalable multi-client platform

### Version 1.0.0 (January 2026)
- Initial oil analysis dashboard
- Stewart Limits implementation
- Basic machine monitoring
