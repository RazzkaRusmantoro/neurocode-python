"""
Extract symbols (functions, classes, methods) from Tree-sitter AST
"""
from typing import List, Optional
from tree_sitter import Node
from neurocode.services.analysis.parser.models import (
    FunctionDefinition,
    ClassDefinition,
    MethodDefinition,
    PropertyDefinition,
    Parameter,
    ExportStatement,
    ConstantDefinition,
    RouteDefinition,
    DefaultExportDefinition,
)


def extract_functions(root_node: Node, language: str, source_code: bytes) -> List[FunctionDefinition]:
    """Extract functions from AST"""
    functions: List[FunctionDefinition] = []
    
    if language in ('typescript', 'tsx', 'javascript', 'jsx'):
        # Extract function declarations
        for node in _extract_nodes_by_type(root_node, 'function_declaration'):
            func = _extract_function_from_node(node, language, source_code)
            if func:
                functions.append(func)
        
        # Extract arrow functions from variable_declaration (var) and lexical_declaration (const/let)
        for node in _extract_nodes_by_type(root_node, 'variable_declaration'):
            for arrow_func in _extract_arrow_functions_from_declaration(node, language, source_code):
                if arrow_func:
                    functions.append(arrow_func)
        for node in _extract_nodes_by_type(root_node, 'lexical_declaration'):
            for arrow_func in _extract_arrow_functions_from_declaration(node, language, source_code):
                if arrow_func:
                    functions.append(arrow_func)
    
    elif language == 'python':
        # Extract Python function definitions
        for node in _extract_nodes_by_type(root_node, 'function_definition'):
            func = _extract_python_function_from_node(node, source_code)
            if func:
                functions.append(func)
    
    return functions


def extract_constants(root_node: Node, language: str, source_code: bytes) -> List[ConstantDefinition]:
    """Extract top-level constants (const/let with object or array literal)."""
    constants: List[ConstantDefinition] = []
    if language not in ('typescript', 'tsx', 'javascript', 'jsx'):
        return constants
    for node in _extract_nodes_by_type(root_node, 'lexical_declaration'):
        for child in node.named_children:
            if child.type != 'variable_declarator':
                continue
            name_node = child.child_by_field_name('name')
            value_node = child.child_by_field_name('value')
            if not name_node or not value_node:
                continue
            name = _get_node_text(name_node, source_code)
            if not name or name.startswith('{') or name.startswith('['):
                continue
            if value_node.type == 'object':
                value_type = 'object'
            elif value_node.type == 'array':
                value_type = 'array'
            else:
                continue
            constants.append(ConstantDefinition(
                name=name,
                startLine=child.start_point[0] + 1,
                endLine=child.end_point[0] + 1,
                valueType=value_type,
                isExported=_has_export_modifier(node, source_code),
            ))
    for node in _extract_nodes_by_type(root_node, 'variable_declaration'):
        for child in node.named_children:
            if child.type != 'variable_declarator':
                continue
            name_node = child.child_by_field_name('name')
            value_node = child.child_by_field_name('value')
            if not name_node or not value_node:
                continue
            if value_node.type not in ('object', 'array'):
                continue
            name = _get_node_text(name_node, source_code)
            if not name or name.startswith('{') or name.startswith('['):
                continue
            constants.append(ConstantDefinition(
                name=name,
                startLine=child.start_point[0] + 1,
                endLine=child.end_point[0] + 1,
                valueType='object' if value_node.type == 'object' else 'array',
                isExported=_has_export_modifier(node, source_code),
            ))
    return constants


def extract_classes(root_node: Node, language: str, source_code: bytes) -> List[ClassDefinition]:
    """Extract classes from AST"""
    classes: List[ClassDefinition] = []
    
    if language in ('typescript', 'tsx', 'javascript', 'jsx'):
        for node in _extract_nodes_by_type(root_node, 'class_declaration'):
            class_def = _extract_class_from_node(node, language, source_code)
            if class_def:
                classes.append(class_def)
    
    elif language == 'python':
        for node in _extract_nodes_by_type(root_node, 'class_definition'):
            class_def = _extract_python_class_from_node(node, source_code)
            if class_def:
                classes.append(class_def)
    
    return classes


