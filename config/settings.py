"""
Application settings for Multi-Technical-Alerts.

Uses Pydantic Settings for configuration management with environment variable support.
"""

from pathlib import Path
from typing import List
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration with validation."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # API Keys
    openai_api_key: str = Field(..., description="OpenAI API key for recommendations")
    
    # Paths
    data_root: Path = Field(default=Path("data/oil"), description="Root data directory")
    logs_dir: Path = Field(default=Path("logs"), description="Logs directory")
    
    # Dashboard
    secret_key: str = Field(default="dev-secret-key-change-in-production", description="Secret key for sessions")
    dashboard_host: str = Field(default="0.0.0.0", description="Dashboard host")
    dashboard_port: int = Field(default=8050, description="Dashboard port")
    debug_mode: bool = Field(default=False, description="Enable debug mode")
    
    # Processing
    max_workers: int = Field(default=18, description="Max parallel workers for AI processing")
    min_machine_samples: int = Field(default=5, description="Minimum samples per machine")
    min_component_samples: int = Field(default=3, description="Minimum samples per component")
    
    # Stewart Limits
    percentile_marginal: int = Field(default=90, description="Percentile for Marginal threshold")
    percentile_condenatorio: int = Field(default=95, description="Percentile for Condenatorio threshold")
    percentile_critico: int = Field(default=98, description="Percentile for Critico threshold")
    
    # AI Configuration
    openai_model: str = Field(default="gpt-4o-mini", description="OpenAI model")
    openai_temperature: float = Field(default=0.9, description="Temperature for AI generation")
    openai_max_tokens: int = Field(default=500, description="Max tokens per response")
    
    # Classification Thresholds
    essay_points_marginal: int = Field(default=1, description="Points for Marginal essays")
    essay_points_condenatorio: int = Field(default=3, description="Points for Condenatorio essays")
    essay_points_critico: int = Field(default=5, description="Points for Critico essays")
    
    report_threshold_normal: int = Field(default=3, description="Report threshold for Normal (<)")
    report_threshold_anormal: int = Field(default=5, description="Report threshold for Anormal (>=)")
    
    # Clients
    clients: List[str] = Field(default=["CDA", "EMIN"], description="List of client names")
    
    @field_validator("data_root", "logs_dir", mode="before")
    @classmethod
    def ensure_path(cls, v):
        """Convert string to Path if needed."""
        if isinstance(v, str):
            return Path(v)
        return v
    
    @field_validator("clients", mode="before")
    @classmethod
    def parse_clients(cls, v):
        """Parse comma-separated clients if string."""
        if isinstance(v, str):
            return [c.strip() for c in v.split(",")]
        return v
    
    def get_raw_path(self, client: str) -> Path:
        """Get raw data path for a client."""
        return self.data_root / "raw" / client.lower()
    
    def get_to_consume_path(self, client: str) -> Path:
        """Get to_consume data path for a client."""
        return self.data_root / "to_consume" / f"{client.upper()}.parquet"
    
    def get_processed_path(self) -> Path:
        """Get processed data path."""
        return self.data_root / "processed"
    
    def get_stewart_limits_path(self) -> Path:
        """Get Stewart limits JSON path."""
        return self.get_processed_path() / "stewart_limits.json"
    
    def create_directories(self) -> None:
        """Create necessary directories if they don't exist."""
        # Create logs directory
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        
        # Create data directories
        for client in self.clients:
            self.get_raw_path(client).mkdir(parents=True, exist_ok=True)
        
        self.get_processed_path().mkdir(parents=True, exist_ok=True)
        
        # Create to_consume directory
        (self.data_root / "to_consume").mkdir(parents=True, exist_ok=True)


# Global settings instance
_settings = None


def get_settings() -> Settings:
    """Get global settings instance (singleton pattern)."""
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.create_directories()
    return _settings
