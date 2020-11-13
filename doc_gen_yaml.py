# USAGE python doc_gen_yaml.py doc_structure.yaml

import ast
import _ast
import sys
import tokenize
import yaml
import os

from Mydocstring.extract import extract, format_txt
from Mydocstring import parse


yaml_filename = sys.argv[1]
yaml_file = open(yaml_filename)
p_yaml_file = yaml.load(yaml_file, Loader=yaml.FullLoader)

loaders = p_yaml_file['loaders']
renderer = p_yaml_file['renderer']

def compute_interval(node):
    """Computes the beginning and the ending line number"""
    min_lineno = node.lineno
    max_lineno = node.lineno
    for node in ast.walk(node):
        if hasattr(node, "lineno"):
            min_lineno = min(min_lineno, node.lineno)
            max_lineno = max(max_lineno, node.lineno)
    return (min_lineno, max_lineno)

def has_doc(node):
    """Checks for docstring"""
    if ast.get_docstring(node):
        return True
    else:
        return False

def inspect_module(module_path):
    """Inspects the whole module"""
    with tokenize.open(module_path) as mf:
        tree = ast.parse(mf.read())
    module_details = []
    for item in tree.body:
        if isinstance(item, _ast.ClassDef):
            # IF CLASS
            module_methods = []
            for nest_item in item.body:
                if isinstance(nest_item, _ast.FunctionDef):
                    # IF METHOD
                    if has_doc(nest_item):
                        module_methods.append(('{}.{}'.format(item.name,nest_item.name), compute_interval(nest_item), True))
            if len(module_methods) != 0 or has_doc(item):
                module_details.append((item.name, compute_interval(item), has_doc(item)))
                for i in module_methods:
                    module_details.append(i)
        elif isinstance(item, _ast.FunctionDef):
            # ELSE IF FUNCTION
            if has_doc(item):
                module_details.append((item.name, compute_interval(item), True))
    return module_details

def setup_google(source_code, query, signature=None, config=None):
    extracted = extract(source_code, query)
    google = parse.GoogleDocString(
        extracted['docstring'].lstrip('\n'),
        signature=signature,
        config=config)
    return extracted, google

def create_md(
    root_path,
    source_code,
    query,
    line,
    header,
    has_doc=True,
    signature=None,
    config=None):
    if has_doc:
        extracted, google = setup_google(
            source_code=root_path+'/'+source_code+'.py',
            query=query,
            signature=signature,
            config=config)
        docstr = google.parse()
        table_arg = ''
        table_att = ''
        hint = ''
        example = ''
        returns = ''
        for item in docstr:
            # CHECK FOR ARGUMENTS
            if item["header"] == "Arguments":
                table_arg = """| **Arguments** | **Datatype** | **Description** |\n|:--:|:--:|:--|\n"""
                for arg in item["args"]:
                    table_arg += """|{}|{}|{}|\n""".format(
                        arg['field'],
                        arg['signature'],
                        format_txt(arg['description'])
                    )
            
            # CHECK FOR ATTRIBUTES
            if item["header"] == "Attributes":
                table_att = """| **Attributes** | **Datatype** | **Description** |\n|:--:|:--:|:--|\n"""
                for arg in item["args"]:
                    table_att += """|{}|{}|{}|\n""".format(
                        arg['field'],
                        arg['signature'],
                        format_txt(arg['description'])
                    )
            
            # CHECK FOR RAISES
            if item["header"] == "Raises":
                for arg in  item['args']:
                    hint +='\n{% hint style="info" %}\n'
                    hint += arg['signature']+':'+arg['description']+'\n'
                    hint += '{% endhint %}'
            
            # CHECK FOR EXAMPLES
            if item["header"] == "Examples":
                example='**Example**\n\n'
                example += item['text']
            
            # CHECK FOR RETURNS
            if item["header"] == "Returns":
                returns = '**Reutrns**\n\n'
                returns += item['text']
        
        if extracted['source'] == '':
            sig = '`{}`'.format(query)
        else:
            sig = '`{}`'.format(extracted['source'].split('\n')[0])

        return TEMPLATE_FILE.format(
                header, #header
                '{}.py'.format(source_code), #source file in repo: https://github.com/ariG23498/Aritra-Documentation/blob/master/____
                line[0], #line begin
                line[1], #line end
                sig, #function signature: extract['source']
                docstr[0]['text'].lstrip('\n'), #summary
                table_arg, #table_args 
                table_att, #table_att
                hint, #hint
                returns, #returns
                example #example
            )
    else:
        return TEMPLATE_FILE.format(
            header, #header
            '{}.py'.format(source_code), #source file in repo: https://github.com/ariG23498/Aritra-Documentation/blob/master/____
            line[0], #line begin
            line[1], #line end
            '', #function signature: extract['source']
            '', #summary: parse[0]['text']
            '', #table_args 
            '', #table_att
            '', #hint
            '', #returns
            '' #example
        )


