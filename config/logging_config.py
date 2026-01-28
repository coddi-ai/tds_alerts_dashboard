"""
Logging configuration for Multi-Technical-Alerts.

Provides centralized logging setup with file and console handlers.
"""

import logging
from pathlib import Path
from typing import Optional


def setup_logging(
    log_file: Optional[str] = None,
    level: str = "INFO",
    log_dir: str = "logs"
) -> logging.Logger:
    """
    Configure application-wide logging.
    
    Args:
        log_file: Name of log file (if None, uses 'app.log')
        level: Logging level ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
        log_dir: Directory for log files
    
    Returns:
        Configured logger instance
    """
    # Create logs directory if it doesn't exist
    log_directory = Path(log_dir)
    log_directory.mkdir(parents=True, exist_ok=True)
    
    # Set log file path
    if log_file is None:
        log_file = "app.log"
    log_path = log_directory / log_file
    
    # Convert string level to logging constant
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    
    # Create logger
    logger = logging.getLogger("multi_technical_alerts")
    logger.setLevel(numeric_level)
    
    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    simple_formatter = logging.Formatter(
        fmt='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # File handler (detailed logging)
    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(detailed_formatter)
    logger.addHandler(file_handler)
    
    # Console handler (simple logging)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(simple_formatter)
    logger.addHandler(console_handler)
    
    logger.info(f"Logging configured: level={level}, file={log_path}")
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a specific module.
    
    Args:
        name: Logger name (typically __name__ of calling module)
    
    Returns:
        Logger instance
    """
    return logging.getLogger(f"multi_technical_alerts.{name}")
