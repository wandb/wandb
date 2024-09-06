using System;
using System.Threading.Tasks;
using Wandb.Internal;
using System.Text.Json;

namespace Wandb
{
    public class Run
    {
        private readonly SocketInterface _interface;
        private readonly byte[] _runInfo;

        internal Run(SocketInterface @interface, byte[] runInfo)
        {
            _interface = @interface;
            _runInfo = runInfo;
        }

        public async Task Log(object data)
        {
            byte[] serializedData = SerializeData(data);
            await _interface.Publish(serializedData);
        }

        public async Task Finish()
        {
            // Send finish command
            await _interface.Deliver(new byte[] { /* finish command */ });
        }

        private byte[] SerializeData(object data)
        {
            // Convert the object to JSON, then to bytes
            string jsonString = JsonSerializer.Serialize(data);
            return System.Text.Encoding.UTF8.GetBytes(jsonString);
        }
    }
}
