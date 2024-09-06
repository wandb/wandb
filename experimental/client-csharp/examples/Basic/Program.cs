using System;
using System.Threading.Tasks;
using Wandb;

class Program
{
    static async Task Main()
    {
        using (var session = new Session())
        {
            var run1 = await session.InitRun();
            // await run1.Log(new { loss = 0.5, step = 1 });
            // await run1.Finish();

            // // You can create multiple runs in the same session
            // var run2 = await session.InitRun();
            // await run2.Log(new { loss = 0.3, step = 1 });
            // await run2.Finish();
        }
    }
}
