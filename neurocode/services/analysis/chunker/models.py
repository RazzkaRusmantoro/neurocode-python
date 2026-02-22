"""
Models for code chunks
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from enum import Enum


class ChunkType(str, Enum):
    """Type of code chunk"""
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"  # Class method
    CONSTANT = "constant"  # Top-level constant (object/array)
    ROUTE = "route"  # Route definition (router.get, app.post, etc.)
    DEFAULT_EXPORT = "default_export"  # export default ...
    FLOW = "flow"  # Related functions in a call chain
    FILE = "file"  # Entire file (fallback when no other chunks)
    SUBSYSTEM = "subsystem"  # All files in a subsystem


class CodeChunk(BaseModel):
    """A chunk of code for vectorization"""
    id: str  # Unique chunk ID
    type: ChunkType
    content: str  # The actual code content
    metadata: 'ChunkMetadata'
    related_chunks: List[str] = []  # IDs of related chunks


class ChunkMetadata(BaseModel):
    """Metadata for a code chunk"""
    file_path: str
    language: str
    start_line: int
    end_line: int
    
    # Symbol information
    function_name: Optional[str] = None
    class_name: Optional[str] = None
    method_name: Optional[str] = None
    
    # Context information
    subsystem: Optional[str] = None
    imports: List[str] = []
    exports: List[str] = []
    
    # Relationships
    calls: List[str] = []  # Functions this chunk calls
    called_by: List[str] = []  # Functions that call this
    dependencies: List[str] = []  # Files this depends on
    
    # Additional metadata
    line_count: int = 0
    complexity_score: Optional[float] = None  # Can be calculated later


# Update forward reference
CodeChunk.model_rebuild()

