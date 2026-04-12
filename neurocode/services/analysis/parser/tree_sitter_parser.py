from typing import List, Dict, Optional, Any
from tree_sitter import Parser, Node
from neurocode.services.analysis.parser.language_support import (
    detect_language,
    is_language_supported,
    get_language_grammar,
    initialize_parser,
)
from neurocode.services.analysis.parser.symbol_extractor import (
    extract_functions,
    extract_classes,
    extract_constants,
    extract_exports,
    extract_routes,
    extract_default_exports,
)
from neurocode.services.analysis.parser.dependency_extractor import (
    extract_imports,
    extract_inheritance,
)
from neurocode.services.analysis.parser.call_extractor import (
    extract_function_calls,
    build_usage_map,
    create_call_dependencies,
)
from neurocode.services.analysis.parser.models import (
    ParsedCodeStructure,
    ParsedFile,
    Dependency,
    FunctionCall,
    FunctionUsage,
)


class ParseError:
    
    def __init__(self, file_path: str, error: str, language: Optional[str] = None):
        self.file_path = file_path
        self.error = error
        self.language = language


class ParseResult:
    
    def __init__(
        self,
        structure: ParsedCodeStructure,
        errors: List[ParseError],
        function_usage: Dict[str, FunctionUsage],
        metadata: Dict[str, Any]
    ):
        self.structure = structure
        self.errors = errors
        self.function_usage = function_usage
        self.metadata = metadata


