# Environment Variables

When you're running a script in an automated environment, you can control **wandb** with environment variables set before the script runs or within the script.

```bash
# This is secret and shouldn't be checked into version control
WANDB_API_KEY=$YOUR_API_KEY
# Description is optional
WANDB_DESCRIPTION="$SHORT_MESSAGE"
```

```bash
# Only needed if you don't checkin the wandb/settings file
WANDB_ENTITY=$username
WANDB_PROJECT=$project
```

```python
# If you don't want your script to sync to the cloud
os.environ['WANDB_MODE'] = 'dryrun'
```

Optional environment variables:

| Variable name | Usage |
| :--- | :--- |
| **WANDB\_API\_KEY** | Sets the authentication key associated with your account. You can find your key on your [profile page](https://app.wandb.ai/profile). This must be set if `wandb login` hasn't been run on the remote machine. |
| **WANDB\_DESCRIPTION** | Description associated with a run. This will become the name of your run in the UI. If not set it will be randomly generated for you |
| **WANDB\_ENTITY** | The entity associated with your run. If you have run `wandb init` in the directory of your training script, it will create a directory named _wandb_ and will save a default entity which can be checked into source control. If you don't want to create that file or want to override the file you can use the environmental variable. |
| **WANDB\_USERNAME** | The username of a member of your team associated with the run. This can be used along with a service account API key to enable attribution of automated runs to members of your team. |
| **WANDB\_PROJECT** | The project associated with your run. This can also be set with `wandb init`, but the environmental variable will override the value. |
| **WANDB\_MODE** | By default this is set to _run_ which saves results to wandb. If you just want to save your run metadata locally, you can set this to _dryrun_. |
| **WANDB\_TAGS** | A comma separated list of tags to be applied to the run. |
| **WANDB\_DIR** | Set this to an absolute path to store all generated files here instead of the _wandb_ directory relative to your training script. _be sure this directory exists and the user your process runs as can write to it_ |
| **WANDB\_RESUME** | By default this is set to _never_. If set to _auto_ wandb will automatically resume failed runs. If set to _must_ forces the run to exist on startup. If you want to always generate your own unique ids, set this to _allow_ and always set **WANDB\_RUN\_ID**. |
| **WANDB\_RUN\_ID** | Set this to a globally unique string \(per project\) corresponding to a single run of your script. It must be no longer than 64 characters. All non-word characters will be converted to dashes. This can be used to resume an existing run in cases of failure. |
| **WANDB\_IGNORE\_GLOBS** | Set this to a comma separated list of file globs to ignore. These files will not be synced to the cloud. |
| **WANDB\_ERROR\_REPORTING** | Set this to false to prevent wandb from logging fatal errors to its error tracking system. |
| **WANDB\_SHOW\_RUN** | Set this to **true** to automatically open a browser with the run url if your operating system supports it. |
| **WANDB\_DOCKER** | Set this to a docker image digest to enable restoring of runs. This is set automatically with the wandb docker command. You can obtain an image digest by running `wandb docker my/image/name:tag --digest` |
| **WANDB\_DISABLE\_CODE** | Set this to true to prevent wandb from storing a reference to your source code |
| **WANDB\_ANONYMOUS** | Set this to "allow", "never", or "must" to let users create anonymous runs with secret urls. |
| **WANDB\_CONFIG\_DIR** | This defaults to ~/.config/wandb, you can override this location with this environment variable |
| **WANDB\_NOTEBOOK\_NAME** | If you're running in jupyter you can set the name of the notebook with this variable. We attempt to auto detect this. |
| **WANDB\_HOST** | Set this to the hostname you want to see in the wandb interface if you don't want to use the system provided hostname |
| **WANDB\_SILENT** | Set this to **true** to silence wandb log statements. If this is set all logs will be written to **WANDB\_DIR**/debug.log |

