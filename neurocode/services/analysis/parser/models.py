"""
Data models for parsed code structure
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel


class Parameter(BaseModel):
    """Function parameter"""
    name: str
    type: Optional[str] = None
    optional: bool = False
    defaultValue: Optional[str] = None


class MethodDefinition(BaseModel):
    """Class method definition"""
    name: str
    parameters: List[Parameter] = []
    returnType: Optional[str] = None
    isAsync: bool = False
    isPublic: bool = True
    isStatic: bool = False
    startLine: int
    endLine: int


class PropertyDefinition(BaseModel):
    """Class property definition"""
    name: str
    type: Optional[str] = None
    isPublic: bool = True
    isStatic: bool = False


class FunctionDefinition(BaseModel):
    """Function definition"""
    name: str
    parameters: List[Parameter] = []
    returnType: Optional[str] = None
    isAsync: bool = False
    isExported: bool = False
    startLine: int
    endLine: int
    body: str = ""


class ClassDefinition(BaseModel):
    """Class definition"""
    name: str
    methods: List[MethodDefinition] = []
    properties: List[PropertyDefinition] = []
    extends: Optional[str] = None
    implements: Optional[List[str]] = None
    isExported: bool = False
    startLine: int
    endLine: int


class ImportStatement(BaseModel):
    """Import statement"""
    source: str
    imports: List[str] = []
    isTypeOnly: bool = False


class ExportStatement(BaseModel):
    """Export statement"""
    name: str
    type: str  # 'function' | 'class' | 'variable' | 'default'


class Dependency(BaseModel):
    """Dependency between files"""
    from_path: str  # file path
    to_path: str  # file path or external package
    type: str  # 'import' | 'call' | 'extends' | 'implements'
    relationship: str = ""  # function name, class name, etc.


class FunctionCall(BaseModel):
    """Function call information"""
    functionName: str
    filePath: str
    line: int
    column: int
    context: Optional[str] = None  # Function/method where it's called
    isMethodCall: bool = False
    receiver: Optional[str] = None
    callType: str = "function"  # 'function' | 'method' | 'constructor'


class FunctionUsage(BaseModel):
    """Function usage tracking"""
    functionName: str
    definedIn: Optional[str] = None
    calledIn: List[FunctionCall] = []
    totalCalls: int = 0


class ParsedFile(BaseModel):
    """Parsed file structure"""
    path: str
    language: str
    functions: List[FunctionDefinition] = []
    classes: List[ClassDefinition] = []
    imports: List[ImportStatement] = []
    exports: List[ExportStatement] = []


class ParsedCodeStructure(BaseModel):
    """Complete parsed code structure"""
    files: List[ParsedFile] = []
    dependencies: List[Dependency] = []
    modules: List[Dict[str, Any]] = []

