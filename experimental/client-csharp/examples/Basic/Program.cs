using System;
using System.Threading.Tasks;
using Wandb;

class Program
{
    static async Task Main()
    {
        using (var session = new Session())
        {
            var run1 = await session.Init(project: "csharp");
            await run1.Log(new Dictionary<string, object> { { "loss", 0.5 } });

            run1.Config["batch_size"] = 64;
            // add some sleep to simulate training
            await Task.Delay(5000);



            await run1.Finish();

            // // You can create multiple runs in the same session
            // var run2 = await session.Init();
            // await run2.Log(new Dictionary<string, object> { { "loss", 0.3 } });
            // await run2.Finish();
        }
    }
}
