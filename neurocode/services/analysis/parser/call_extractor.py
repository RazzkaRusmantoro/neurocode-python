from typing import List, Dict, Optional
from tree_sitter import Node
from neurocode.services.analysis.parser.models import FunctionCall, FunctionUsage, Dependency


def extract_function_calls(
    root_node: Node,
    language: str,
    file_path: str,
    source_code: bytes
) -> List[FunctionCall]:
    
    calls: List[FunctionCall] = []
    
    if language in ('typescript', 'tsx', 'javascript', 'jsx'):
                                  
        for node in _extract_nodes_by_type(root_node, 'call_expression'):
            call = _extract_call_from_node(node, file_path, root_node, source_code)
            if call:
                calls.append(call)
        
                                                       
        for node in _extract_nodes_by_type(root_node, 'new_expression'):
            call = _extract_new_expression_from_node(node, file_path, root_node, source_code)
            if call:
                calls.append(call)
    
    elif language == 'python':
                                       
        for node in _extract_nodes_by_type(root_node, 'call'):
            call = _extract_python_call_from_node(node, file_path, root_node, source_code)
            if call:
                calls.append(call)
    
    return calls


def build_usage_map(
    calls: List[FunctionCall],
    defined_functions: List[Dict[str, str]]
) -> Dict[str, FunctionUsage]:
    
    usage_map: Dict[str, FunctionUsage] = {}
    
                                       
    for func in defined_functions:
        usage_map[func['name']] = FunctionUsage(
            functionName=func['name'],
            definedIn=func.get('filePath'),
            calledIn=[],
            totalCalls=0
        )
    
                            
    for call in calls:
        if call.functionName in usage_map:
            usage_map[call.functionName].calledIn.append(call)
            usage_map[call.functionName].totalCalls += 1
        else:
                                                             
            usage_map[call.functionName] = FunctionUsage(
                functionName=call.functionName,
                definedIn=None,
                calledIn=[call],
                totalCalls=1
            )
    
    return usage_map


def create_call_dependencies(
    calls: List[FunctionCall],
    defined_functions: Dict[str, Dict[str, str]]
) -> List[Dependency]:
    
    dependencies: List[Dependency] = []
    
    for call in calls:
        if call.functionName in defined_functions:
            definition = defined_functions[call.functionName]
            if definition['filePath'] != call.filePath:
                                                         
                dependencies.append(Dependency(
                    from_path=call.filePath,
                    to_path=definition['filePath'],
                    type='call',
                    relationship=call.functionName
                ))
    
    return dependencies


                  

def _extract_call_from_node(
    node: Node,
    file_path: str,
    root_node: Node,
    source_code: bytes
) -> Optional[FunctionCall]:
    
    function_node = node.child_by_field_name('function')
    if not function_node:
        return None
    
    function_name: str
    is_method_call = False
    receiver: Optional[str] = None
    
                                                
    if function_node.type == 'member_expression':
        is_method_call = True
        object_node = function_node.child_by_field_name('object')
        property_node = function_node.child_by_field_name('property')
        
        if property_node:
            function_name = _get_node_text(property_node, source_code)
            if object_node:
                receiver = _get_node_text(object_node, source_code)
        else:
            return None
    else:
                               
        function_name = _get_node_text(function_node, source_code)
    
    if not function_name:
        return None
    
    context = _get_call_context(node, root_node, source_code)
    line = node.start_point[0] + 1
    column = node.start_point[1]
    
    return FunctionCall(
        functionName=function_name,
        filePath=file_path,
        line=line,
        column=column,
        context=context,
        isMethodCall=is_method_call,
        receiver=receiver,
        callType='method' if is_method_call else 'function'
    )


def _extract_new_expression_from_node(
    node: Node,
    file_path: str,
    root_node: Node,
    source_code: bytes
) -> Optional[FunctionCall]:
    
    constructor_node = node.child_by_field_name('constructor')
    if not constructor_node:
        return None
    
    class_name: str
    is_method_call = False
    receiver: Optional[str] = None
    
                                             
    if constructor_node.type == 'member_expression':
        is_method_call = True
        object_node = constructor_node.child_by_field_name('object')
        property_node = constructor_node.child_by_field_name('property')
        
        if property_node:
            class_name = _get_node_text(property_node, source_code)
            if object_node:
                receiver = _get_node_text(object_node, source_code)
        else:
            return None
    else:
                                                 
        class_name = _get_node_text(constructor_node, source_code)
    
    if not class_name:
        return None
    
    context = _get_call_context(node, root_node, source_code)
    line = node.start_point[0] + 1
    column = node.start_point[1]
    
    return FunctionCall(
        functionName=class_name,
        filePath=file_path,
        line=line,
        column=column,
        context=context,
        isMethodCall=is_method_call,
        receiver=receiver,
        callType='constructor'
    )


def _extract_python_call_from_node(
    node: Node,
    file_path: str,
    root_node: Node,
    source_code: bytes
) -> Optional[FunctionCall]:
    
    function_node = node.child_by_field_name('function')
    if not function_node:
        return None
    
    function_name: str
    is_method_call = False
    receiver: Optional[str] = None
    
                                                
    if function_node.type == 'attribute':
        is_method_call = True
        object_node = function_node.child_by_field_name('object')
        attr_node = function_node.child_by_field_name('attribute')
        
        if attr_node:
            function_name = _get_node_text(attr_node, source_code)
            if object_node:
                receiver = _get_node_text(object_node, source_code)
        else:
            return None
    else:
                               
        function_name = _get_node_text(function_node, source_code)
    
    if not function_name:
        return None
    
    context = _get_call_context(node, root_node, source_code)
    line = node.start_point[0] + 1
    column = node.start_point[1]
    
    return FunctionCall(
        functionName=function_name,
        filePath=file_path,
        line=line,
        column=column,
        context=context,
        isMethodCall=is_method_call,
        receiver=receiver,
        callType='method' if is_method_call else 'function'
    )


def _get_call_context(node: Node, root_node: Node, source_code: bytes) -> Optional[str]:
    
                                               
    containing_function = _find_containing_function(root_node, node, source_code)
    
    if containing_function:
        name_node = containing_function.child_by_field_name('name')
        if name_node:
            return _get_node_text(name_node, source_code)
        return 'anonymous'
    
    return None


def _find_containing_function(
    current: Node,
    target: Node,
    source_code: bytes
) -> Optional[Node]:
    
                                                    
    if (
        target.start_point[0] >= current.start_point[0] and
        target.end_point[0] <= current.end_point[0] and
        target.start_point[1] >= current.start_point[1] and
        target.end_point[1] <= current.end_point[1]
    ):
                                        
        if current.type in (
            'function_declaration',
            'function_expression',
            'arrow_function',
            'method_definition',
            'function_definition'          
        ):
            return current
        
                         
        for child in current.named_children:
            found = _find_containing_function(child, target, source_code)
            if found:
                return found
    
    return None


def _extract_nodes_by_type(root: Node, node_type: str):
    
    if root.type == node_type:
        yield root
    
    for child in root.named_children:
        yield from _extract_nodes_by_type(child, node_type)


def _get_node_text(node: Optional[Node], source_code: bytes) -> str:
    
    if not node:
        return ""
    return source_code[node.start_byte:node.end_byte].decode('utf-8', errors='ignore')

