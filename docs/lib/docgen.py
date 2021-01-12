# USAGE python docgen.py wandb.yml ./template/template.md
import yaml
import sys
import os
from utils import gen

from mako.template import Template


yaml_filename = sys.argv[1]
template_path = sys.argv[2]

mytemplate = Template(filename=template_path)
with open(yaml_filename, 'r') as f:
    p_yaml = yaml.load(f, Loader=yaml.FullLoader)

loaders = p_yaml['loaders']
renderer = p_yaml['renderer']

module_dict = {}
root = loaders['search_path']
for module in loaders["modules"]:
    module_dict[module] = module.replace('.','/')
    module_dict[module] = root+'/'+module_dict[module]+'.py'
# module_dict contain
# - modules in yaml: module in os
# eg
# wandb.apis.public: ./wandb/apis/public.py 

doc_path = f"{renderer['content_directory']}/{renderer['build_directory']}"
os.makedirs(doc_path,exist_ok=True)
pages = []
for page in renderer['pages']:
    # Create the empty pages
    with open(f"{doc_path}/{page['title']}.md", 'w') as f:
        pass
    component = []
    for content in page['contents']:
        s = content.split('.')
        for idx in range(len(s)):
            if module_dict.get('.'.join(s[:idx]),0) != 0:
                component.append({
                    'md_name': f"{doc_path}/{page['title']}.md",
                    'module_name':module_dict['.'.join(s[:idx])],
                    'query':'.'.join(s[idx:])
                })
        pages.append(component)
# pages is a list of all the page components for ind page
# component is a list of individual components
# individual component is a dict with keys:
# - md_name
# - module_name
# - query

for page in pages:
    for component in page:
        source_code = component['module_name']
        p_module = gen.module_parser(component['module_name'])
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
        
