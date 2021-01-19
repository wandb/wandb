from .tools import inspect_module
from mydocstring import extract, parse



def module_parser(source_path):
    """
    Generates a dictionary of parsed elements from the source code.

    Args:
        source_path (str) : The path to the source code.
    
    Returns:
        p_module (list[dict]): The parsed module.
    """
    # the parsed module
    p_module = inspect_module(source_path)
    # Here p_module segments has the following keys
    # - name: name
    # - header: header that should appear in docs
    # - doc: the docstring
    count_query = []
    for segment in p_module:
        name = segment['name']
        name_split = name.split('.')

        if len(name_split) == 2:
            if not name_split[0] and not name_split[1]:
                segment['index'] = count_query.count('')
                segment['query'] = ''
                count_query.append('')
                
            else:
                segment['index'] = count_query.count(name_split[1])
                segment['query'] = name_split[1]
                count_query.append(name_split[1])
                
        else:
            segment['index'] = count_query.count(name_split[0])
            segment['query'] = name_split[0]
            count_query.append(name_split[0])
    
    # Here p_module segments has the following keys
    # - name: name
    # - header: header that should appear in docs
    # - doc: the docstring
    # - index: query index
    # - query: the query
    temp_dict = {}
    for segment in p_module:
        if segment['index'] > 0:
            # assign the other docstring
            segment['sig'] = temp_dict[segment['query']][segment['index']]['sig']
        else:
            if segment['doc']:
                d = extract.extract(source_path, segment['query'])
                if type(d) is not dict:
                    # List
                    temp_list = []
                    for item in d:
                        temp_list.append({
                            'sig': f"def {item['function']}{item['signature']}: {item['return_annotation']}",
                            }) 
                    temp_dict[segment['query']] = temp_list
                    segment['sig'] = temp_dict[segment['query']][0]['sig']
                else:
                    # Dict
                    if d["type"] == "function":
                        segment['sig'] = f"def {d['function']}{d['signature']}: {d['return_annotation']}"
                    elif d["type"] == "class":
                        segment['sig'] = f"class {d['class']}{d['signature']}:"
                    else:
                        segment['sig'] = ""
    # Here p_module segments has the following keys
    # - name: name
    # - header: header that should appear in docs
    # - doc: the docstring
    # - index: query index
    # - query: the query
    # - sig: signature
    for segment in p_module:
        list_parse = parse.GoogleDocString(segment['doc']).parse()
        for idx, item in enumerate(list_parse):
            if item["args"]:
                for i, arg in enumerate(item["args"]):
                    list_parse[idx]["args"][i]["description"] = extract.format_txt(arg["description"])
        segment['parse'] = list_parse
    # Here p_module segments has the following keys
    # - name: name
    # - header: header that should appear in docs
    # - doc: the docstring
    # - index: query index
    # - query: the query
    # - sig: signature
    # - parse: {header, args, text} for docstring. args- list of {field, signature, description}
    return p_module


def pretty_docs(components, mytemplate):
# components is a list of component
# component is a dict with keys:
# - md_name
# - module_name
# - query
    for component in components:
        source_code = component['module_name']
        p_module = module_parser(component['module_name'])
        comp_split = component['query'].split('.')
        if component['query'] == '*':
            # The whole module is documented
            with open(component['md_name'], 'a') as f:
                for element in p_module:
                    f.write(mytemplate.render(el=element, source=source_code))
        elif len(comp_split)==2 and comp_split[-1] == "*":
            # Document the class
            for element in p_module:
                if '.'.join(comp_split[:-1]) in element['name'].split('.'):
                    with open(component['md_name'], 'a') as f:
                        f.write(mytemplate.render(el=element, source=source_code))
        else:
            for element in p_module:
                if component['query'] == element['name']:
                    with open(component['md_name'], 'a') as f:
                        f.write(mytemplate.render(el=element, source=source_code))
