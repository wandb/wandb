# We can import from the top after dropping support for Python 3.6
# import wandb.apis.reports as wr
from .util import coalesce


def create_example_header():
    """Create an example header with image at top."""
    import wandb.apis.reports as wr

    return [
        wr.P(),
        wr.HorizontalRule(),
        wr.P(),
        wr.Image(
            "https://camo.githubusercontent.com/83839f20c90facc062330f8fee5a7ab910fdd04b80b4c4c7e89d6d8137543540/68747470733a2f2f692e696d6775722e636f6d2f676236423469672e706e67"
        ),
        wr.P(),
        wr.HorizontalRule(),
        wr.P(),
    ]


def create_example_footer():
    """Create an example footer with image and text at bottom."""
    import wandb.apis.reports as wr

    return [
        wr.P(),
        wr.HorizontalRule(),
        wr.P(),
        wr.H1("Disclaimer"),
        wr.P(
            "The views and opinions expressed in this report are those of the authors and do not necessarily reflect the official policy or position of Weights & Biases. blah blah blah blah blah boring text at the bottom"
        ),
        wr.P(),
        wr.HorizontalRule(),
    ]


def create_enterprise_report(
    project=None,
    title="Untitled Report",
    description="",
    header=None,
    body=None,
    footer=None,
):
    """Create an example enterprise report with a header and footer.

    Can be used to add custom branding to reports.
    """
    import wandb.apis.reports as wr

    project = coalesce(project, "default-project")
    header = coalesce(header, create_example_header())
    body = coalesce(body, [])
    footer = coalesce(footer, create_example_footer())

    return wr.Report(
        project=project,
        title=title,
        description=description,
        blocks=[*header, *body, *footer],
    )


