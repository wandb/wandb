# Imports
import subprocess
import re

# Utils
PATTERN = re.compile(r'(.*?\w) +(.*)')
KEYWORDS = ["Options:", "Commands:"]
TEMPLATE = """
{}

{}

{}

{}

{}
""".strip()

def process(command):
    """
    Processes the document and produces
    a parsed dictionary.

    Args:
        command (str): The command eg. wandb in `wandb --help`
    
    Returns:
        str, str, str: usage, summary and the parsed document
    """
    document = subprocess.run(
        f'{command} --help',
        shell=True,
        capture_output=True,
        text=True).stdout
    summary = []
    keyword = None
    parsed_dict = {}

    for line in document.split('\n'):
        line = line.strip()
        if line in KEYWORDS:
            parsed_dict[line] = []
            keyword = line
            continue
        if keyword is None:
            summary.append(line)
        else:
            extract = PATTERN.findall(line)
            if extract:
                parsed_dict[keyword].append([extract[0][0], extract[0][1]])
    
    if len(summary) == 0:
        return '', '', parsed_dict
    elif len(summary) == 1:
        return summary[0], '', parsed_dict
    else:
        usage = summary[0]
        summary = '\n'.join(summary[1:])
        return usage, summary, parsed_dict


def markdown_render(command):
    """
    Renders the markdown and also provides
    the commands nested in it.

    Args:
        command (str): The command that is exectued `wandb command --help`
    
    Returns:
        commands: The nested commands in the parsed dictionary
    """
    usage, summary, parsed_dict = process(command)
    if usage:
        usage = usage.split(':')
        usage=f"**Usage**\n\n`{usage[1]}`"
    if summary:
        summary=f"**Summary**\n{summary}"
    options = ''
    commands = ''
    op = True
    for k,v in parsed_dict.items():
        for element in v:
            if k == "Options:":
                des = ' '.join(list(filter(lambda x: x, element[1].split(' ')[1:]))) if element[1].split(' ')[0].isupper() else element[1]
                options += """|{}|{}|\n""".format(element[0],des) 
        if options and op:
            options = """**Options**\n| **Options** | **Description** |\n|:--|:--|:--|\n""" + options
            op = False
    if usage or summary or options or commands:
        if len(command.split(' ')) > 2:
            head = f'## {command}'
        else:
            head = f'# {command}'
        with open("cli.md", 'a') as fp:
            fp.write(
                TEMPLATE.format(
                    head, # Heading
                    usage, # Usage
                    summary,
                    options, # Options
                    commands  # Commands
                )
            )
    for k,v in parsed_dict.items():
        for element in v:
            if k == "Commands:":
                markdown_render(f'{command} {element[0]}')


########## BEGIN First pass for wandb
usage, summary, parsed_dict = process('wandb')
if usage:
    usage = usage.split(':')[1]
    usage=f"**Usage**\n\n`{usage}`"
if summary:
    summary=f"**Summary**\n{summary}"
options = ''
commands = ''
op_flag = True
co_flag = True
for k,v in parsed_dict.items():
    for element in v:
        if k == "Options:":
            des = ' '.join(list(filter(lambda x: x, element[1].split(' ')[1:]))) if element[1].split(' ')[0].isupper() else element[1]
            options += """|{}|{}|\n""".format(element[0],des) 
        elif k == "Commands:":
            des = ' '.join(list(filter(lambda x: x, element[1].split(' ')[1:]))) if element[1].split(' ')[0].isupper() else element[1]
            commands += """|{}|{}|\n""".format(element[0],des)
    if options and op_flag:
        options = """**Options**\n| **Options** | **Description** |\n|:--|:--|:--|\n""" + options
        op_flag = False
    if commands and co_flag:
        commands = """**Commands**\n| **Commands** | **Description** |\n|:--|:--|:--|\n""" + commands
        co_flag = False
if usage or summary or options or commands:
    with open("cli.md", 'w') as fp:
        fp.write(
            TEMPLATE.format(
                f"# wandb", # Heading
                usage, # Usage
                summary,
                options, # Options
                commands  # Commands
                )
            )
########## END First pass for wandb

commands = parsed_dict["Commands:"]
for command in commands:
    markdown_render(f'wandb {command[0]}')