import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from pydantic import ValidationError

from neurocode.models.agent_docs import AgentDocsBundle


def _config_dir() -> Path:
    return Path(__file__).parent / "config"


def load_agent_bundle_schema() -> Dict[str, Any]:
    
    path = _config_dir() / "agent_docs_bundle_schema.json"
    if not path.exists():
        raise FileNotFoundError(f"Schema not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_agent_docs_bundle(data: Dict[str, Any]) -> Tuple[bool, Optional[AgentDocsBundle], str]:
    
    try:
        bundle = AgentDocsBundle.model_validate(data)
        return True, bundle, ""
    except ValidationError as e:
        return False, None, e.json(indent=2)
    except Exception as e:
        return False, None, str(e)


def validate_and_parse_agent_docs_bundle(data: Dict[str, Any]) -> AgentDocsBundle:
    
    ok, bundle, msg = validate_agent_docs_bundle(data)
    if not ok:
        raise ValueError(f"Agent docs bundle validation failed: {msg}")
    return bundle