def extract_exports(root_node: Node, language: str, source_code: bytes) -> List[ExportStatement]:
    """Extract exports from AST"""
    exports: List[ExportStatement] = []
    
    if language in ('typescript', 'tsx', 'javascript', 'jsx'):
        # Named exports: export function foo() {}
        for node in _extract_nodes_by_type(root_node, 'export_statement'):
            export_stmt = _extract_export_from_node(node, source_code)
            if export_stmt:
                exports.append(export_stmt)
        
        # Export declarations: export class Foo {}
        for node in _extract_nodes_by_type(root_node, 'class_declaration'):
            if _has_export_modifier(node, source_code):
                name_node = node.child_by_field_name('name')
                if name_node:
                    class_name = _get_node_text(name_node, source_code)
                    if class_name:
                        exports.append(ExportStatement(name=class_name, type='class'))
        
        for node in _extract_nodes_by_type(root_node, 'function_declaration'):
            if _has_export_modifier(node, source_code):
                name_node = node.child_by_field_name('name')
                if name_node:
                    func_name = _get_node_text(name_node, source_code)
                    if func_name:
                        exports.append(ExportStatement(name=func_name, type='function'))
    
    elif language == 'python':
        # Python doesn't have explicit exports, but we can check __all__
        pass
    
    return exports


def extract_routes(root_node: Node, language: str, source_code: bytes) -> List[RouteDefinition]:
    """Extract route definitions (router.get('/path', handler), app.post(...), etc.)."""
    routes: List[RouteDefinition] = []
    http_methods = ('get', 'post', 'put', 'delete', 'patch', 'use')

    if language in ('typescript', 'tsx', 'javascript', 'jsx'):
        for node in _extract_nodes_by_type(root_node, 'call_expression'):
            func_node = node.child_by_field_name('function')
            if not func_node or func_node.type != 'member_expression':
                continue
            property_node = func_node.child_by_field_name('property')
            if not property_node:
                continue
            method = _get_node_text(property_node, source_code).lower()
            if method not in http_methods:
                continue
            # First argument should be path (string)
            args = node.child_by_field_name('arguments')
            if not args or args.named_child_count == 0:
                continue
            first_arg = args.named_children[0]
            path_text = _get_node_text(first_arg, source_code).strip()
            if not (path_text.startswith(("'", '"', "`")) and path_text.endswith(("'", '"', "`"))):
                continue
            path = path_text[1:-1]
            receiver_node = func_node.child_by_field_name('object')
            receiver = _get_node_text(receiver_node, source_code) if receiver_node else None
            routes.append(RouteDefinition(
                path=path,
                method=method,
                receiver=receiver,
                startLine=node.start_point[0] + 1,
                endLine=node.end_point[0] + 1,
            ))

    elif language == 'python':
        # Decorator-based routes: @app.get("/path"), @router.post("/path")
        for node in _extract_nodes_by_type(root_node, 'decorator'):
            call_node = node.named_children[0] if node.named_child_count else None
            if not call_node or call_node.type != 'call':
                continue
            func_node = call_node.child_by_field_name('function')
            if not func_node or func_node.type != 'attribute':
                continue
            attr_node = func_node.child_by_field_name('attribute')
            if not attr_node:
                continue
            method = _get_node_text(attr_node, source_code).lower()
            if method not in http_methods:
                continue
            args = call_node.child_by_field_name('arguments')
            if not args or args.named_child_count == 0:
                continue
            first_arg = args.named_children[0]
            path_text = _get_node_text(first_arg, source_code).strip().strip('"\'')
            receiver_node = func_node.child_by_field_name('value')
            receiver = _get_node_text(receiver_node, source_code) if receiver_node else None
            routes.append(RouteDefinition(
                path=path_text,
                method=method,
                receiver=receiver,
                startLine=node.start_point[0] + 1,
                endLine=node.end_point[0] + 1,
            ))

    return routes


def extract_default_exports(root_node: Node, language: str, source_code: bytes) -> List[DefaultExportDefinition]:
    """Extract default export statements (export default ...) for full coverage."""
    default_exports: List[DefaultExportDefinition] = []
    if language not in ('typescript', 'tsx', 'javascript', 'jsx'):
        return default_exports
    for node in _extract_nodes_by_type(root_node, 'export_statement'):
        text = _get_node_text(node, source_code)
        if 'default' in text.split()[:3]:  # export default ...
            default_exports.append(DefaultExportDefinition(
                startLine=node.start_point[0] + 1,
                endLine=node.end_point[0] + 1,
            ))
    return default_exports


