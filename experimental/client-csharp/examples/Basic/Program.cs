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
            await run1.Log(new Dictionary<string, object> { { "loss", 0.5 } });
            run1.Config["batch_size"] = 64;
            await run1.Finish();

            // Another run
            var run2 = await session.Init(
                settings: new Settings(
                    project: "csharp"
                )
            );
            await run2.Log(new Dictionary<string, object> { { "loss", 0.3 } });
            await run2.Finish();
        }
    }
}
