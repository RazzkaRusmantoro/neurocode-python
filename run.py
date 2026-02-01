#!/usr/bin/env python3
"""
Simple script to run the NeuroCode Python service
"""
import uvicorn
import os

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("ENV", "development") == "development"
    
    print(f"Starting NeuroCode Python service on {host}:{port}")
    print(f"Environment: {os.getenv('ENV', 'development')}")
    print(f"Auto-reload: {reload}")
    
    uvicorn.run(
        "neurocode.main:app",
        host=host,
        port=port,
        reload=reload
    )

