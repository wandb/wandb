# Wandb Development

## CLI and Library

### Setup

```shell
git clone git@github.com:wandb/client.git
cd client
pip install -e .
pip install -r requirements_dev.txt
```

### Architecture

When `wandb.init()` is called from a user script, communication with a seperate wandb process is coordinated. This is done by creating a pty for stdout and stderr and listening for changes to files in the run directory. If a script is started with `wandb run` the wandb process is started immediately and the user process is started by it. If the script is run directly, the wandb process is started from `wandb.init()`. Communication with the WandB cloud only occurs when `wandb run` is used, or `WANDB_MODE=run` is set in the environment.

### Special Files

The following files can be created by the wandb library in the run directory in all modes.

<dl>
    <dt>description.md</dt>
    <dd>Experiment notes specified with <pre>wandb run -m 'My notes'</pre> or edited via the local web server.</dd>
    <dt>wandb-metadata.json</dt>
    <dd>Data about the run such as git commit, program name, host, directory, exit code, etc.</dd>
    <dt>wandb-summary.json</td>
    <dd>The latest summary metrics generated either from <pre>run.history.add(...)</pre> or <pre>run.summary.update(...)</pre></dt>
    <dt>wandb-history.jsonl</dt>
    <dd>The history metrics added via our callbacks, or manually with <pre>run.history.add(...)</pre></dd>
    <dt>wandb-events.jsonl</dt>
    <dd>System metrics are automatically stored every 30 seconds.  This file can contain custom user metrics as weel</dd>
    <dt>diff.patch</dt>
    <dd>A git diff of any un-commited changes</dd>
    <dt>config.yaml</dt>
    <dd>The config parameters specified in <pre>run.config.update(...)</pre></dd>
    <dt>output.log</dt>
    <dd>The stdout and stderr collected during the run</dd>
</dl>

## WandB Board

WandB Board consists of 2 components: a Flask app which reads from the local filesystem and serves up a Graphql endpoint, and a React based frontend.

### Setup

```shell
cd wandb/board/ui
yarn install
```

### Running the development servers

The flask app can be started in development mode from a directory containing a _wandb_ directory with `WANDB_ENV=dev wandb board`. This will automatically reload when changes are made. The frontend can be run by calling `yarn start` from the _wandb/board/ui_ directory.

### Building the frontend

```shell
yarn release
```
