"""
Validation for AI-Agent .md bundle (guide + rules).

Use this to:
1. Validate LLM output (dict) against the agent docs schema (Pydantic).
2. Load the JSON schema for the bundle to inject into LLM prompts so output conforms.

Schema files (in services/config/):
- agent_guide_schema.json
- agent_rule_schema.json
- agent_docs_bundle_schema.json
"""
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from pydantic import ValidationError

from neurocode.models.agent_docs import AgentDocsBundle


def _config_dir() -> Path:
    return Path(__file__).parent / "config"


def load_agent_bundle_schema() -> Dict[str, Any]:
    """Load the agent_docs_bundle_schema.json (for LLM prompt injection)."""
    path = _config_dir() / "agent_docs_bundle_schema.json"
    if not path.exists():
        raise FileNotFoundError(f"Schema not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_agent_docs_bundle(data: Dict[str, Any]) -> Tuple[bool, Optional[AgentDocsBundle], str]:
    """
    Validate a dict (e.g. parsed LLM output) against the agent docs bundle schema.

    Returns:
        (success, validated_bundle_or_none, error_message)
    """
    try:
        bundle = AgentDocsBundle.model_validate(data)
        return True, bundle, ""
    except ValidationError as e:
        return False, None, e.json(indent=2)
    except Exception as e:
        return False, None, str(e)


def validate_and_parse_agent_docs_bundle(data: Dict[str, Any]) -> AgentDocsBundle:
    """
    Validate and return the parsed bundle. Raises ValueError with validation details on failure.
    """
    ok, bundle, msg = validate_agent_docs_bundle(data)
    if not ok:
        raise ValueError(f"Agent docs bundle validation failed: {msg}")
    return bundle