# Helper functions for TypeScript/JavaScript

def _extract_function_from_node(node: Node, language: str, source_code: bytes) -> Optional[FunctionDefinition]:
    """Extract function from function_declaration node"""
    name_node = node.child_by_field_name('name')
    if not name_node:
        return None
    
    name = _get_node_text(name_node, source_code)
    parameters = _extract_parameters(node.child_by_field_name('parameters'), source_code)
    return_type = _extract_return_type(node, language, source_code)
    body = _extract_function_body(node, source_code)
    is_async = _has_modifier(node, 'async', source_code)
    is_exported = _has_export_modifier(node, source_code)
    
    return FunctionDefinition(
        name=name,
        parameters=parameters,
        returnType=return_type,
        isAsync=is_async,
        isExported=is_exported,
        startLine=node.start_point[0] + 1,
        endLine=node.end_point[0] + 1,
        body=body
    )


def _extract_arrow_functions_from_declaration(
    node: Node, language: str, source_code: bytes
) -> List[FunctionDefinition]:
    """Extract all arrow functions from a variable_declaration or lexical_declaration (const/let)."""
    results: List[FunctionDefinition] = []
    for child in node.named_children:
        if child.type != 'variable_declarator':
            continue
        func = _extract_arrow_function_from_declarator(child, node, language, source_code)
        if func:
            results.append(func)
    return results


def _extract_arrow_function_from_declarator(
    declarator: Node,
    parent_declaration: Node,
    language: str,
    source_code: bytes,
) -> Optional[FunctionDefinition]:
    """Extract arrow function from a single variable_declarator."""
    name_node = declarator.child_by_field_name('name')
    value_node = declarator.child_by_field_name('value')
    
    if not name_node or not value_node:
        return None
    
    # Check if value is an arrow function or function expression
    if value_node.type not in ('arrow_function', 'function', 'function_expression'):
        return None
    
    # For object patterns (e.g. const { x } = ...) name_node might be different; skip if no simple name
    name = _get_node_text(name_node, source_code)
    if not name or name.startswith('{') or name.startswith('['):
        return None
    
    parameters = _extract_parameters(value_node.child_by_field_name('parameters'), source_code)
    return_type = _extract_return_type(value_node, language, source_code)
    body = _extract_function_body(value_node, source_code)
    is_async = _has_modifier(value_node, 'async', source_code)
    is_exported = _has_export_modifier(parent_declaration, source_code)
    
    return FunctionDefinition(
        name=name,
        parameters=parameters,
        returnType=return_type,
        isAsync=is_async,
        isExported=is_exported,
        startLine=declarator.start_point[0] + 1,
        endLine=declarator.end_point[0] + 1,
        body=body
    )


def _extract_class_from_node(node: Node, language: str, source_code: bytes) -> Optional[ClassDefinition]:
    """Extract class from class_declaration node"""
    name_node = node.child_by_field_name('name')
    if not name_node:
        return None
    
    name = _get_node_text(name_node, source_code)
    class_body = node.child_by_field_name('body')
    methods: List[MethodDefinition] = []
    properties: List[PropertyDefinition] = []
    
    if class_body:
        # Extract methods
        for method_node in _extract_nodes_by_type(class_body, 'method_definition'):
            method = _extract_method_from_node(method_node, source_code)
            if method:
                methods.append(method)
        
        # Extract properties
        for prop_node in _extract_nodes_by_type(class_body, 'property_signature'):
            prop = _extract_property_from_node(prop_node, source_code)
            if prop:
                properties.append(prop)
    
    extends_node = node.child_by_field_name('superclass')
    extends = _get_node_text(extends_node, source_code) if extends_node else None
    
    is_exported = _has_export_modifier(node, source_code)
    
    return ClassDefinition(
        name=name,
        methods=methods,
        properties=properties,
        extends=extends,
        implements=None,  # Would need to extract implements clause
        isExported=is_exported,
        startLine=node.start_point[0] + 1,
        endLine=node.end_point[0] + 1
    )


