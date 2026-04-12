from typing import Optional, List
from pydantic import BaseModel, Field


class AgentGuideHowToUseItem(BaseModel):
    
    path: str = Field(..., description="Path to rule .md, e.g. 'rules/timing.md'")
    description: str = Field(..., description="One-line description of what the rule covers")


class AgentGuideTopicPointer(BaseModel):
    
    title: str = Field(..., description="Section heading, e.g. 'Captions'")
    body: str = Field(..., description="One sentence + instruction to load the rule file")
    rule_path: str = Field(..., description="Path to the rule .md, e.g. 'rules/subtitles.md'")


class AgentGuideMetadata(BaseModel):
    tags: Optional[List[str]] = Field(default_factory=list, description="Tags for discovery")


class AgentGuide(BaseModel):
    
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
    
    name: str = Field(..., description="Slug for the filename, e.g. 'timing' (without .md)")
    description: str = Field(..., description="Short description for frontmatter")
    metadata: Optional[AgentRuleMetadata] = None
    role: Optional[str] = Field(None, description="Optional: what is the role of this .md")
    prerequisites: Optional[List[str]] = Field(default_factory=list)
    body: str = Field(..., description="Main markdown content (playbook)")
    input: Optional[str] = Field(None, description="Optional input section")
    output: Optional[str] = Field(None, description="Optional output section")


class AgentDocsBundle(BaseModel):
    
    guide: AgentGuide
    rules: List[AgentRule] = Field(..., min_length=1)
