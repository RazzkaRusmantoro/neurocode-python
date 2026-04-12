from fastapi import APIRouter
from neurocode.config import mongodb_service

router = APIRouter()


@router.get("/")
async def root():
    
    return {"status": "ok", "service": "neurocode-python"}


@router.get("/health")
async def health():
    
    from neurocode.config import s3_service, llm_service, mongodb_service
    
    mongodb_status = "unknown"
    if mongodb_service:
        try:
            result = mongodb_service.check_connection()
            mongodb_status = "connected" if result.get("success") else "disconnected"
        except Exception:
            mongodb_status = "error"
    else:
        mongodb_status = "not_initialized"
    
    return {
        "status": "healthy",
        "services": {
            "s3": s3_service is not None,
            "llm": llm_service is not None,
            "mongodb": mongodb_status
        }
    }

