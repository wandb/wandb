using System;
using System.Threading.Tasks;
using Wandb;

class Program
{
    static async Task Main()
    {
        using (var session = new Session())
        {
            var run1 = await session.Init(
                settings: new Settings(
                    project: "csharp"
                )
            );

            run1.Config["batch_size"] = 64;

            await run1.DefineMetric("recall", "epoch", SummaryType.Max | SummaryType.Mean);
            await run1.DefineMetric("loss", "epoch", SummaryType.Min);

            await run1.Log(new Dictionary<string, object> { { "loss", 0.5 }, { "recall", 0.8 }, { "epoch", 1 } });
            await run1.Log(new Dictionary<string, object> { { "loss", 0.4 }, { "recall", 0.95 }, { "epoch", 2 } });
            await run1.Log(new Dictionary<string, object> { { "loss", 0.3 }, { "recall", 0.9 }, { "epoch", 3 } });

            await run1.Finish();

            // Another run
            // var run2 = await session.Init(
            //     settings: new Settings(
            //         project: "csharp"
            //     )
            // );
            // await run2.Log(new Dictionary<string, object> { { "loss", 0.3 } });
            // await run2.Finish();
        }
    }
}
