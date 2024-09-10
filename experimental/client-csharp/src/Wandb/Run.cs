using System;
using System.Threading.Tasks;
using Wandb.Internal;
using WandbInternal;
using System.Text;

namespace Wandb
{
    public class Run
    {
        private readonly SocketInterface _interface;
        public Settings Settings;

        internal Run(SocketInterface @interface, Settings settings)
        {
            _interface = @interface;
            Settings = settings;
        }

        public async Task Init()
        {
            await _interface.InformInit(Settings, Settings.RunId);
            Result deliverRunResult = await _interface.DeliverRun(this);
            if (deliverRunResult.RunResult == null)
            {
                throw new Exception("Failed to deliver run");
            }

            RunUpdateResult runResult = deliverRunResult.RunResult;
            if (runResult.Error != null)
            {
                throw new Exception(runResult.Error.Message);
            }

            // save project, entity and displa name to settings
            Settings.Project = runResult.Run.Project;
            Settings.Entity = runResult.Run.Entity;
            Settings.DisplayName = runResult.Run.DisplayName;

            Result result = await _interface.DeliverRunStart(this);
            if (result.Response == null)
            {
                throw new Exception("Failed to deliver run start");
            }
            Console.WriteLine($"wandb: Run {Settings.RunId} is live at {Settings.RunURL}");
        }


        public async Task Log(Dictionary<string, object> data)
        {
            await _interface.PublishPartialHistory(Settings.RunId, data);
        }

        public async Task Finish()
        {
            Result deliverExitResult = await _interface.DelieverExit(streamId: Settings.RunId);
            if (deliverExitResult.ExitResult == null)
            {
                throw new Exception("Failed to deliver exit");
            }
            // Send finish command
            await _interface.InformFinish(Settings.RunId);
            Console.WriteLine($"wandb: Run {Settings.RunId} is finished at {Settings.RunURL}");
        }
    }
}
