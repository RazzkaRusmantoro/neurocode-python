from typing import List, Optional, Dict, Any
from pydantic import BaseModel


class Parameter(BaseModel):
    
    name: str
    type: Optional[str] = None
    optional: bool = False
    defaultValue: Optional[str] = None


class MethodDefinition(BaseModel):
    
    name: str
    parameters: List[Parameter] = []
    returnType: Optional[str] = None
    isAsync: bool = False
    isPublic: bool = True
    isStatic: bool = False
    startLine: int
    endLine: int


class PropertyDefinition(BaseModel):
    
    name: str
    type: Optional[str] = None
    isPublic: bool = True
    isStatic: bool = False


class FunctionDefinition(BaseModel):
    
    name: str
    parameters: List[Parameter] = []
    returnType: Optional[str] = None
    isAsync: bool = False
    isExported: bool = False
    startLine: int
    endLine: int
    body: str = ""


class ClassDefinition(BaseModel):
    
    name: str
    methods: List[MethodDefinition] = []
    properties: List[PropertyDefinition] = []
    extends: Optional[str] = None
    implements: Optional[List[str]] = None
    isExported: bool = False
    startLine: int
    endLine: int


class ImportStatement(BaseModel):
    
    source: str
    imports: List[str] = []
    isTypeOnly: bool = False


class ExportStatement(BaseModel):
    
    name: str
    type: str                                                 


class ConstantDefinition(BaseModel):
    
    name: str
    startLine: int
    endLine: int
    valueType: str = "object"                                  
    isExported: bool = False


class RouteDefinition(BaseModel):
    
    path: str
    method: str                                                       
    receiver: Optional[str] = None                        
    startLine: int
    endLine: int


class DefaultExportDefinition(BaseModel):
    
    startLine: int
    endLine: int


class Dependency(BaseModel):
    
    from_path: str             
    to_path: str                                 
    type: str                                                
    relationship: str = ""                                   


class FunctionCall(BaseModel):
    
    functionName: str
    filePath: str
    line: int
    column: int
    context: Optional[str] = None                                     
    isMethodCall: bool = False
    receiver: Optional[str] = None
    callType: str = "function"                                         


class FunctionUsage(BaseModel):
    
    functionName: str
    definedIn: Optional[str] = None
    calledIn: List[FunctionCall] = []
    totalCalls: int = 0


class ParsedFile(BaseModel):
    
    path: str
    language: str
    functions: List[FunctionDefinition] = []
    classes: List[ClassDefinition] = []
    constants: List[ConstantDefinition] = []
    routes: List[RouteDefinition] = []
    default_exports: List[DefaultExportDefinition] = []
    imports: List[ImportStatement] = []
    exports: List[ExportStatement] = []


class ParsedCodeStructure(BaseModel):
    
    files: List[ParsedFile] = []
    dependencies: List[Dependency] = []
    modules: List[Dict[str, Any]] = []

