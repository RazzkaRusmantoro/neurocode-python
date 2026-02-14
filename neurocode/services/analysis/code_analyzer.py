"""
Code analyzer service
Combines parsing and chunking to prepare code for vectorization
"""
from typing import List, Dict, Any, Optional
from neurocode.services.analysis.parser import TreeSitterParser, ParseResult
from neurocode.services.analysis.chunker import CodeChunker
from neurocode.services.analysis.chunker.models import CodeChunk


class CodeAnalyzer:
    """Analyzes code by parsing and chunking it"""
    
    def __init__(self):
        self.parser = TreeSitterParser()
        self.chunker = CodeChunker()
    
    async def analyze_and_chunk(
        self,
        files: List[Dict[str, Any]],
        chunking_strategy: str = "hybrid"
    ) -> Dict[str, Any]:
        """
        Parse files and create chunks
        
        Args:
            files: List of dicts with 'path', 'content', 'language'
            chunking_strategy: 'function', 'flow', or 'hybrid'
        
        Returns:
            Dictionary with parsed structure and chunks
        """
        # Initialize parser
        await self.parser.initialize()
        
        # Parse files
        print(f"[CodeAnalyzer] Parsing {len(files)} files...")
        parse_result = await self.parser.parse_files(files)
        
        # Store file contents for chunking
        file_contents = {f['path']: f['content'] for f in files}
        self.chunker.set_file_contents(file_contents)
        
        # Create chunks
        print(f"[CodeAnalyzer] Creating chunks with strategy: {chunking_strategy}...")
        chunks = self.chunker.create_chunks(parse_result, strategy=chunking_strategy)
        
        print(f"[CodeAnalyzer] ✓ Created {len(chunks)} chunks")
        
        # Structure output
        return {
            "repository_structure": self._build_repository_structure(parse_result),
            "symbols": self._extract_symbols_summary(parse_result),
            "dependencies": self._format_dependencies(parse_result.structure.dependencies),
            "function_usage": self._format_function_usage(parse_result.function_usage),
            "chunks": self._format_chunks(chunks),
            "metadata": {
                "totalFiles": len(files),
                "totalChunks": len(chunks),
                "languages": parse_result.metadata['languages'],
                "parseErrors": parse_result.metadata['parseErrors'],
                "totalFunctions": sum(len(f.functions) for f in parse_result.structure.files),
                "totalClasses": sum(len(f.classes) for f in parse_result.structure.files),
            }
        }
    
    def _build_repository_structure(self, parse_result: ParseResult) -> Dict[str, Any]:
        """Build repository structure with subsystems"""
        subsystems: Dict[str, List[str]] = {}
        
        for parsed_file in parse_result.structure.files:
            subsystem = self._get_subsystem(parsed_file.path)
            if subsystem not in subsystems:
                subsystems[subsystem] = []
            subsystems[subsystem].append(parsed_file.path)
        
        return {
            "subsystems": [
                {
                    "path": path,
                    "files": sorted(files),
                    "depth": 1
                }
                for path, files in sorted(subsystems.items())
            ]
        }
    
    def _extract_symbols_summary(self, parse_result: ParseResult) -> Dict[str, Any]:
        """Extract symbols summary with key snippets"""
        symbols: Dict[str, Any] = {}
        
        for parsed_file in parse_result.structure.files:
            file_symbols = {
                "functions": [
                    {
                        "name": func.name,
                        "parameters": [{"name": p.name, "type": p.type} for p in func.parameters],
                        "returnType": func.returnType,
                        "isAsync": func.isAsync,
                        "isExported": func.isExported,
                        "startLine": func.startLine,
                        "endLine": func.endLine,
                        "snippet": func.body[:500] if func.body else ""  # First 500 chars
                    }
                    for func in parsed_file.functions
                ],
                "classes": [
                    {
                        "name": cls.name,
                        "methods": [{"name": m.name, "parameters": len(m.parameters)} for m in cls.methods],
                        "properties": [{"name": p.name, "type": p.type} for p in cls.properties],
                        "extends": cls.extends,
                        "isExported": cls.isExported,
                        "startLine": cls.startLine,
                        "endLine": cls.endLine
                    }
                    for cls in parsed_file.classes
                ],
                "imports": [{"source": imp.source, "imports": imp.imports} for imp in parsed_file.imports],
                "exports": [{"name": exp.name, "type": exp.type} for exp in parsed_file.exports],
                "language": parsed_file.language
            }
            symbols[parsed_file.path] = file_symbols
        
        return symbols
    
    def _format_dependencies(self, dependencies: List[Any]) -> List[Dict[str, Any]]:
        """Format dependencies for output"""
        return [
            {
                "from": dep.from_path,
                "to": dep.to_path,
                "type": dep.type,
                "relationship": dep.relationship
            }
            for dep in dependencies
        ]
    
    def _format_function_usage(self, function_usage: Dict[str, Any]) -> Dict[str, Any]:
        """Format function usage for output"""
        return {
            func_name: {
                "definedIn": usage.definedIn,
                "calledIn": [
                    {
                        "filePath": call.filePath,
                        "line": call.line,
                        "context": call.context
                    }
                    for call in usage.calledIn
                ],
                "totalCalls": usage.totalCalls
            }
            for func_name, usage in function_usage.items()
        }
    
    def _format_chunks(self, chunks: List[CodeChunk]) -> List[Dict[str, Any]]:
        """Format chunks for output"""
        return [
            {
                "id": chunk.id,
                "type": chunk.type.value,
                "content": chunk.content,
                "metadata": {
                    "file_path": chunk.metadata.file_path,
                    "language": chunk.metadata.language,
                    "start_line": chunk.metadata.start_line,
                    "end_line": chunk.metadata.end_line,
                    "function_name": chunk.metadata.function_name,
                    "class_name": chunk.metadata.class_name,
                    "subsystem": chunk.metadata.subsystem,
                    "imports": chunk.metadata.imports,
                    "calls": chunk.metadata.calls,
                    "called_by": chunk.metadata.called_by,
                    "dependencies": chunk.metadata.dependencies,
                    "line_count": chunk.metadata.line_count
                },
                "related_chunks": chunk.related_chunks
            }
            for chunk in chunks
        ]
    
    def _get_subsystem(self, file_path: str) -> str:
        """Get subsystem (folder) for a file"""
        parts = file_path.split("/")
        if len(parts) > 1:
            return parts[0]
        return "."