def _extract_method_from_node(node: Node, source_code: bytes) -> Optional[MethodDefinition]:
    """Extract method from method_definition node"""
    name_node = node.child_by_field_name('name')
    if not name_node:
        return None
    
    name = _get_node_text(name_node, source_code)
    parameters = _extract_parameters(node.child_by_field_name('parameters'), source_code)
    return_type = _extract_return_type(node, 'typescript', source_code)
    is_async = _has_modifier(node, 'async', source_code)
    is_public = not _has_modifier(node, 'private', source_code) and not _has_modifier(node, 'protected', source_code)
    is_static = _has_modifier(node, 'static', source_code)
    
    return MethodDefinition(
        name=name,
        parameters=parameters,
        returnType=return_type,
        isAsync=is_async,
        isPublic=is_public,
        isStatic=is_static,
        startLine=node.start_point[0] + 1,
        endLine=node.end_point[0] + 1
    )


def _extract_property_from_node(node: Node, source_code: bytes) -> Optional[PropertyDefinition]:
    """Extract property from property_signature node"""
    name_node = node.child_by_field_name('name')
    if not name_node:
        return None
    
    name = _get_node_text(name_node, source_code)
    type_node = node.child_by_field_name('type')
    prop_type = _get_node_text(type_node, source_code) if type_node else None
    is_public = not _has_modifier(node, 'private', source_code) and not _has_modifier(node, 'protected', source_code)
    is_static = _has_modifier(node, 'static', source_code)
    
    return PropertyDefinition(
        name=name,
        type=prop_type,
        isPublic=is_public,
        isStatic=is_static
    )


# Python-specific extractors

def _extract_python_function_from_node(node: Node, source_code: bytes) -> Optional[FunctionDefinition]:
    """Extract Python function from function_definition node"""
    name_node = node.child_by_field_name('name')
    if not name_node:
        return None
    
    name = _get_node_text(name_node, source_code)
    parameters = _extract_python_parameters(node.child_by_field_name('parameters'), source_code)
    body = _extract_function_body(node, source_code)
    
    # Check for async
    is_async = False
    for child in node.named_children:
        if child.type == 'async':
            is_async = True
            break
    
    return FunctionDefinition(
        name=name,
        parameters=parameters,
        returnType=None,  # Python return types are in annotations, would need to extract
        isAsync=is_async,
        isExported=False,  # Python doesn't have explicit exports
        startLine=node.start_point[0] + 1,
        endLine=node.end_point[0] + 1,
        body=body
    )


def _extract_python_class_from_node(node: Node, source_code: bytes) -> Optional[ClassDefinition]:
    """Extract Python class from class_definition node"""
    name_node = node.child_by_field_name('name')
    if not name_node:
        return None
    
    name = _get_node_text(name_node, source_code)
    class_body = node.child_by_field_name('body')
    methods: List[MethodDefinition] = []
    
    if class_body:
        for method_node in _extract_nodes_by_type(class_body, 'function_definition'):
            method = _extract_python_method_from_node(method_node, source_code)
            if method:
                methods.append(method)
    
    # Extract superclasses
    superclasses = node.child_by_field_name('superclasses')
    extends = None
    if superclasses:
        # Get first superclass name
        for child in superclasses.named_children:
            if child.type == 'identifier':
                extends = _get_node_text(child, source_code)
                break
    
    return ClassDefinition(
        name=name,
        methods=methods,
        properties=[],  # Python properties are methods with @property decorator
        extends=extends,
        implements=None,
        isExported=False,
        startLine=node.start_point[0] + 1,
        endLine=node.end_point[0] + 1
    )


def _extract_python_method_from_node(node: Node, source_code: bytes) -> Optional[MethodDefinition]:
    """Extract Python method from function_definition node"""
    name_node = node.child_by_field_name('name')
    if not name_node:
        return None
    
    name = _get_node_text(name_node, source_code)
    parameters = _extract_python_parameters(node.child_by_field_name('parameters'), source_code)
    
    # Check for async
    is_async = False
    for child in node.named_children:
        if child.type == 'async':
            is_async = True
            break
    
    return MethodDefinition(
        name=name,
        parameters=parameters,
        returnType=None,
        isAsync=is_async,
        isPublic=True,  # Python methods are public by default
        isStatic=False,  # Would need to check for @staticmethod decorator
        startLine=node.start_point[0] + 1,
        endLine=node.end_point[0] + 1
    )


