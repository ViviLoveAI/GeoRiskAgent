"""FastAPI backend for GeoRisk Transmission Analyzer."""

from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.pipeline import run_pipeline
from src.report_formatter import format_concise_report
from src.schemas import FinalReport


app = FastAPI(
    title="GeoRisk Transmission Analyzer API",
    description=(
        "Geopolitical risk exposure discovery API. This service does not "
        "predict stock prices or provide investment advice."
    ),
)


class AnalyzeRequest(BaseModel):
    """Request body for risk transmission analysis."""

    news_text: str = Field(..., description="Geopolitical news headline or article.")
    top_k: int = Field(default=3, ge=1, le=20)
    output_format: Literal["json", "concise"] = "json"


class ConciseAnalyzeResponse(BaseModel):
    """Concise markdown report response."""

    report: str


@app.get("/health")
def health() -> dict[str, str]:
    """Return API health status."""

    return {"status": "ok"}


@app.post("/analyze", response_model=FinalReport | ConciseAnalyzeResponse)
def analyze(request: AnalyzeRequest) -> FinalReport | ConciseAnalyzeResponse:
    """Run the GeoRisk pipeline for a geopolitical news item."""

    if not request.news_text.strip():
        raise HTTPException(status_code=400, detail="news_text must not be empty.")

    try:
        report = run_pipeline(request.news_text, top_k=request.top_k)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Pipeline execution failed. Please check server logs.",
        ) from exc

    if request.output_format == "concise":
        return ConciseAnalyzeResponse(report=format_concise_report(report))

    return report
