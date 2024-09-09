using System;
using System.Threading.Tasks;
using Wandb.Internal;
using System.Text.Json;

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
            await _interface.InformInit(Settings, Settings.GetRunId());
            await _interface.DeliverRun(this);
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