def create_customer_landing_page(
    project=None,
    company_name="My Company",
    main_contact="My Contact (name@email.com)",
    slack_link="https://company.slack.com",
):
    """Create an example customer landing page using data from Andrew's demo."""
    import wandb.apis.reports as wr

    project = coalesce(project, "default-project")

    return wr.Report(
        project,
        title=f"Weights & Biases @ {company_name}",
        description=f"The developer-first MLOps platform is now available at {company_name}!\nReach out to {main_contact} for an account, and join your dedicated slack channel at:\n{slack_link}",
        blocks=[
            wr.P(),
            wr.HorizontalRule(),
            wr.TableOfContents(),
            wr.P(),
            wr.HorizontalRule(),
            wr.H1(text=["What is Weights & Biases?"]),
            wr.P(
                text=[
                    "Weights & Biases (W&B) is the developer-first MLOps platform to build better models faster.  Over 200,000+ ML practitioners at 500+ companies use W&B to optimize their ML workflows in Natural Language, Computer Vision, Reinforcement Learning, Tabular ML, Finance, and more!"
                ]
            ),
            wr.P(),
            wr.H2(text=["Why do you need W&B?"]),
            wr.P(
                text=[
                    "ML is a highly experimental field.  Often we try many different datasets, model architectures, optimizers, hyperparameters, etc."
                ]
            ),
            wr.P(
                text=["Experimentation is great, but it can get messy.  Have you ever:"]
            ),
            wr.UnorderedList(
                items=[
                    ["Logged experiments in a sketchy spreadsheet?"],
                    [
                        "Built an amazing model but could not reproduce it for a colleague / model validation?"
                    ],
                    ["Wondered why your model is making strange predictions?"],
                    ["Fumbled with tuning hyperparameters?"],
                    [
                        "Struggled explaining to a colleague the impact of what you're doing?"
                    ],
                ]
            ),
            wr.P(
                text=["If that sounds familiar, W&B might be a good solution for you!"]
            ),
            wr.P(),
            wr.H2(
                text=[
                    "What does W&B do?",
                    wr.Link(text="", url="https://wandb.ai/site/experiment-tracking"),
                ]
            ),
            wr.P(
                text=[
                    wr.Link(text="", url="https://wandb.ai/site/experiment-tracking"),
                    "W&B has lightweight and flexible tools for... (expand to see more)",
                ]
            ),
            wr.H3(
                text=[
                    wr.Link(
                        text="Experiment tracking",
                        url="https://wandb.ai/site/experiment-tracking",
                    )
                ]
            ),
            wr.PanelGrid(
                runsets=[
                    wr.Runset(
                        entity="megatruong",
                        project="whirlwind_test4",
                        name="Run set",
                        query="",
                        filters={
                            "$or": [
                                {
                                    "$and": [
                                        {"state": {"$ne": "crashed"}},
                                        {
                                            "config.Learner.value.opt_func": {
                                                "$ne": None
                                            }
                                        },
                                    ]
                                }
                            ]
                        },
                        groupby=["Learner.opt_func"],
                        order=["-CreatedTimestamp"],
                    )
                ],
                panels=[
                    wr.LinePlot(
                        x="Step",
                        y=["gradients/layers.0.4.0.bn1.bias"],
                        log_y=False,
                        groupby="None",
                        layout={"x": 16, "y": 12, "w": 8, "h": 6},
                    ),
                    wr.LinePlot(
                        x="Step",
                        y=["gradients/layers.0.1.weight"],
                        log_y=False,
                        groupby="None",
                        layout={"x": 8, "y": 12, "w": 8, "h": 6},
                    ),
                    wr.LinePlot(
                        x="Step",
                        y=["gradients/layers.0.1.bias"],
                        log_y=False,
                        groupby="None",
                        layout={"x": 0, "y": 12, "w": 8, "h": 6},
                    ),
                    wr.LinePlot(
                        x="Step",
                        y=["train_loss"],
                        log_y=False,
                        groupby="None",
                        layout={"x": 16, "y": 0, "w": 8, "h": 6},
                    ),
                    wr.LinePlot(
                        x="Step",
                        y=["valid_loss"],
                        log_y=False,
                        groupby="None",
                        layout={"x": 16, "y": 6, "w": 8, "h": 6},
                    ),
                    wr.LinePlot(
                        x="Step",
                        y=["top_k_accuracy"],
                        log_y=False,
                        groupby="None",
                        layout={"x": 8, "y": 0, "w": 8, "h": 6},
                    ),
                    wr.LinePlot(
                        x="Step",
                        y=["mom_0"],
                        log_y=False,
                        groupby="None",
                        layout={"x": 0, "y": 6, "w": 8, "h": 6},
                    ),
                    wr.LinePlot(
                        x="Step",
                        y=["lr_0"],
                        log_y=False,
                        groupby="None",
                        layout={"x": 8, "y": 6, "w": 8, "h": 6},
                    ),
                    wr.LinePlot(
                        x="Step",
                        y=["accuracy"],
                        log_y=False,
                        groupby="None",
                        layout={"x": 0, "y": 0, "w": 8, "h": 6},
                    ),
                ],
                custom_run_colors={
                    ("Run set", "megatruong"): "rgb(83, 135, 221)",
                    ("Run set", "fastai.optimizer.ranger"): "rgb(83, 135, 221)",
                    ("Run set", "fastai.optimizer.Adam"): "rgb(229, 116, 57)",
                },
            ),
            wr.P(
                text=[
                    wr.Link(
                        text="",
                        url="https://assets.website-files.com/5ac6b7f2924c656f2b13a88c/6066c22135b8983b61ad7939_weights-and-biases-logo.svg",
                    )
                ]
            ),
            wr.H3(
                text=[
                    wr.Link(
                        text="Dataset and model versioning, evaluation, and reproduction",
                        url="https://wandb.ai/site/artifacts",
                    )
                ]
            ),
            wr.WeaveBlockArtifact(
                entity="megatruong",
                project="whirlwind_test4",
                artifact="camvid_learner",
                tab="lineage",
            ),
            wr.P(),
            wr.H3(
                text=[
                    wr.Link(
                        text="Hyperparameter optimization",
                        url="https://wandb.ai/site/sweeps",
                    )
                ]
            ),
            wr.P(text=[wr.Link(text="", url="https://wandb.ai/site/sweeps")]),
            wr.PanelGrid(
                runsets=[
                    wr.Runset(
                        entity="wandb",
                        project="cartpole",
                        name="Run set",
                        query="sweep",
                        filters={"$or": [{"$and": []}]},
                        order=["-CreatedTimestamp"],
                    )
                ],
                panels=[
                    wr.MediaBrowser(layout={"x": 0, "y": 10, "w": 24, "h": 10}),
                    wr.ParallelCoordinatesPlot(
                        columns=[
                            wr.PCColumn(metric="c::activation"),
                            wr.PCColumn(metric="c::lr", log_scale=True),
                            wr.PCColumn(
                                metric="c::target_model_update",
                                log_scale=True,
                            ),
                            wr.PCColumn(metric="c::n_hidden", log_scale=True),
                            wr.PCColumn(metric="test_reward"),
                        ],
                        layout={"x": 0, "y": 0, "w": 24, "h": 10},
                    ),
                ],
            ),
            wr.H3(
                text=[
                    wr.Link(
                        text="Model visualization and analysis",
                        url="https://wandb.ai/site/tables",
                    )
                ]
            ),
            wr.P(text=[wr.Link(text="", url="https://wandb.ai/site/tables")]),
            wr.PanelGrid(
                runsets=[
                    wr.Runset(
                        entity="megatruong",
                        project="whirlwind_test4",
                        name="Run set",
                        query="",
                        filters={"$or": [{"$and": []}]},
                        order=["-CreatedTimestamp"],
                    )
                ],
                panels=[
                    wr.WeavePanelSummaryTable(
                        table_name="valid_table",
                        layout={"x": 7, "y": 0, "w": 7, "h": 13},
                    ),
                    wr.WeavePanelSummaryTable(
                        table_name="img_table",
                        layout={"x": 0, "y": 0, "w": 7, "h": 13},
                    ),
                    wr.WeavePanelSummaryTable(
                        table_name="image_table",
                        layout={"x": 14, "y": 0, "w": 10, "h": 13},
                    ),
                ],
            ),
            wr.P(),
            wr.PanelGrid(
                runsets=[
                    wr.Runset(
                        entity="wandb",
                        project="wandb_spacy_integration",
                        name="Run set",
                        query="",
                        filters={"$or": [{"$and": []}]},
                        order=["-CreatedTimestamp"],
                    )
                ],
                panels=[
                    wr.WeavePanelSummaryTable(
                        table_name="spaCy NER table",
                        layout={"x": 0, "y": 0, "w": 24, "h": 10},
                    ),
                    wr.WeavePanelSummaryTable(
                        table_name="per annotation scores",
                        layout={"x": 7, "y": 10, "w": 17, "h": 8},
                    ),
                    wr.WeavePanelSummaryTable(
                        table_name="metrics", layout={"x": 0, "y": 10, "w": 7, "h": 8}
                    ),
                ],
            ),
            wr.H3(
                text=[
                    wr.Link(
                        text="ML team collaboration and sharing results",
                        url="https://wandb.ai/site/reports",
                    )
                ]
            ),
            wr.H2(text=["How do I get access?"]),
            wr.P(text=[f"Ask {main_contact} to help:"]),
            wr.OrderedList(
                items=[
                    ["Set up your account"],
                    [
                        "Get added to the ",
                        wr.Link(
                            text="joint slack channel",
                            url=slack_link,
                        ),
                    ],
                ]
            ),
            wr.HorizontalRule(),
            wr.H1(text=["Getting Started"]),
            wr.P(text=["W&B has two components:"]),
            wr.OrderedList(
                items=[
                    ["A centrally managed MLOps platform and UI"],
                    [
                        "The ",
                        wr.InlineCode(code="wandb"),
                        " SDK (",
                        wr.Link(text="github", url="https://github.com/wandb/client"),
                        ", ",
                        wr.Link(text="pypi", url="https://pypi.org/project/wandb/"),
                        ", ",
                        wr.Link(
                            text="conda-forge",
                            url="https://anaconda.org/conda-forge/wandb",
                        ),
                        ")",
                    ],
                ]
            ),
            wr.P(),
            wr.H3(text=["1. Install the SDK"]),
            wr.CodeBlock(code=["pip install wandb"], language="python"),
            wr.P(),
            wr.H3(text=["2. Log in to W&B"]),
            wr.P(text=["You will be prompted to get and set your API key in the UI."]),
            wr.CodeBlock(code=["wandb.login()"], language="python"),
            wr.P(),
            wr.H3(text=["3. Setup an experiment"]),
            wr.P(
                text=[
                    "Add this to the beginning of your scripts (or top of your notebook)."
                ]
            ),
            wr.CodeBlock(code=["wandb.init()"], language="python"),
            wr.P(),
            wr.P(
                text=[
                    wr.Link(
                        text="For more details on options and advanced usage, see the docs.",
                        url="https://docs.wandb.ai/ref/python/init",
                    )
                ]
            ),
            wr.P(),
            wr.H3(text=["4. Log anything!"]),
            wr.P(text=["You can log metrics anywhere in your script, for example"]),
            wr.CodeBlock(code=['wandb.log({"loss": model_loss})'], language="python"),
            wr.P(),
            wr.P(
                text=[
                    "Log metrics, graphs, dataframes, images with segmentation masks or bounding boxes, videos, point clouds, custom HTML, and more!  ",
                    wr.Link(
                        text="For more details on logging, including advanced types, see the docs.",
                        url="https://docs.wandb.ai/guides/track/log",
                    ),
                ]
            ),
            wr.P(text=["W&B also helps you reproduce results by capturing:"]),
            wr.UnorderedList(
                items=[
                    ["git state (repo, commit)"],
                    ["requirements (requirements.txt, conda_env.yml)"],
                    ["logs, including stdout"],
                    [
                        "hardware metrics (CPU, GPU, network, memory utilization, temperature, throughput)"
                    ],
                    ["and more!"],
                ]
            ),
            wr.P(),
            wr.H3(text=["Putting everything together:"]),
            wr.CodeBlock(
                code=[
                    "wandb.login()",
                    "",
                    "wandb.init()",
                    "for i in range(1000):",
                    '    wandb.log({"metric": i})',
                ],
                language="python",
            ),
            wr.P(),
            wr.H1(text=["What else is possible with W&B?"]),
            wr.H2(text=["Example projects"]),
            wr.Gallery(
                ids=[
                    "Vmlldzo4ODc0MDc=",
                    "Vmlldzo4NDI3NzM=",
                    "Vmlldzo2MDIzMTg=",
                    "VmlldzoyMjA3MjY=",
                    "Vmlldzo1NjM4OA==",
                ]
            ),
            wr.P(),
        ],
    )
