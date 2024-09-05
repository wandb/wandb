using System;
using System.Threading.Tasks;
using Wandb.Internal;
// using Wandb.Interfaces;

namespace Wandb
{
    public class WandbClient : IDisposable
    {
        private readonly Manager _manager;
        // private readonly ITcpCommunication _tcpCommunication;

        // public WandbClient(ITcpCommunication tcpCommunication)
        public WandbClient()
        {
            _manager = new Manager();
            // _tcpCommunication = tcpCommunication;
        }

        public async Task InitializeAsync()
        {
            var timeout = TimeSpan.FromSeconds(30); // Adjust as needed
            int port = await _manager.LaunchCore(timeout);
            // print port
            Console.WriteLine($"Port: {port}");
            // await _tcpCommunication.ConnectAsync("localhost", port);
        }

        // ... rest of the class implementation ...

        public void Dispose()
        {
            _manager.Dispose();
            // _tcpCommunication.Disconnect();
        }
    }
}
