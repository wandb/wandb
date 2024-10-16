using Microsoft.Extensions.Logging;
using Wandb;

class Program
{
    public class EpochSummary
    {
        public int Epoch { get; set; }
    }

    static async Task Main()
    {
        using var loggerFactory = LoggerFactory.Create(builder =>
        {
            builder
                .AddConsole() // Add console for the example
                .SetMinimumLevel(LogLevel.Information);
        });

        using (var session = new Session())
        {
            // Verify the apiKey:
            var entity = await session.Authenticate();
            Console.WriteLine($"Logged in as: {entity}");

            // Bad credentials will throw an exception:
            try
            {
                await session.Authenticate("bad-api-key", "https://api.fake.ai");
            }
            catch (Exception e)
            {
                Console.WriteLine($"Bad credentials: {e.Message}");
            }

            // Initialize a new run:
            var run1 = await session.Init(
                settings: new Settings(
                    // apiKey: "my-api",
                    // entity: "my-entity",
                    // displayName: "smart-capybara-42",
                    project: "csharp",
                    runTags: new[] { "c", "sharp" }
                ),
                logger: loggerFactory.CreateLogger<Program>()
            );

            Console.WriteLine($"Run URL: {run1.Settings.RunURL}");

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

            // Finish the run without marking it as finished on the server:
            await run1.Finish(markFinished: false);
            run1.Dispose();

            // Simulate waiting for the next batch of data:
            Console.WriteLine("Waiting for the next batch of data...");
            await Task.Delay(3000);

            // Resume run1:
            var run2 = await session.Init(
                settings: new Settings(
                    // apiKey: "my-api",
                    // entity: "my-entity",
                    project: "csharp",
                    resume: ResumeOption.Allow, // resume if exists, or create a new run
                    runId: run1.Settings.RunId
                ),
                logger: loggerFactory.CreateLogger<Program>()
            );

            // Get the run's summary:
            var epochSummary = await run2.GetSummary<EpochSummary>();
            // Try and get the last logged epoch:
            var lastEpoch = epochSummary?.Epoch ?? -1;
            Console.WriteLine($"Next epoch: {lastEpoch + 1}");

            // Update configuration:
            await run2.UpdateConfig(new Dictionary<string, object> { { "learning_rate", 3e-4 } });
            await run2.DefineMetric("recall", "epoch", SummaryType.Max | SummaryType.Mean);
            await run2.DefineMetric("loss", "epoch", SummaryType.Min);
            await run2.DefineMetric("epoch", hidden: true);

            // Log more metrics:
            await run2.Log(new Dictionary<string, object> { { "loss", 0.1 }, { "recall", 0.99 }, { "epoch", 4 } });

            // Finish the resumed run and mark it as finished on the server:
            await run2.Finish();
            run2.Dispose();
        }
    }
}