# Get the names of the modules
root_path = loaders['search_path']
modules = loaders['modules']
modulename_moduledetails = {}
for module in modules:
    source_code = root_path+'/'+module+'.py'
    module_details = inspect_module(source_code)
    modulename_moduledetails['{}'.format(module)] = module_details


DOCS_PATH = renderer['content_directory']+'/'+renderer['build_directory']
TEMPLATE_FILE = open('template.txt').read()
for group in renderer['groups']:
    # Create GROUP
    GROUP_PATH = DOCS_PATH+'/'+group["title"]
    if not os.path.exists(GROUP_PATH):
        os.makedirs(GROUP_PATH)
    # Create individual PAGES
    for page in group['pages']:
        markdown = ''
        MARKDOWN_FILE = GROUP_PATH+'/'+page['title']+'.md'
        
        # Content for the page [module and names]
        for content in page['contents']:
            module_name = content['module']
            query_names = content['names']
            details = modulename_moduledetails[module_name]
            for query in query_names:
                query_split = query.split('.')

                # CHECK '*'
                if len(query_split) == 1 and query_split[0] == '*':
                    # Iterate over the entire details
                    for detail in details:
                        detail_name = detail[0]
                        detail_name_split = detail_name.split('.')
                        detail_line = detail[1]
                        detail_has_doc = detail[2]
                        if len(detail_name_split) == 1:
                            header = "# {}".format(detail_name)
                        else:
                            header = "## {}".format(detail_name)
                        markdown += '{}\n'.format(create_md(
                            root_path=root_path,
                            source_code=module_name,
                            query=detail_name,
                            line=detail_line,
                            header=header,
                            has_doc=detail_has_doc
                        ))
                
                # CHECK 'Class.*'
                elif len(query_split) == 2 and query_split[1] == '*':
                    # Iterate over the entire details with class name
                    for detail in details:
                        detail_name = detail[0]
                        detail_name_split = detail_name.split('.')
                        detail_line = detail[1]
                        detail_has_doc = detail[2]
                        header = '## {}'.format(detail_name)
                        if len(detail_name_split) == 2 and detail_name_split[0] == query_split[0]:
                            markdown += '{}\n'.format(create_md(
                            root_path=root_path,
                            source_code=module_name,
                            query=detail_name,
                            line=detail_line,
                            header=header,
                            has_doc=detail_has_doc)
                            )

                # Everything else
                else:
                    # Iterate over details and see which one
                    for detail in details:
                        detail_name = detail[0]
                        detail_name_split = detail_name.split('.')
                        detail_line = detail[1]
                        detail_has_doc = detail[2]
                        if detail_name == query:
                            if len(detail_name_split) == 1:
                                header = "# {}".format(detail_name)
                            else:
                                header = "## {}".format(detail_name)
                            markdown += '{}\n'.format(create_md(
                            root_path=root_path,
                            source_code=module_name,
                            query=detail_name,
                            line=detail_line,
                            header=header,
                            has_doc=detail_has_doc)
                            )
        
        # Create the md file
        with open(MARKDOWN_FILE, 'w') as mdf:
            mdf.write(markdown)



