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
            // hide the epoch metric from the UI:
            await run1.DefineMetric("epoch", hidden: true);

            // Log metrics:
            await run1.Log(new Dictionary<string, object> { { "loss", 0.5 }, { "recall", 0.8 }, { "epoch", 1 } });
            await run1.Log(new Dictionary<string, object> { { "loss", 0.4 }, { "recall", 0.95 }, { "epoch", 2 } });
            await run1.Log(new Dictionary<string, object> { { "loss", 0.3 }, { "recall", 0.9 }, { "epoch", 3 } });

            // Finish the run:
            await run1.Finish();

            // Get the last dictionary of metrics logged for run1:
            await session.RunLogTail(run1.Settings.RunId);

            // Resume run1:
            var run2 = await session.Init(
                settings: new Settings(
                    project: "csharp",
                    resume: ResumeOption.Allow, // resume if exists, or create a new run
                    runId: run1.Settings.RunId
                )
            );

            // Get the run's summary:
            var summary = await run2.GetSummary();

            // Update configuration:
            await run2.UpdateConfig(new Dictionary<string, object> { { "learning_rate", 3e-4 } });
            await run2.DefineMetric("recall", "epoch", SummaryType.Max | SummaryType.Mean);
            await run2.DefineMetric("loss", "epoch", SummaryType.Min);
            await run2.DefineMetric("epoch", hidden: true);

            // Log more metrics:
            await run2.Log(new Dictionary<string, object> { { "loss", 0.1 }, { "recall", 0.99 }, { "epoch", 4 } });

            // Finish the resumed run:
            await run2.Finish();
        }
    }
}
