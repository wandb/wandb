using System;
using System.Threading.Tasks;

namespace Wandb.Internal
{
    public class SocketInterface : IDisposable
    {
        private readonly TcpCommunication _tcpCommunication;
        private int _port;

        public SocketInterface(int port)
        {
            _port = port;
            _tcpCommunication = new TcpCommunication();
        }

        public async Task Initialize()
        {
            await _tcpCommunication.Open(_port);
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
