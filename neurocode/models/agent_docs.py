"""
Pydantic models and validation for AI-Agent .md output (guide + rules bundle).

Schema is defined in:
- neurocode/services/config/agent_guide_schema.json
- neurocode/services/config/agent_rule_schema.json
- neurocode/services/config/agent_docs_bundle_schema.json

These models mirror that schema so we can validate LLM output before rendering to .md.
"""
from typing import Optional, List
from pydantic import BaseModel, Field


class AgentGuideHowToUseItem(BaseModel):
    """Single entry in the guide's 'How to use' list (path + description)."""
    path: str = Field(..., description="Path to rule .md, e.g. 'rules/timing.md'")
    description: str = Field(..., description="One-line description of what the rule covers")


class AgentGuideTopicPointer(BaseModel):
    """Optional section in the guide that points to a specific rule file."""
    title: str = Field(..., description="Section heading, e.g. 'Captions'")
    body: str = Field(..., description="One sentence + instruction to load the rule file")
    rule_path: str = Field(..., description="Path to the rule .md, e.g. 'rules/subtitles.md'")


class AgentGuideMetadata(BaseModel):
    tags: Optional[List[str]] = Field(default_factory=list, description="Tags for discovery")


class AgentGuide(BaseModel):
    """Main guide .md (e.g. GUIDE.md): explains what the folder is for and how to use each rule .md."""
    name: str = Field(..., description="Slug for the filename, e.g. 'guide' (without .md)")
    description: str = Field(..., description="Short description for frontmatter")
    metadata: Optional[AgentGuideMetadata] = None
    when_to_use: str = Field(..., description="Body text for the 'When to use' section")
    topic_pointers: Optional[List[AgentGuideTopicPointer]] = Field(default_factory=list)
    how_to_use: List[AgentGuideHowToUseItem] = Field(
        ...,
        min_length=1,
        description="List of rule files with descriptions (main index of all rule .mds)",
    )


class AgentRuleMetadata(BaseModel):
    tags: Optional[List[str]] = Field(default_factory=list)


class AgentRule(BaseModel):
    """Single rule/playbook .md: role, description, prerequisites, body, optional input/output."""
    name: str = Field(..., description="Slug for the filename, e.g. 'timing' (without .md)")
    description: str = Field(..., description="Short description for frontmatter")
    metadata: Optional[AgentRuleMetadata] = None
    role: Optional[str] = Field(None, description="Optional: what is the role of this .md")
    prerequisites: Optional[List[str]] = Field(default_factory=list)
    body: str = Field(..., description="Main markdown content (playbook)")
    input: Optional[str] = Field(None, description="Optional input section")
    output: Optional[str] = Field(None, description="Optional output section")


class AgentDocsBundle(BaseModel):
    """Bundle of AI-Agent .md files: one main guide + N rule/playbook .mds."""
    guide: AgentGuide
    rules: List[AgentRule] = Field(..., min_length=1)
