using System;
using System.Threading.Tasks;

namespace Wandb.Internal
{
    public class SocketInterface : IDisposable
    {
        private readonly TcpCommunication _tcpCommunication;

        public SocketInterface()
        {
            _tcpCommunication = new TcpCommunication();
        }

        public async Task Initialize(int port)
        {
            await _tcpCommunication.Open(port);
        }

        public async Task Publish(byte[] data)
        {
            await _tcpCommunication.Send(data);
        }

        public async Task<byte[]> Deliver(byte[] data)
        {
            await _tcpCommunication.Send(data);
            return await _tcpCommunication.Receive();
        }

        public void Dispose()
        {
            _tcpCommunication.Dispose();
        }
    }
}
