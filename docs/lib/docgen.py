# USAGE python doc_gen_yaml.py wandb.yml ./template/template.md
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
# pages = []
for page in renderer['pages']:
    # Create the empty pages
    with open(f"{doc_path}/{page['title']}.md", 'w') as f:
        pass
    for content in page['contents']:
        components = []
        s = content.split('.')
        for idx in range(len(s)):
            if module_dict.get('.'.join(s[:idx]),0) != 0:
                components.append({
                    'md_name': f"{doc_path}/{page['title']}.md",
                    'module_name':module_dict['.'.join(s[:idx])],
                    'query':'.'.join(s[idx:])
                })
        gen.pretty_docs(components, mytemplate)
