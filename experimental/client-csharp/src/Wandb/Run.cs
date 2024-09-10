using System;
using System.Threading.Tasks;
using Wandb.Internal;
using System.Text.Json;
using WandbInternal;

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
            Console.WriteLine("{0}", deliverRunResult);
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

            Console.WriteLine("Settings: {0}", Settings.ToString());
        }

        public async Task Log(object data)
        {
            byte[] serializedData = SerializeData(data);
            // await _interface.Publish(serializedData);
        }

        public async Task Finish()
        {
            // Send finish command
            // await _interface.Deliver(new byte[] { /* finish command */ });
        }

        private byte[] SerializeData(object data)
        {
            // Convert the object to JSON, then to bytes
            string jsonString = JsonSerializer.Serialize(data);
            return System.Text.Encoding.UTF8.GetBytes(jsonString);
        }
    }
}
