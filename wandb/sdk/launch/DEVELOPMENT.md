## Testing

### Integration tests with local kind cluster

#### Prerequisites
Make sure you have [kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation) and [kubectl](https://kubernetes.io/docs/tasks/tools/) installed.

Set up a Kubernetes queue on W&B beforehand to test against.

#### Cluster setup

```bash
# Create cluster
kind create cluster --name launch-test

# Switch context (if not done automatically)
kubectl config use-context kind-launch-test

# Grant the agent permission to manage secrets and jobs
kubectl create clusterrole launch-agent-role \
  --verb=get,list,watch,create,update,patch,delete \
  --resource=secrets,jobs,pods,pods/log,services,deployments,namespaces
kubectl create clusterrolebinding launch-agent-binding \
  --clusterrole=launch-agent-role \
  --serviceaccount=default:default

# Tear down when done
kind delete cluster --name launch-test
```

#### Build and run the agent

Build the agent image from the current local branch (note: the full repo is the build context):

```bash
docker build -t <image-name> -f tools/launch_release/build/Dockerfile .
kind load docker-image <image-name> --name launch-test
```

To build from a pushed branch instead of local source:

```bash
docker build -t <image-name> -f tools/launch_release/build/Dockerfile \
  --build-arg REF=<branch-name> .
```

Run the agent:

```bash
kubectl run launch-agent \
  --image=<image-name> \
  --image-pull-policy=Never \
  --env="WANDB_API_KEY=<api-key>" \
  -- -q <queue-name> -e <entity>
```

#### Submitting test jobs

```bash
wandb launch \
  [--uri <git-repo-url> | --job <entity>/<project>/<job>:<version>] \
  --entry-point "<entrypoint>" \
  --queue <queue-name> \
  --entity <entity> \
  --project <project> \
  [--config '<json-overrides>']
```

Key overrides via `--config`:

| Override | Effect | Example |
| --- | --- | --- |
| `overrides.working_dir` | Sets working directory inside the emptyDir volume to `/mnt/wandb/<dir>`. Useful when the entrypoint and requirements are in a subdirectory. | `"jobs/hello_world"` |
| `overrides.entry_point` | Overrides the job entrypoint | `["python", "train.py"]` |

#### Working example: `hello_world` from [wandb/launch-jobs](https://github.com/wandb/launch-jobs)

**Git URI job** — clones the repo in the init container, uses `working_dir` to point at the subdirectory containing `job.py` and `requirements.txt`:

```bash
wandb launch \
  --uri https://github.com/wandb/launch-jobs \
  --entry-point "python job.py" \
  --queue <queue-name> \
  --entity <entity> \
  --project <project> \
  --config '{"overrides": {"working_dir": "jobs/hello_world"}}'
```

**Artifact job** — create the job artifact once, then launch it repeatedly:

```bash
# Clone the repo and create the artifact from the hello_world subdirectory
git clone https://github.com/wandb/launch-jobs
wandb job create code launch-jobs/jobs/hello_world \
  --entry-point "python job.py" \
  --entity <entity> \
  --project <project> \
  --name hello-world

# Launch it
wandb launch \
  --job <entity>/<project>/hello-world:latest \
  --queue <queue-name> \
  --entity <entity> \
  --project <project>
```

#### Generic examples

Git URI job:

```bash
wandb launch \
  --uri https://github.com/<org>/<repo> \
  --entry-point "python <script>.py" \
  --queue <queue-name> \
  --entity <entity> \
  --project <project> \
  --config '{"overrides": {"working_dir": "<subdir>"}}'
```

Artifact job:

```bash
wandb job create code <path-to-code> \
  --entry-point "python <script>.py" \
  --entity <entity> \
  --project <project> \
  --name <job-name>

wandb launch \
  --job <entity>/<project>/<job-name>:<version> \
  --queue <queue-name> \
  --entity <entity> \
  --project <project>
```
