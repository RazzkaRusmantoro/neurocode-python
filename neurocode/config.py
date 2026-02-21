"""
Configuration and service initialization
"""
import os
from dotenv import load_dotenv

from neurocode.services.external.github_fetcher import GitHubFetcher
from neurocode.services.analysis.code_analyzer import CodeAnalyzer
from neurocode.services.storage.storage import StorageService
from neurocode.services.vector.vectorizer import Vectorizer
from neurocode.services.external.llm_service import LLMService
from neurocode.services.storage.s3_service import S3Service
from neurocode.services.storage.mongodb_service import MongoDBService

# Load environment variables
load_dotenv()

# Initialize services
github_fetcher = GitHubFetcher()
code_analyzer = CodeAnalyzer()
storage_service = StorageService(base_dir="data")

# Initialize S3 service (will fail if AWS credentials not set)
try:
    s3_service = S3Service()
    print("[S3Service] ✓ S3 service initialized")
except ValueError as e:
    print(f"[Warning] S3 service not initialized: {e}")
    s3_service = None
except Exception as e:
    print(f"[Warning] S3 service initialization failed: {e}")
    s3_service = None

# Initialize MongoDB service (will fail if MONGODB_URI not set)
try:
    mongodb_service = MongoDBService()
    print("[MongoDBService] ✓ MongoDB service initialized")
except ValueError as e:
    print(f"[Warning] MongoDB service not initialized: {e}")
    mongodb_service = None
except Exception as e:
    print(f"[Warning] MongoDB service initialization failed: {e}")
    mongodb_service = None

# Initialize tree builder (needs LLM, initialized after llm_service below)
tree_builder = None

# Load Qdrant configuration from environment
qdrant_url = os.getenv("QDRANT_URL") or None
qdrant_api_key = os.getenv("QDRANT_API_KEY") or None
qdrant_local_path = os.getenv("QDRANT_LOCAL_PATH", "data/vector_db")
embedding_model = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

vectorizer = Vectorizer(
    model_name=embedding_model,
    qdrant_url=qdrant_url,
    qdrant_api_key=qdrant_api_key,
    persist_directory=qdrant_local_path if not qdrant_url else None
)

# Initialize LLM service (will fail if ANTHROPIC_API_KEY not set)
try:
    llm_service = LLMService()
    print("[LLMService] ✓ Claude initialized")
except ValueError as e:
    print(f"[Warning] LLM service not initialized: {e}")
    llm_service = None
except Exception as e:
    print(f"[Warning] LLM service initialization failed: {e}")
    llm_service = None

# Initialize tree builder (uses LLM service)
from neurocode.services.analysis.tree_builder import TreeBuilder
try:
    if llm_service:
        tree_builder = TreeBuilder(
            llm_client=llm_service.client,
            model=llm_service.model,
            model_fast=llm_service.model_fast,
        )
        print("[TreeBuilder] ✓ Tree builder initialized (with LLM)")
    else:
        tree_builder = TreeBuilder()
        print("[TreeBuilder] ✓ Tree builder initialized (without LLM)")
except Exception as e:
    print(f"[Warning] Tree builder initialization failed: {e}")
    tree_builder = None

