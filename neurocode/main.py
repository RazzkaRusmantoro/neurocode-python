"""
FastAPI server for NeuroCode Python backend
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Import routes
from neurocode.routes import health, mongodb, github, documentation, pull_request, visual_tree, internal, chat

app = FastAPI(
    title="NeuroCode Python API",
    description="Python backend service for NeuroCode",
    version="0.1.0"
)

# Configure CORS to allow requests from Next.js
# Get CORS origins from environment or use defaults
cors_origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in cors_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(health.router)
app.include_router(mongodb.router)
app.include_router(github.router)
app.include_router(documentation.router)
app.include_router(pull_request.router)
app.include_router(visual_tree.router)
app.include_router(internal.router)
app.include_router(chat.router)

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("ENV", "development") == "development"
    
    uvicorn.run(
        "neurocode.main:app",
        host=host,
        port=port,
        reload=reload
    )
