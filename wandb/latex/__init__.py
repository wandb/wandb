"""
Helper function for exporting reports to latex

You must install pandoc to use this library.

Example:

report_path = "stacey/keras_finetune"
report_name = "Curriculum Learning with Nature Photos"
filename = "report.tex"

api = wandb.Api()
report = api.reports(report_path, name=report_name)[0]

report_latex = wandb.latex.report_to_latex(report)

file = open(filename, "w")
file.write(report_latex)
file.close()
"""
import pypandoc
import pandas as pd

def runs_to_df(runs):
    summary_list = []
    config_list = []
    name_list = []
    for run in runs:
        # run.summary are the output key/values like accuracy.  We call ._json_dict to omit large files
        summary_list.append(run.summary._json_dict)

        # run.config is the input metrics.  We remove special values that start with _.
        config_list.append({k: v for k, v in run.config.items() if not k.startswith('_')})

        # run.name is the name of the run.
        name_list.append(run.name)

    summary_df = pd.DataFrame.from_records(summary_list)
    config_df = pd.DataFrame.from_records(config_list)
    name_df = pd.DataFrame({'name': name_list})
    all_df = pd.concat([name_df, config_df, summary_df], axis=1)

    # should put smarter logic in here to drop all columns that are non-numeric or strings
    all_df = all_df.drop(['graph'], axis=1)

    return all_df


HEADER = r"""
\documentclass{article}
\usepackage{graphicx}
\usepackage{csvsimple}
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{hyperref}

\providecommand{\tightlist}{%
  \setlength{\itemsep}{0pt}\setlength{\parskip}{0pt}}
\title{TITLE}
\author{%
  AUTHOR
}
\begin{document}
\maketitle"""

FOOTER = r"""
\begin{thebibliography}{9}
\bibitem{wandb} 
  Weights and Biases,
  \\\texttt{http://wandb.com}
\end{thebibliography}
\end{document}
"""


def markdown_to_latex(markdown):
    latex= pypandoc.convert_text(markdown, "latex", format="markdown")
    return latex


def section_to_latex(section):
    section_latex = ""
    title = section['name']
    for panel in section['panels']['views']['0']['config']:
        if panel['viewType'] == "Markdown Panel":
            section_latex += markdown_to_latex(panel['config']['value'])

    return section_latex


def runs_table_to_latex(runs, columns=None):
    """
    Converts runs to a latex table

    Args:
    runs (Runs): the Runs object to convert
    columns (str or None): the columns to use for tables.  If None, use all columns.

    Returns:
    A str which is a latex table
    """

    df = runs_to_df(runs)

    if columns:
        filtered_cols_df = pd.DataFrame(df, columns=columns)
    else:
        filtered_cols_df = df

    return filtered_cols_df.to_latex(longtable=True)


def report_to_latex(report, columns=None):
    """
    Converts a report object to latex

    Args:
    - report (Report): the Report object to convert
    - columns (str or None): the columns to use for tables.  If None, use all columns.

    Returns:
    A str which is a latex document
    """
    report_latex = ""
    report_latex += HEADER.replace("AUTHOR", report.entity).replace("TITLE", report.name)
    for section in report.sections:
        report_latex += section_to_latex(section)

        runs = report.runs(section)
        report_latex += runs_table_to_latex(runs, columns)

    report_latex += FOOTER
    return report_latex


