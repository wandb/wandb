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
            run1.Config["batch_size"] = 64;
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
                    resume: ResumeOption.Must,
                    runId: run1.Settings.RunId
                )
            );
            // Update configuration:
            run2.Config["learning_rate"] = 3e-4;
            await run2.DefineMetric("recall", "epoch", SummaryType.Max | SummaryType.Mean);
            await run2.DefineMetric("loss", "epoch", SummaryType.Min);

            // Log more metrics:
            await run2.Log(new Dictionary<string, object> { { "loss", 0.1 }, { "recall", 0.99 }, { "epoch", 4 } });

            // Finish the resumed run:
            await run2.Finish();
        }
    }
}
