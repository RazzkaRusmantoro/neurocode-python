from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict
from neurocode.services.analysis.parser.models import (
    ParsedCodeStructure,
    ParsedFile,
    FunctionDefinition,
    ClassDefinition,
    Dependency,
    FunctionUsage,
)
from neurocode.services.analysis.chunker.models import CodeChunk, ChunkMetadata, ChunkType


class CodeChunker:
    
    
    def __init__(self):
        self.file_contents: Dict[str, str] = {}                           
    
    def set_file_contents(self, file_contents: Dict[str, str]):
        
        self.file_contents = file_contents
    
    def create_chunks(
        self,
        parse_result: Any,                           
        strategy: str = "hybrid"
    ) -> List[CodeChunk]:
        
        structure = parse_result.structure
        function_usage = parse_result.function_usage
        
        chunks: List[CodeChunk] = []
        
        if strategy == "function":
            chunks = self._create_function_chunks(structure, function_usage)
        elif strategy == "flow":
            chunks = self._create_flow_chunks(structure, function_usage)
        elif strategy == "hybrid":
            chunks = self._create_hybrid_chunks(structure, function_usage)
        else:
            raise ValueError(f"Unknown chunking strategy: {strategy}")
        
                             
        self._link_related_chunks(chunks, structure, function_usage)
        
        return chunks
    
    def _create_function_chunks(
        self,
        structure: ParsedCodeStructure,
        function_usage: Dict[str, FunctionUsage]
    ) -> List[CodeChunk]:
        
        chunks: List[CodeChunk] = []
        
        for parsed_file in structure.files:
            file_content = self.file_contents.get(parsed_file.path, "")
            lines = file_content.splitlines()
            
                                 
            for func in parsed_file.functions:
                chunk_id = f"{parsed_file.path}:{func.name}"
                
                                   
                func_code = self._extract_function_code(
                    lines, func.startLine, func.endLine
                )
                
                              
                calls = self._get_function_calls(func.name, parsed_file.path, function_usage)
                called_by = self._get_called_by(func.name, parsed_file.path, function_usage)
                dependencies = self._get_file_dependencies(parsed_file.path, structure.dependencies)
                
                chunk = CodeChunk(
                    id=chunk_id,
                    type=ChunkType.FUNCTION,
                    content=func_code,
                    metadata=ChunkMetadata(
                        file_path=parsed_file.path,
                        language=parsed_file.language,
                        start_line=func.startLine,
                        end_line=func.endLine,
                        function_name=func.name,
                        subsystem=self._get_subsystem(parsed_file.path),
                        imports=[imp.source for imp in parsed_file.imports],
                        exports=[exp.name for exp in parsed_file.exports if exp.name == func.name],
                        calls=calls,
                        called_by=called_by,
                        dependencies=dependencies,
                        line_count=func.endLine - func.startLine + 1
                    ),
                    related_chunks=[]
                )
                chunks.append(chunk)
            
                                                                 
            for cls in parsed_file.classes:
                chunk_id = f"{parsed_file.path}:{cls.name}"
                class_code = self._extract_function_code(
                    lines, cls.startLine, cls.endLine
                )
                method_names = [m.name for m in cls.methods]
                chunk = CodeChunk(
                    id=chunk_id,
                    type=ChunkType.CLASS,
                    content=class_code,
                    metadata=ChunkMetadata(
                        file_path=parsed_file.path,
                        language=parsed_file.language,
                        start_line=cls.startLine,
                        end_line=cls.endLine,
                        class_name=cls.name,
                        subsystem=self._get_subsystem(parsed_file.path),
                        imports=[imp.source for imp in parsed_file.imports],
                        exports=[exp.name for exp in parsed_file.exports if exp.name == cls.name],
                        calls=method_names,
                        dependencies=self._get_file_dependencies(parsed_file.path, structure.dependencies),
                        line_count=cls.endLine - cls.startLine + 1
                    ),
                    related_chunks=[]
                )
                chunks.append(chunk)
                                            
                for method in cls.methods:
                    method_id = f"{parsed_file.path}:{cls.name}.{method.name}"
                    method_code = self._extract_function_code(
                        lines, method.startLine, method.endLine
                    )
                    chunks.append(CodeChunk(
                        id=method_id,
                        type=ChunkType.METHOD,
                        content=method_code,
                        metadata=ChunkMetadata(
                            file_path=parsed_file.path,
                            language=parsed_file.language,
                            start_line=method.startLine,
                            end_line=method.endLine,
                            function_name=method.name,
                            class_name=cls.name,
                            method_name=method.name,
                            subsystem=self._get_subsystem(parsed_file.path),
                            imports=[imp.source for imp in parsed_file.imports],
                            exports=[],
                            calls=[],
                            called_by=[],
                            dependencies=self._get_file_dependencies(parsed_file.path, structure.dependencies),
                            line_count=method.endLine - method.startLine + 1
                        ),
                        related_chunks=[]
                    ))
            
                                                          
            for const in getattr(parsed_file, 'constants', []):
                chunk_id = f"{parsed_file.path}:{const.name}"
                const_code = self._extract_function_code(
                    lines, const.startLine, const.endLine
                )
                chunks.append(CodeChunk(
                    id=chunk_id,
                    type=ChunkType.CONSTANT,
                    content=const_code,
                    metadata=ChunkMetadata(
                        file_path=parsed_file.path,
                        language=parsed_file.language,
                        start_line=const.startLine,
                        end_line=const.endLine,
                        function_name=const.name,
                        subsystem=self._get_subsystem(parsed_file.path),
                        imports=[imp.source for imp in parsed_file.imports],
                        exports=[const.name] if const.isExported else [],
                        calls=[],
                        called_by=[],
                        dependencies=[],
                        line_count=const.endLine - const.startLine + 1
                    ),
                    related_chunks=[]
                ))

                                                           
            for i, route in enumerate(getattr(parsed_file, 'routes', [])):
                chunk_id = f"{parsed_file.path}:route:{route.method}:{i}"
                route_code = self._extract_function_code(
                    lines, route.startLine, route.endLine
                )
                chunks.append(CodeChunk(
                    id=chunk_id,
                    type=ChunkType.ROUTE,
                    content=route_code,
                    metadata=ChunkMetadata(
                        file_path=parsed_file.path,
                        language=parsed_file.language,
                        start_line=route.startLine,
                        end_line=route.endLine,
                        function_name=f"{route.method} {route.path}",
                        subsystem=self._get_subsystem(parsed_file.path),
                        imports=[imp.source for imp in parsed_file.imports],
                        exports=[],
                        calls=[],
                        called_by=[],
                        dependencies=[],
                        line_count=route.endLine - route.startLine + 1
                    ),
                    related_chunks=[]
                ))

                                                            
            for i, default_exp in enumerate(getattr(parsed_file, 'default_exports', [])):
                chunk_id = f"{parsed_file.path}:default_export:{i}"
                default_code = self._extract_function_code(
                    lines, default_exp.startLine, default_exp.endLine
                )
                chunks.append(CodeChunk(
                    id=chunk_id,
                    type=ChunkType.DEFAULT_EXPORT,
                    content=default_code,
                    metadata=ChunkMetadata(
                        file_path=parsed_file.path,
                        language=parsed_file.language,
                        start_line=default_exp.startLine,
                        end_line=default_exp.endLine,
                        subsystem=self._get_subsystem(parsed_file.path),
                        imports=[imp.source for imp in parsed_file.imports],
                        exports=[],
                        calls=[],
                        called_by=[],
                        dependencies=[],
                        line_count=default_exp.endLine - default_exp.startLine + 1
                    ),
                    related_chunks=[]
                ))

                                                                                                
            file_chunk_count = (
                len(parsed_file.functions)
                + len(parsed_file.classes)
                + sum(len(c.methods) for c in parsed_file.classes)
                + len(getattr(parsed_file, 'constants', []))
                + len(getattr(parsed_file, 'routes', []))
                + len(getattr(parsed_file, 'default_exports', []))
            )
            if file_chunk_count == 0 and file_content:
                chunk_id = f"{parsed_file.path}:file"
                chunks.append(CodeChunk(
                    id=chunk_id,
                    type=ChunkType.FILE,
                    content=file_content,
                    metadata=ChunkMetadata(
                        file_path=parsed_file.path,
                        language=parsed_file.language,
                        start_line=1,
                        end_line=len(lines),
                        subsystem=self._get_subsystem(parsed_file.path),
                        imports=[imp.source for imp in parsed_file.imports],
                        exports=[exp.name for exp in parsed_file.exports],
                        calls=[],
                        called_by=[],
                        dependencies=self._get_file_dependencies(parsed_file.path, structure.dependencies),
                        line_count=len(lines)
                    ),
                    related_chunks=[]
                ))
        
        return chunks
    
    def _create_flow_chunks(
        self,
        structure: ParsedCodeStructure,
        function_usage: Dict[str, FunctionUsage]
    ) -> List[CodeChunk]:
        
        chunks: List[CodeChunk] = []
        
                          
        call_graph = self._build_call_graph(structure, function_usage)
        
                                                           
        processed = set()
        
        for parsed_file in structure.files:
            file_content = self.file_contents.get(parsed_file.path, "")
            lines = file_content.splitlines()
            
            for func in parsed_file.functions:
                func_id = f"{parsed_file.path}:{func.name}"
                
                if func_id in processed:
                    continue
                
                                                       
                flow_functions = self._get_flow_chain(func_id, call_graph, structure)
                
                if len(flow_functions) == 1:
                                                                    
                    chunk = self._create_single_function_chunk(
                        func, parsed_file, lines, structure, function_usage
                    )
                    chunks.append(chunk)
                    processed.add(func_id)
                else:
                                                                   
                    flow_content = []
                    flow_metadata = []
                    
                    for flow_func_id in flow_functions:
                        flow_func, flow_file = self._find_function_by_id(
                            flow_func_id, structure
                        )
                        if flow_func and flow_file:
                            flow_file_content = self.file_contents.get(flow_file.path, "")
                            flow_file_lines = flow_file_content.splitlines()
                            func_code = self._extract_function_code(
                                flow_file_lines, flow_func.startLine, flow_func.endLine
                            )
                            flow_content.append(f"// {flow_file.path}:{flow_func.name}\n{func_code}")
                            flow_metadata.append({
                                "file": flow_file.path,
                                "function": flow_func.name,
                                "lines": f"{flow_func.startLine}-{flow_func.endLine}"
                            })
                            processed.add(flow_func_id)
                    
                                       
                    chunk_id = f"flow:{func_id}"
                    chunk = CodeChunk(
                        id=chunk_id,
                        type=ChunkType.FLOW,
                        content="\n\n".join(flow_content),
                        metadata=ChunkMetadata(
                            file_path=parsed_file.path,
                            language=parsed_file.language,
                            start_line=func.startLine,
                            end_line=func.endLine,
                            function_name=func.name,
                            subsystem=self._get_subsystem(parsed_file.path),
                            imports=[imp.source for imp in parsed_file.imports],
                            calls=[f["function"] for f in flow_metadata[1:]],                         
                            dependencies=self._get_file_dependencies(parsed_file.path, structure.dependencies),
                            line_count=sum(len(c.splitlines()) for c in flow_content)
                        ),
                        related_chunks=[f"{f['file']}:{f['function']}" for f in flow_metadata]
                    )
                    chunks.append(chunk)
        
        return chunks
    
    def _create_hybrid_chunks(
        self,
        structure: ParsedCodeStructure,
        function_usage: Dict[str, FunctionUsage]
    ) -> List[CodeChunk]:
        
                             
        function_chunks = self._create_function_chunks(structure, function_usage)
        
                                           
        flow_chunks = self._create_flow_chunks(structure, function_usage)
        
                                                          
        chunk_map = {chunk.id: chunk for chunk in function_chunks}
        
        for flow_chunk in flow_chunks:
                                                                      
            for related_id in flow_chunk.related_chunks:
                if related_id in chunk_map:
                    del chunk_map[related_id]
            chunk_map[flow_chunk.id] = flow_chunk
        
        return list(chunk_map.values())
    
    def _create_single_function_chunk(
        self,
        func: FunctionDefinition,
        parsed_file: ParsedFile,
        lines: List[str],
        structure: ParsedCodeStructure,
        function_usage: Dict[str, FunctionUsage]
    ) -> CodeChunk:
        
        chunk_id = f"{parsed_file.path}:{func.name}"
        func_code = self._extract_function_code(lines, func.startLine, func.endLine)
        
        calls = self._get_function_calls(func.name, parsed_file.path, function_usage)
        called_by = self._get_called_by(func.name, parsed_file.path, function_usage)
        dependencies = self._get_file_dependencies(parsed_file.path, structure.dependencies)
        
        return CodeChunk(
            id=chunk_id,
            type=ChunkType.FUNCTION,
            content=func_code,
            metadata=ChunkMetadata(
                file_path=parsed_file.path,
                language=parsed_file.language,
                start_line=func.startLine,
                end_line=func.endLine,
                function_name=func.name,
                subsystem=self._get_subsystem(parsed_file.path),
                imports=[imp.source for imp in parsed_file.imports],
                exports=[exp.name for exp in parsed_file.exports if exp.name == func.name],
                calls=calls,
                called_by=called_by,
                dependencies=dependencies,
                line_count=func.endLine - func.startLine + 1
            ),
            related_chunks=[]
        )
    
    def _extract_function_code(self, lines: List[str], start_line: int, end_line: int) -> str:
        
                                     
        start_idx = max(0, start_line - 1)
        end_idx = min(len(lines), end_line)
        return "\n".join(lines[start_idx:end_idx])
    
    def _get_subsystem(self, file_path: str) -> str:
        
        parts = file_path.split("/")
        if len(parts) > 1:
            return parts[0]
        return "."
    
    def _get_function_calls(
        self,
        function_name: str,
        file_path: str,
        function_usage: Dict[str, FunctionUsage]
    ) -> List[str]:
        
                                                                                   
                                                                                           
                                                          
        calls = []
        for func_name, usage in function_usage.items():
            for call in usage.calledIn:
                if call.filePath == file_path and call.context == function_name:
                                                   
                    calls.append(func_name)
        return calls
    
    def _get_called_by(
        self,
        function_name: str,
        file_path: str,
        function_usage: Dict[str, FunctionUsage]
    ) -> List[str]:
        
        if function_name in function_usage:
            usage = function_usage[function_name]
            return [f"{call.filePath}:{call.context or 'unknown'}" for call in usage.calledIn]
        return []
    
    def _get_file_dependencies(
        self,
        file_path: str,
        dependencies: List[Dependency]
    ) -> List[str]:
        
        deps = []
        for dep in dependencies:
            if dep.from_path == file_path:
                deps.append(dep.to_path)
        return deps
    
    def _build_call_graph(
        self,
        structure: ParsedCodeStructure,
        function_usage: Dict[str, FunctionUsage]
    ) -> Dict[str, List[str]]:
        
        graph: Dict[str, List[str]] = defaultdict(list)
        
        for parsed_file in structure.files:
            for func in parsed_file.functions:
                func_id = f"{parsed_file.path}:{func.name}"
                                                              
                                                      
                if func.name in function_usage:
                    usage = function_usage[func.name]
                    for call in usage.calledIn:
                                                           
                        caller_id = f"{call.filePath}:{call.context or 'unknown'}"
                        graph[caller_id].append(func_id)
        
        return dict(graph)
    
    def _get_flow_chain(
        self,
        start_func_id: str,
        call_graph: Dict[str, List[str]],
        structure: ParsedCodeStructure
    ) -> List[str]:
        
        chain = [start_func_id]
        visited = {start_func_id}
        
                                           
        queue = [start_func_id]
        while queue:
            current = queue.pop(0)
            if current in call_graph:
                for called_func in call_graph[current]:
                    if called_func not in visited:
                        visited.add(called_func)
                        chain.append(called_func)
                        queue.append(called_func)
        
        return chain
    
    def _find_function_by_id(
        self,
        func_id: str,
        structure: ParsedCodeStructure
    ) -> Tuple[Optional[FunctionDefinition], Optional[ParsedFile]]:
        
        if ":" not in func_id:
            return None, None
        
        file_path, func_name = func_id.rsplit(":", 1)
        
        for parsed_file in structure.files:
            if parsed_file.path == file_path:
                for func in parsed_file.functions:
                    if func.name == func_name:
                        return func, parsed_file
        
        return None, None
    
    def _link_related_chunks(
        self,
        chunks: List[CodeChunk],
        structure: ParsedCodeStructure,
        function_usage: Dict[str, FunctionUsage]
    ):
        
        chunk_map = {chunk.id: chunk for chunk in chunks}
        
        for chunk in chunks:
            related = []
            
                                 
            for called_func in chunk.metadata.calls:
                                                     
                for other_chunk in chunks:
                    if other_chunk.metadata.function_name == called_func:
                        related.append(other_chunk.id)
            
                                        
            for dep_file in chunk.metadata.dependencies:
                                                 
                for other_chunk in chunks:
                    if other_chunk.metadata.file_path == dep_file:
                        related.append(other_chunk.id)
            
                                     
            for caller in chunk.metadata.called_by:
                if ":" in caller:
                    file_path, func_name = caller.rsplit(":", 1)
                    for other_chunk in chunks:
                        if (other_chunk.metadata.file_path == file_path and
                            other_chunk.metadata.function_name == func_name):
                            related.append(other_chunk.id)
            
            chunk.related_chunks = list(set(related))                     

