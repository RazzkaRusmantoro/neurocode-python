from fastapi import APIRouter, HTTPException
from neurocode.config import mongodb_service

router = APIRouter()


@router.get("/api/test-mongodb")
async def test_mongodb():
    
    from neurocode.config import mongodb_service
    
    if mongodb_service is None:
        raise HTTPException(
            status_code=503,
            detail="MongoDB service not initialized. Please set MONGODB_URI in environment variables."
        )
    
    try:
        result = mongodb_service.check_connection()
        if result.get("success"):
            return result
        else:
            raise HTTPException(
                status_code=500,
                detail=result.get("error", "MongoDB connection failed")
            )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to test MongoDB connection: {str(e)}"
        )

