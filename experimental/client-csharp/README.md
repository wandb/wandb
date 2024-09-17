# Wandb C# Client (Experimental)

This is an experimental C# client for [Weights & Biases](https://wandb.ai/), the AI developer platform.

## Features

- **Session Management**: Initialize and manage sessions using the `Session` class.
- **Run Tracking**: Start, resume, and finish runs with the `Run` class.
- **Configuration Management**: Update configurations during a run.
- **Metric Logging**: Define metrics with custom summary statistics and log data points.
- **Resume Functionality**: Resume previous runs and continue logging data.

## Example

Below is an example demonstrating how to use the client:

```csharp
using System;
using System.Threading.Tasks;
using Wandb;

class Program
{
    static async Task Main()
    {
        using (var session = new Session())
        {
            // Initialize a new run:
            var run1 = await session.Init(
                settings: new Settings(
                    project: "csharp"
                )
            );

            // Define configuration and metrics:
            await run1.UpdateConfig(new Dictionary<string, object> { { "batch_size", 64 } });
            await run1.DefineMetric("recall", "epoch", SummaryType.Max | SummaryType.Mean);
            await run1.DefineMetric("loss", "epoch", SummaryType.Min);

            // Log metrics:
            await run1.Log(new Dictionary<string, object> { { "loss", 0.5 }, { "recall", 0.8 }, { "epoch", 1 } });
            await run1.Log(new Dictionary<string, object> { { "loss", 0.4 }, { "recall", 0.95 }, { "epoch", 2 } });
            await run1.Log(new Dictionary<string, object> { { "loss", 0.3 }, { "recall", 0.9 }, { "epoch", 3 } });

            // Finish the run:
            await run1.Finish();

            // Resume run1:
            var run2 = await session.Init(
                settings: new Settings(
                    project: "csharp",
                    resume: ResumeOption.Allow, // resume if exists, or create a new run
                    runId: run1.Settings.RunId
                )
            );
            // Update configuration:
            await run2.UpdateConfig(new Dictionary<string, object> { { "learning_rate", 3e-4 } });
            await run2.DefineMetric("recall", "epoch", SummaryType.Max | SummaryType.Mean);
            await run2.DefineMetric("loss", "epoch", SummaryType.Min);

            // Log more metrics:
            await run2.Log(new Dictionary<string, object> { { "loss", 0.1 }, { "recall", 0.99 }, { "epoch", 4 } });

            // Finish the resumed run:
            await run2.Finish();
        }
    }
}
```

## Prerequisites

Before building and running this example, ensure that .NET is installed on your machine. For detailed installation instructions, visit the official [Microsoft .NET installation guide](https://learn.microsoft.com/en-us/dotnet/core/install/).

## Building and Running the Example

To build and run the example, you can use the following script:

```bash
#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Move to the script's directory
cd "$(dirname "$0")"

# Build the Wandb library
echo "Building Wandb library..."
dotnet build ../../src/Wandb/Wandb.csproj

# Build the example project
echo "Building Basic example..."
dotnet build Basic.csproj

# Run the example
echo "Running Basic example..."
dotnet run --project Basic.csproj

echo "Example completed."
```

## Available Features

### Session Class

- **Session Initialization**: Create a new session to manage runs using `Session`.
- **Setup**: Prepare the session environment and launch necessary services with `Setup`.

### Run Class

- **Initialization**: Start a new run or resume an existing one using `Init`.
- **Configuration Management**:
  - Access and modify run configurations via the `Config` property.
  - Subscribe to configuration updates with the `ConfigUpdated` event.
- **Metric Definition**:
  - Define custom metrics using `DefineMetric`.
  - Specify summary statistics like `Min`, `Max`, `Mean`, and `Last` with `SummaryType`.
- **Logging**:
  - Log data points using the `Log` method.
- **Run Completion**:
  - Finish runs properly using the `Finish` method.
- **Resume Runs**:
  - Resume previous runs by specifying `resume` and `runId` in `Settings`.

## Note

This client is experimental and does not support all features of the official wandb clients. Contributions and feedback are welcome.
