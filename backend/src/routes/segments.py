from fastapi import APIRouter, Depends, Query
from src.config.database import get_db
from src.utils.auth import current_user
from src.controllers.segment_controller import list_segments
from src.schemas.segment import SegmentSummary
from src.schemas.comparison import ComparisonResult
from src.services.comparison_service import compare_runs
router=APIRouter(prefix="/segments")
@router.get("", response_model=list[SegmentSummary])
def index(run_id:int|None=None,db=Depends(get_db),user=Depends(current_user)):
    return list_segments(db,run_id)
@router.get("/compare", response_model=ComparisonResult)
def compare(run_a:int=Query(),run_b:int=Query(),db=Depends(get_db),user=Depends(current_user)):
    return compare_runs(db,run_a,run_b)
