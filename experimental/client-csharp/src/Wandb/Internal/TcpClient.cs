using System;
using System.Net.Sockets;
using System.Threading.Tasks;

namespace Wandb.Internal
{
    public class TcpCommunication : IDisposable
    {
        private TcpClient? _client;
        private NetworkStream? _stream;

        public async Task Open(int port)
        {
            _client = new TcpClient();
            await _client.ConnectAsync("localhost", port);
            _stream = _client.GetStream();
        }

        public async Task Send(byte[] data)
        {
            if (_stream == null)
                throw new InvalidOperationException("Connection not open");

            await _stream.WriteAsync(data, 0, data.Length);
        }

        public async Task<byte[]> Receive()
        {
            if (_stream == null)
                throw new InvalidOperationException("Connection not open");

            byte[] buffer = new byte[4096]; // Adjust buffer size as needed
            int bytesRead = await _stream.ReadAsync(buffer, 0, buffer.Length);
            Array.Resize(ref buffer, bytesRead);
            return buffer;
        }

        public void Close()
        {
            _stream?.Close();
            _client?.Close();
            _stream = null;
            _client = null;
        }

        public void Dispose()
        {
            Close();
        }
    }
}