# Utility functions

def _extract_parameters(params_node: Optional[Node], source_code: bytes) -> List[Parameter]:
    """Extract parameters from parameters node"""
    if not params_node:
        return []
    
    parameters: List[Parameter] = []
    
    for child in params_node.named_children:
        if child.type in ('required_parameter', 'optional_parameter', 'identifier'):
            param = _extract_parameter_from_node(child, source_code)
            if param:
                parameters.append(param)
    
    return parameters


def _extract_python_parameters(params_node: Optional[Node], source_code: bytes) -> List[Parameter]:
    """Extract Python parameters"""
    if not params_node:
        return []
    
    parameters: List[Parameter] = []
    
    for child in params_node.named_children:
        if child.type in ('identifier', 'typed_parameter', 'default_parameter'):
            param = _extract_python_parameter_from_node(child, source_code)
            if param:
                parameters.append(param)
    
    return parameters


def _extract_parameter_from_node(node: Node, source_code: bytes) -> Optional[Parameter]:
    """Extract parameter from parameter node"""
    pattern = node.child_by_field_name('pattern') or node
    name_node = pattern.child_by_field_name('name') or pattern
    
    name = _get_node_text(name_node, source_code)
    if not name:
        return None
    
    type_node = node.child_by_field_name('type')
    param_type = _get_node_text(type_node, source_code) if type_node else None
    
    optional = node.type == 'optional_parameter' or b'?' in node.text
    
    default_node = node.child_by_field_name('value')
    default_value = _get_node_text(default_node, source_code) if default_node else None
    
    return Parameter(
        name=name,
        type=param_type,
        optional=optional,
        defaultValue=default_value
    )


def _extract_python_parameter_from_node(node: Node, source_code: bytes) -> Optional[Parameter]:
    """Extract Python parameter"""
    name_node = node.child_by_field_name('name') or node
    name = _get_node_text(name_node, source_code)
    
    if not name:
        return None
    
    type_node = node.child_by_field_name('type')
    param_type = _get_node_text(type_node, source_code) if type_node else None
    
    default_node = node.child_by_field_name('default')
    default_value = _get_node_text(default_node, source_code) if default_node else None
    
    return Parameter(
        name=name,
        type=param_type,
        optional=default_value is not None,
        defaultValue=default_value
    )


def _extract_return_type(node: Node, language: str, source_code: bytes) -> Optional[str]:
    """Extract return type annotation"""
    type_node = node.child_by_field_name('return_type')
    if type_node:
        return _get_node_text(type_node, source_code)
    
    # For arrow functions, check for type annotation
    if node.type == 'arrow_function':
        for child in node.named_children:
            if child.type == 'type_annotation':
                return _get_node_text(child, source_code)
    
    return None


def _extract_function_body(node: Node, source_code: bytes) -> str:
    """Extract function body"""
    body_node = node.child_by_field_name('body')
    if body_node:
        return _get_node_text(body_node, source_code)
    return ""


def _extract_export_from_node(node: Node, source_code: bytes) -> Optional[ExportStatement]:
    """Extract export statement"""
    # Find what's being exported
    for child in node.named_children:
        if child.type in ('function_declaration', 'class_declaration', 'variable_declaration'):
            name_node = child.child_by_field_name('name')
            if name_node:
                name = _get_node_text(name_node, source_code)
                export_type = 'variable'
                if child.type == 'function_declaration':
                    export_type = 'function'
                elif child.type == 'class_declaration':
                    export_type = 'class'
                
                return ExportStatement(name=name, type=export_type)
    
    return None


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


def _has_modifier(node: Node, modifier: str, source_code: bytes) -> bool:
    """Check if node has a modifier"""
    node_text = _get_node_text(node, source_code)
    return modifier in node_text.lower()


def _has_export_modifier(node: Node, source_code: bytes) -> bool:
    """Check if node has export modifier"""
    # Check parent for export
    current = node
    while current:
        node_text = _get_node_text(current, source_code)
        if 'export' in node_text:
            return True
        # Tree-sitter nodes don't have parent, so we check siblings/parent context
        # This is simplified - would need proper tree traversal
        break
    return False

