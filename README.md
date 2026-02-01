# NeuroCode Python Service

Basic Python FastAPI service setup for NeuroCode.

## Setup

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Run the Service

```bash
python run.py
```

Or:

```bash
python -m neurocode.main
```

The service will be available at `http://localhost:8000`

## API Endpoints

- `GET /` - Health check
- `GET /health` - Health check

## Configuration

Environment variables:
- `PORT` - Server port (default: 8000)
- `HOST` - Server host (default: 0.0.0.0)
- `ENV` - Environment (default: development)
- `CORS_ORIGINS` - Comma-separated list of allowed origins (default: http://localhost:3000,http://127.0.0.1:3000)
