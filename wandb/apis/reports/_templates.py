import wandb.apis.reports as wr


def analysis(title, text):
    return [wr.H1(title), wr.P(text)]


def create_customer_landing_page(project_name, company_name, main_contact):
    return wr.Report(
        project_name,
        title=f"Weights & Biases @ {company_name}",
        description=f"The developer-first MLOps platform is now available at {company_name}!\nReach out to {main_contact} for an account",
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
            wr.H3(
                text=[
                    wr.Link(
                        text="Dataset and model versioning, evaluation, and reproduction",
                        url="https://wandb.ai/site/artifacts",
                    )
                ]
            ),
            wr.H3(
                text=[
                    wr.Link(
                        text="Hyperparameter optimization",
                        url="https://wandb.ai/site/sweeps",
                    )
                ]
            ),
            wr.H3(
                text=[
                    wr.Link(
                        text="Model visualization and analysis",
                        url="https://wandb.ai/site/tables",
                    )
                ]
            ),
            wr.H3(
                text=[
                    wr.Link(
                        text="ML team collaboration and sharing results",
                        url="https://wandb.ai/site/reports",
                    )
                ]
            ),
            wr.P(),
            wr.UnorderedList(
                items=[
                    [
                        wr.Link(
                            text="Experiment tracking",
                            url="https://wandb.ai/site/experiment-tracking",
                        )
                    ],
                    [
                        wr.Link(
                            text="Dataset and model versioning, evaluation, and reproduction",
                            url="https://wandb.ai/site/artifacts",
                        )
                    ],
                    [
                        wr.Link(
                            text="Hyperparameter optimization",
                            url="https://wandb.ai/site/sweeps",
                        )
                    ],
                    [
                        wr.Link(
                            text="Model visualization and analysis",
                            url="https://wandb.ai/site/tables",
                        )
                    ],
                    [
                        wr.Link(
                            text="ML team collaboration and sharing results",
                            url="https://wandb.ai/site/reports",
                        )
                    ],
                ]
            ),
            wr.P(),
            wr.P(
                text=[
                    "If you use a popular framework or library, W&B has integrations that make logging even easier.  In many cases, integrations are in just one line of code (yes, really!)"
                ]
            ),
            wr.UnorderedList(
                items=[
                    [
                        wr.Link(
                            text="PyTorch",
                            url="https://docs.wandb.ai/guides/integrations/pytorch",
                        )
                    ],
                    [
                        wr.Link(
                            text="Keras",
                            url="https://docs.wandb.ai/guides/integrations/keras",
                        )
                    ],
                    [
                        wr.Link(
                            text="Kubeflow Pipelines",
                            url="https://docs.wandb.ai/guides/integrations/other/kubeflow-pipelines-kfp",
                        )
                    ],
                    [
                        wr.Link(
                            text="HuggingFace Transformers",
                            url="https://docs.wandb.ai/guides/integrations/huggingface",
                        )
                    ],
                    [
                        wr.Link(
                            text="Scikit-Learn",
                            url="https://docs.wandb.ai/guides/integrations/scikit",
                        )
                    ],
                    [
                        wr.Link(
                            text="XGBoost",
                            url="https://docs.wandb.ai/guides/integrations/xgboost",
                        )
                    ],
                    [
                        wr.Link(
                            text="More integrations here",
                            url="https://docs.wandb.ai/guides/integrations",
                        )
                    ],
                ]
            ),
            wr.P(),
            wr.P(
                text=[
                    wr.Link(text="", url="https://wandb.ai/site/reports"),
                    "You're looking at it -- reports!  In addition to what you see here, you can actually hover over text and leave comments ",
                    "like this",
                    "!",
                ]
            ),
            wr.P(),
            wr.H2(text=["How do I get access?"]),
            wr.P(text=["Ask Matthew Schirmer to help:"]),
            wr.OrderedList(
                items=[
                    ["Set up your account"],
                    [
                        "Get added to the ",
                        wr.Link(
                            text="joint slack channel",
                            url="https://rbc-to.slack.com/archives/C031XE9S537",
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
                        InlineCode(code="wandb"),
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
                        text="For more details on options and advanced usage, see the docs for ",
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
