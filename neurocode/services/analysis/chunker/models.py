from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from enum import Enum


class ChunkType(str, Enum):
    
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"                
    CONSTANT = "constant"                                     
    ROUTE = "route"                                                 
    DEFAULT_EXPORT = "default_export"                      
    FLOW = "flow"                                     
    FILE = "file"                                               
    SUBSYSTEM = "subsystem"                            


class CodeChunk(BaseModel):
    
    id: str                   
    type: ChunkType
    content: str                           
    metadata: 'ChunkMetadata'
    related_chunks: List[str] = []                         


class ChunkMetadata(BaseModel):
    
    file_path: str
    language: str
    start_line: int
    end_line: int
    
                        
    function_name: Optional[str] = None
    class_name: Optional[str] = None
    method_name: Optional[str] = None
    
                         
    subsystem: Optional[str] = None
    imports: List[str] = []
    exports: List[str] = []
    
                   
    calls: List[str] = []                              
    called_by: List[str] = []                            
    dependencies: List[str] = []                         
    
                         
    line_count: int = 0
    complexity_score: Optional[float] = None                           


                          
CodeChunk.model_rebuild()

