# Global Imports
import ast
import _ast
import tokenize

def compute_interval(node):
    """
    Computes the beginning and the ending line number
    
    Args:
        node: The AST node whose line numbers are required.
    
    Returns:
        Tuple of start lineno and end lineno
    """
    min_lineno = node.lineno
    max_lineno = node.lineno
    for node in ast.walk(node):
        if hasattr(node, "lineno"):
            min_lineno = min(min_lineno, node.lineno)
            max_lineno = max(max_lineno, node.lineno)
    return (min_lineno, max_lineno)

def extract_doc(node):
    """
    Extracting the docstring from the node

    Args:
        node: The AST node that we want to get the docstring of
    
    Returns:
        Returns the docstring if present,
        else returns empty string.
    """
    e = ast.get_docstring(node)
    if e:
        return e
    else:
        return ''

def inspect_module(module_path):
    """
    Inspects the whole module and builds the necessary params

    Args:
        module_path (str) : The path to the module that needs to be
            inspected.
    
    Returns:
        Dicstonary with the following keys:
            - name: Name of the segment
            - header: The header that appears
            - lineno: Source code line numbers
            - doc: Docstring
    """
    with tokenize.open(module_path) as mf:
        tree = ast.parse(mf.read())
    module_details = []
    e = extract_doc(tree)
    if e:
        # IF MODULE
        module_details.append({
            'name':'.',
            'header':'',
            'lineno':(0,0),
            'doc':e,})
    for item in tree.body:
        if isinstance(item, _ast.ClassDef):
            # IF CLASS
            module_methods = []
            for nest_item in item.body:
                if isinstance(nest_item, _ast.FunctionDef):
                    # IF METHOD
                    e = extract_doc(nest_item) 
                    if e:
                        module_methods.append({
                            'name':f'{item.name}.{nest_item.name}',
                            'header':f'## {nest_item.name}',
                            'lineno':compute_interval(nest_item),
                            'doc':e,})
            e = extract_doc(item)
            if len(module_methods) != 0 or e:
                module_details.append({
                    'name':item.name,
                    'header':f'# {item.name}',
                    'lineno':compute_interval(item),
                    'doc':e,})
                for i in module_methods:
                    module_details.append(i)
        elif isinstance(item, _ast.FunctionDef):
            # ELSE IF FUNCTION
            e = extract_doc(item) 
            if e:
                module_details.append({
                    'name':item.name,
                    'header':f'# {item.name}',
                    'lineno':compute_interval(item),
                    'doc':e})
    return module_details
