"""
Pydantic data models for Multi-Technical-Alerts.

Defines schemas for:
- OilSample: Silver layer (harmonized data)
- ClassifiedReport: Gold layer (classified with AI recommendations)
- MachineStatus: Machine aggregation
"""

from datetime import datetime
from typing import Optional, List, Dict
from pydantic import BaseModel, Field, field_validator
import pandas as pd


class OilSample(BaseModel):
    """
    Schema for harmonized oil sample (Silver layer).
    
    All data from different labs (CDA, EMIN) is transformed to this schema.
    """
    # Identifiers
    sample_number: str = Field(..., description="Unique sample identifier")
    unit_id: str = Field(..., description="Machine/unit ID")
    component: str = Field(..., description="Component name (harmonized)")
    
    # Dates
    sample_date: datetime = Field(..., description="Sample collection date")
    previous_sample_number: Optional[str] = Field(None, description="Previous sample number for this unit/component")
    previous_sample_date: Optional[datetime] = Field(None, description="Previous sample date")
    days_since_previous: Optional[int] = Field(None, description="Days since previous sample")
    
    # Hours
    component_hours: Optional[float] = Field(None, description="Component operating hours")
    
    # Essay values (all numeric, harmonized names)
    essays: Dict[str, float] = Field(default_factory=dict, description="Essay name → value mapping")
    
    # Metadata
    client: str = Field(..., description="Client name (CDA or EMIN)")
    lab: str = Field(..., description="Laboratory name")
    group_element: Optional[str] = Field(None, description="Group classification for radar charts (Phase 1)")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "sample_number": "12345",
                "unit_id": "WO-001",
                "component": "motor",
                "sample_date": "2024-01-15T00:00:00",
                "previous_sample_number": "12340",
                "previous_sample_date": "2023-12-15T00:00:00",
                "days_since_previous": 31,
                "component_hours": 1500.5,
                "essays": {
                    "hierro": 25.3,
                    "cobre": 10.2,
                    "cromo": 2.1,
                    "viscosidad_40": 95.5
                },
                "client": "CDA",
                "lab": "Finning",
                "group_element": "Desgaste"
            }
        }
    }


class ClassifiedReport(BaseModel):
    """
    Schema for classified oil report (Gold layer).
    
    Includes classification results and AI recommendations.
    """
    # From OilSample
    sample_number: str
    unit_id: str
    component: str
    sample_date: datetime
    client: str
    
    # Classification results
    essays_broken: int = Field(..., description="Number of essays exceeding thresholds")
    severity_score: int = Field(..., description="Total severity points (1=Marginal, 3=Condenatorio, 5=Critico)")
    report_status: str = Field(..., description="Classification: Normal, Alerta, or Anormal")
    breached_essays: List[Dict[str, any]] = Field(default_factory=list, description="List of essays that exceeded thresholds")
    
    # AI recommendation
    ai_recommendation: Optional[str] = Field(None, description="AI-generated maintenance recommendation")
    ai_generated_at: Optional[datetime] = Field(None, description="Timestamp of AI generation")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "sample_number": "12345",
                "unit_id": "WO-001",
                "component": "motor",
                "sample_date": "2024-01-15T00:00:00",
                "client": "CDA",
                "essays_broken": 2,
                "severity_score": 4,
                "report_status": "Alerta",
                "breached_essays": [
                    {"essay": "hierro", "value": 45.2, "threshold": "Condenatorio", "limit": 40.0, "points": 3},
                    {"essay": "cobre", "value": 18.5, "threshold": "Marginal", "limit": 15.0, "points": 1}
                ],
                "ai_recommendation": "Se observa incremento en hierro y cobre, indicando desgaste progresivo...",
                "ai_generated_at": "2024-01-15T10:30:00"
            }
        }
    }


class MachineStatus(BaseModel):
    """
    Schema for machine-level status aggregation.
    
    Combines all components of a machine into overall health status.
    """
    unit_id: str
    client: str
    latest_sample_date: datetime
    
    # Aggregated classification
    overall_status: str = Field(..., description="Worst status across all components")
    total_components: int = Field(..., description="Number of components analyzed")
    components_normal: int = Field(default=0, description="Count of Normal components")
    components_alerta: int = Field(default=0, description="Count of Alerta components")
    components_anormal: int = Field(default=0, description="Count of Anormal components")
    
    # Priority ranking
    priority_score: int = Field(..., description="Priority score for maintenance (higher = more urgent)")
    
    # Component details
    component_details: List[Dict[str, any]] = Field(default_factory=list, description="Status of each component")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "unit_id": "WO-001",
                "client": "CDA",
                "latest_sample_date": "2024-01-15T00:00:00",
                "overall_status": "Anormal",
                "total_components": 3,
                "components_normal": 1,
                "components_alerta": 1,
                "components_anormal": 1,
                "priority_score": 9,
                "component_details": [
                    {"component": "motor", "status": "Anormal", "severity_score": 8},
                    {"component": "transmision", "status": "Alerta", "severity_score": 4},
                    {"component": "hidraulico", "status": "Normal", "severity_score": 0}
                ]
            }
        }
    }


def dataframe_to_oil_samples(df: pd.DataFrame) -> List[OilSample]:
    """
    Convert DataFrame to list of OilSample models.
    
    Args:
        df: DataFrame with OilSample schema
    
    Returns:
        List of validated OilSample instances
    """
    samples = []
    for _, row in df.iterrows():
        sample = OilSample(**row.to_dict())
        samples.append(sample)
    return samples


def oil_samples_to_dataframe(samples: List[OilSample]) -> pd.DataFrame:
    """
    Convert list of OilSample models to DataFrame.
    
    Args:
        samples: List of OilSample instances
    
    Returns:
        DataFrame
    """
    data = [sample.model_dump() for sample in samples]
    return pd.DataFrame(data)
