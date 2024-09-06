using System;
using System.Threading.Tasks;
using Wandb.Internal;

namespace Wandb
{
    public class Session : IDisposable
    {
        private readonly Manager _manager;
        private readonly SocketInterface _interface;
        private bool _isInitialized = false;
        private int? _port = null;

        public Session()
        {
            _manager = new Manager();
            _interface = new SocketInterface();
        }

        public async Task<Run> InitRun()
        {
            if (!_isInitialized)
            {
                var timeout = TimeSpan.FromSeconds(30); // Adjust as needed
                _port = await _manager.LaunchCore(timeout);
                await _interface.Initialize(_port.Value);
                _isInitialized = true;
            }

            // Here you would typically send a command to initialize a new run
            // and receive a run ID or other necessary information
            var runInfo = await _interface.Deliver(new byte[] { /* init run command */ });

            return new Run(_interface, runInfo);
        }

        public void Dispose()
        {
            _manager.Dispose();
            _interface.Dispose();
        }
    }
}