class TreeSitterParser:
    
    
    def __init__(self):
        self.parsers: Dict[str, Parser] = {}                              
        self.initialized = False
    
    async def initialize(self) -> None:
        
        if self.initialized:
            return
        
        print('[TreeSitterParser] Initializing parser...')
                                                       
        self.initialized = True
        print('[TreeSitterParser] ✓ Parser initialized')
    
    async def parse_file(
        self,
        path: str,
        content: str,
        language: Optional[str] = None
    ) -> Optional[ParsedFile]:
        
        if not self.initialized:
            await self.initialize()
        
                         
        detected_lang = detect_language(path, language)
        if not detected_lang or not is_language_supported(detected_lang):
            print(f'[TreeSitterParser] Unsupported language for {path}: {language or "unknown"}')
            return None
        
        try:
                                            
            grammar = get_language_grammar(detected_lang)
            if not grammar:
                print(
                    f'[TreeSitterParser] Failed to load grammar for {detected_lang}. '
                    f'Make sure tree-sitter-{detected_lang} is installed.'
                )
                return None
            
                                                                 
            from tree_sitter import Language
            if not isinstance(grammar, Language):
                try:
                    grammar = Language(grammar)
                except Exception as e:
                    print(f'[TreeSitterParser] Failed to convert grammar to Language: {e}')
                    return None
            
                                                                         
            if detected_lang not in self.parsers:
                parser = Parser(grammar)
                self.parsers[detected_lang] = parser
            
            parser = self.parsers[detected_lang]
            
                            
            source_code = content.encode('utf-8')
            tree = parser.parse(source_code)
            if not tree:
                print(f'[TreeSitterParser] Failed to parse {path}')
                return None
            
            root_node = tree.root_node
            
                             
            functions = extract_functions(root_node, detected_lang, source_code)
            classes = extract_classes(root_node, detected_lang, source_code)
            constants = extract_constants(root_node, detected_lang, source_code)
            exports = extract_exports(root_node, detected_lang, source_code)
            routes = extract_routes(root_node, detected_lang, source_code)
            default_exports = extract_default_exports(root_node, detected_lang, source_code)
            
                                  
            imports, dependencies = extract_imports(root_node, detected_lang, path, source_code)
            inheritance_deps = extract_inheritance(root_node, detected_lang, path, source_code)
            
                                    
            function_calls = extract_function_calls(root_node, detected_lang, path, source_code)
            
            parsed_file = ParsedFile(
                path=path,
                language=detected_lang,
                functions=functions,
                classes=classes,
                constants=constants,
                routes=routes,
                default_exports=default_exports,
                imports=imports,
                exports=exports,
            )
            
                                                                                        
            parsed_file._dependencies = dependencies + inheritance_deps                
            parsed_file._function_calls = function_calls                
            
            print(
                f'[TreeSitterParser] ✓ Parsed {path}: {len(functions)} functions, '
                f'{len(classes)} classes, {len(constants)} constants, {len(routes)} routes, '
                f'{len(default_exports)} default exports, {len(imports)} imports'
            )
            
            return parsed_file
        
        except Exception as error:
            print(f'[TreeSitterParser] Error parsing {path}: {error}')
            return None
    
    async def parse_files(
        self,
        files: List[Dict[str, Any]]
    ) -> ParseResult:
        
        if not self.initialized:
            await self.initialize()
        
        print(f'[TreeSitterParser] Parsing {len(files)} files...')
        
        parsed_files: List[ParsedFile] = []
        all_dependencies: List[Dependency] = []
        all_function_calls: List[FunctionCall] = []
        errors: List[ParseError] = []
        languages = set()
        
                         
        for file in files:
            try:
                parsed = await self.parse_file(
                    file['path'],
                    file['content'],
                    file.get('language')
                )
                
                if parsed:
                    parsed_files.append(parsed)
                    languages.add(parsed.language)
                    
                                          
                    deps = getattr(parsed, '_dependencies', [])
                    all_dependencies.extend(deps)
                    
                                            
                    calls = getattr(parsed, '_function_calls', [])
                    all_function_calls.extend(calls)
                else:
                    errors.append(ParseError(
                        file_path=file['path'],
                        error='Failed to parse file',
                        language=file.get('language')
                    ))
            except Exception as error:
                errors.append(ParseError(
                    file_path=file['path'],
                    error=str(error),
                    language=file.get('language')
                ))
        
                                                          
        defined_functions: Dict[str, Dict[str, str]] = {}
        defined_functions_list: List[Dict[str, str]] = []
        
        for parsed_file in parsed_files:
            for func in parsed_file.functions:
                defined_functions[func.name] = {'name': func.name, 'filePath': parsed_file.path}
                defined_functions_list.append({'name': func.name, 'filePath': parsed_file.path})
            
            for cls in parsed_file.classes:
                for method in cls.methods:
                                                                          
                    full_name = f'{cls.name}.{method.name}'
                    defined_functions[full_name] = {'name': full_name, 'filePath': parsed_file.path}
                    defined_functions_list.append({'name': full_name, 'filePath': parsed_file.path})
                                                 
                    defined_functions[method.name] = {'name': method.name, 'filePath': parsed_file.path}
                    defined_functions_list.append({'name': method.name, 'filePath': parsed_file.path})
        
                                             
        function_usage = build_usage_map(all_function_calls, defined_functions_list)
        
                                                 
        call_dependencies = create_call_dependencies(all_function_calls, defined_functions)
        
                                                              
        file_paths = [f['path'] for f in files]
        resolved_dependencies = self._resolve_dependencies(
            all_dependencies + call_dependencies,
            file_paths
        )
        
        structure = ParsedCodeStructure(
            files=parsed_files,
            dependencies=resolved_dependencies,
            modules=[]                                        
        )
        
        result = ParseResult(
            structure=structure,
            errors=errors,
            function_usage=function_usage,
            metadata={
                'totalFiles': len(files),
                'languages': list(languages),
                'parseErrors': len(errors),
                'totalFunctionCalls': len(all_function_calls),
            }
        )
        
        print(
            f'[TreeSitterParser] ✓ Completed: {len(parsed_files)}/{len(files)} files parsed, '
            f'{len(resolved_dependencies)} dependencies, {len(all_function_calls)} function calls tracked, '
            f'{len(errors)} errors'
        )
        
        return result
    
    def _resolve_dependencies(
        self,
        dependencies: List[Dependency],
        file_paths: List[str]
    ) -> List[Dependency]:
        
        resolved = []
        
        for dep in dependencies:
                                                                           
            if (
                dep.to_path.startswith('/') or
                dep.to_path.startswith('http') or
                not dep.to_path.startswith('.')
            ):
                resolved.append(dep)
                continue
            
                                   
            from_dir = '/'.join(dep.from_path.split('/')[:-1]) if '/' in dep.from_path else ''
            relative_path = dep.to_path
            
                                                
            resolved_path = self._resolve_relative_path(from_dir, relative_path, file_paths)
            
            resolved.append(Dependency(
                from_path=dep.from_path,
                to_path=resolved_path or dep.to_path,
                type=dep.type,
                relationship=dep.relationship
            ))
        
        return resolved
    
    def _resolve_relative_path(
        self,
        from_dir: str,
        relative_path: str,
        available_paths: List[str]
    ) -> Optional[str]:
        
                           
        path = relative_path[2:] if relative_path.startswith('./') else relative_path
        
                               
        potential_paths = [
            f'{from_dir}/{path}' if from_dir else path,
            f'{from_dir}/{path}.ts' if from_dir else f'{path}.ts',
            f'{from_dir}/{path}.tsx' if from_dir else f'{path}.tsx',
            f'{from_dir}/{path}.js' if from_dir else f'{path}.js',
            f'{from_dir}/{path}.jsx' if from_dir else f'{path}.jsx',
            f'{from_dir}/{path}/index.ts' if from_dir else f'{path}/index.ts',
            f'{from_dir}/{path}/index.tsx' if from_dir else f'{path}/index.tsx',
        ]
        
                                   
        for potential_path in potential_paths:
            exact_match = next((p for p in available_paths if p == potential_path), None)
            if exact_match:
                return exact_match
            
                                   
            without_ext = potential_path.replace('.ts', '').replace('.tsx', '').replace('.js', '').replace('.jsx', '')
            match = next((p for p in available_paths if p.startswith(without_ext)), None)
            if match:
                return match
        
        return None

