# Pydantic models for the application API request and response
#
from pydantic import BaseModel
from typing import Optional


class DataEngineerOutput(BaseModel):
    python_script: str  # Full runnable script
    data_preview: dict  # shape, dtypes, head, null_report
    schema_status: str  # Human-readable cleaning decisions log
    output_path: str  # Path to the written clean file
    pipeline_stage: str  # Updated stage label
    target_agent: str  # "Analyst" | "Scientist" | "Supervisor"
    warnings: Optional[list]  # Any unresolved data quality flags
