"""
Extract dependencies (imports, requires) from Tree-sitter AST
"""
from typing import List, Tuple, Optional
from tree_sitter import Node
from neurocode.services.analysis.parser.models import ImportStatement, Dependency


def extract_imports(
    root_node: Node,
    language: str,
    file_path: str,
    source_code: bytes
) -> Tuple[List[ImportStatement], List[Dependency]]:
    """
    Extract import statements and dependencies
    
    Returns:
        Tuple of (imports, dependencies)
    """
    imports: List[ImportStatement] = []
    dependencies: List[Dependency] = []
    
    if language in ('typescript', 'tsx', 'javascript', 'jsx'):
        # Extract import statements
        for node in _extract_nodes_by_type(root_node, 'import_statement'):
            import_stmt = _extract_import_from_node(node, source_code)
            if import_stmt:
                imports.append(import_stmt)
                dependencies.append(Dependency(
                    from_path=file_path,
                    to_path=import_stmt.source,
                    type='import',
                    relationship=', '.join(import_stmt.imports)
                ))
        
        # Extract require statements (CommonJS)
        for node in _extract_nodes_by_type(root_node, 'call_expression'):
            require_stmt = _extract_require_from_node(node, source_code)
            if require_stmt:
                imports.append(ImportStatement(
                    source=require_stmt['source'],
                    imports=['*'],
                    isTypeOnly=False
                ))
                dependencies.append(Dependency(
                    from_path=file_path,
                    to_path=require_stmt['source'],
                    type='import',
                    relationship='require'
                ))
    
    elif language == 'python':
        # Extract Python imports
        for node in _extract_nodes_by_type(root_node, 'import_statement'):
            import_stmt = _extract_python_import_from_node(node, source_code)
            if import_stmt:
                imports.append(import_stmt)
                dependencies.append(Dependency(
                    from_path=file_path,
                    to_path=import_stmt.source,
                    type='import',
                    relationship=', '.join(import_stmt.imports)
                ))
        
        # Extract from imports
        for node in _extract_nodes_by_type(root_node, 'import_from_statement'):
            import_stmt = _extract_python_from_import_from_node(node, source_code)
            if import_stmt:
                imports.append(import_stmt)
                dependencies.append(Dependency(
                    from_path=file_path,
                    to_path=import_stmt.source,
                    type='import',
                    relationship=', '.join(import_stmt.imports)
                ))
    
    return imports, dependencies


def extract_inheritance(
    root_node: Node,
    language: str,
    file_path: str,
    source_code: bytes
) -> List[Dependency]:
    """Extract extends/implements relationships"""
    dependencies: List[Dependency] = []
    
    if language in ('typescript', 'tsx', 'javascript', 'jsx'):
        for node in _extract_nodes_by_type(root_node, 'class_declaration'):
            superclass = node.child_by_field_name('superclass')
            if superclass:
                name_node = node.child_by_field_name('name')
                class_name = _get_node_text(name_node, source_code) if name_node else None
                extends_class = _get_node_text(superclass, source_code)
                
                if class_name and extends_class:
                    dependencies.append(Dependency(
                        from_path=file_path,
                        to_path=extends_class,  # Would need to resolve to actual file path
                        type='extends',
                        relationship=class_name
                    ))
    
    elif language == 'python':
        for node in _extract_nodes_by_type(root_node, 'class_definition'):
            superclasses = node.child_by_field_name('superclasses')
            if superclasses:
                name_node = node.child_by_field_name('name')
                class_name = _get_node_text(name_node, source_code) if name_node else None
                
                # Get first superclass
                for child in superclasses.named_children:
                    if child.type == 'identifier':
                        extends_class = _get_node_text(child, source_code)
                        if class_name and extends_class:
                            dependencies.append(Dependency(
                                from_path=file_path,
                                to_path=extends_class,
                                type='extends',
                                relationship=class_name
                            ))
                        break
    
    return dependencies


# Helper functions for TypeScript/JavaScript

def _extract_import_from_node(node: Node, source_code: bytes) -> Optional[ImportStatement]:
    """Extract import from import_statement node"""
    source_node = node.child_by_field_name('source')
    if not source_node:
        return None
    
    source = _get_node_text(source_node, source_code).strip('"\'')
    
    import_clause = node.child_by_field_name('import')
    imports: List[str] = []
    is_type_only = False
    
    if import_clause:
        # Check if it's a type-only import
        import_text = _get_node_text(import_clause, source_code)
        if 'type ' in import_text:
            is_type_only = True
        
        # Extract import specifiers
        for child in import_clause.named_children:
            if child.type == 'import_specifier':
                name_node = child.child_by_field_name('name')
                if name_node:
                    imports.append(_get_node_text(name_node, source_code))
            elif child.type == 'identifier':
                # Default import
                imports.append(_get_node_text(child, source_code))
            elif child.type == 'namespace_import':
                alias_node = child.child_by_field_name('alias')
                if alias_node:
                    imports.append(f"* as {_get_node_text(alias_node, source_code)}")
    
    if not imports:
        imports = ['*']
    
    return ImportStatement(
        source=source,
        imports=imports,
        isTypeOnly=is_type_only
    )


def _extract_require_from_node(node: Node, source_code: bytes) -> Optional[dict]:
    """Extract require() call"""
    function_node = node.child_by_field_name('function')
    if not function_node or _get_node_text(function_node, source_code) != 'require':
        return None
    
    args_node = node.child_by_field_name('arguments')
    if not args_node or not args_node.named_child_count:
        return None
    
    arg_node = args_node.named_children[0]
    source = _get_node_text(arg_node, source_code).strip('"\'')
    
    return {'source': source}


# Helper functions for Python

def _extract_python_import_from_node(node: Node, source_code: bytes) -> ImportStatement:
    """Extract Python import statement"""
    import_names: List[str] = []
    
    # Extract imported names
    for child in node.named_children:
        if child.type in ('dotted_name', 'aliased_import'):
            name = _get_node_text(child, source_code)
            if name:
                import_names.append(name)
    
    source = '.'.join(import_names) if import_names else '*'
    
    return ImportStatement(
        source=source,
        imports=import_names if import_names else ['*'],
        isTypeOnly=False
    )


def _extract_python_from_import_from_node(node: Node, source_code: bytes) -> ImportStatement:
    """Extract Python from ... import statement"""
    module_node = node.child_by_field_name('module_name')
    source = _get_node_text(module_node, source_code) if module_node else ''
    
    import_list = node.child_by_field_name('import_list')
    imports: List[str] = []
    
    if import_list:
        for child in import_list.named_children:
            if child.type == 'dotted_name':
                imports.append(_get_node_text(child, source_code))
            elif child.type == 'aliased_import':
                # Handle 'import as alias'
                name_node = child.child_by_field_name('name')
                alias_node = child.child_by_field_name('alias')
                if name_node:
                    name = _get_node_text(name_node, source_code)
                    if alias_node:
                        name = f"{name} as {_get_node_text(alias_node, source_code)}"
                    imports.append(name)
    
    return ImportStatement(
        source=source,
        imports=imports if imports else ['*'],
        isTypeOnly=False
    )


# Utility functions

def _extract_nodes_by_type(root: Node, node_type: str):
    """Extract all nodes of a specific type from tree"""
    if root.type == node_type:
        yield root
    
    for child in root.named_children:
        yield from _extract_nodes_by_type(child, node_type)


def _get_node_text(node: Optional[Node], source_code: bytes) -> str:
    """Get text content of a node"""
    if not node:
        return ""
    return source_code[node.start_byte:node.end_byte].decode('utf-8', errors='ignore')

