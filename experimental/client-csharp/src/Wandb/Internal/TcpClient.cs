using System;
using System.Net.Sockets;
using System.Threading.Tasks;

namespace Wandb.Internal
{


    public class MessageHeader
    {
        public byte Magic { get; set; }
        public uint DataLength { get; set; }
    }

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

            var header = new MessageHeader
            {
                Magic = (byte)'W',
                DataLength = (uint)data.Length
            };
            await _stream.WriteAsync([header.Magic], 0, 1);
            await _stream.WriteAsync(BitConverter.GetBytes(header.DataLength), 0, 4);

            await _stream.WriteAsync(data, 0, data.Length);
        }

        public async Task<int> ReceiveExactly(byte[] buffer, int offset, int count)
        {
            int bytesRead = 0;
            while (bytesRead < count)
            {
                if (_stream == null)
                    throw new InvalidOperationException("Connection not open");
                int received = await _stream.ReadAsync(buffer, offset + bytesRead, count - bytesRead);
                if (received == 0)
                    throw new EndOfStreamException("Connection closed prematurely");
                bytesRead += received;
            }
            return bytesRead;
        }

        // TODO: Recieve should be reading everything it can and keeping
        // track of the message boundaries in an internal buffer
        public async Task<byte[]> Receive()
        {
            // Read the magic byte
            byte[] magicByte = new byte[1];
            int bytesRead = await ReceiveExactly(magicByte, 0, 1);
            Console.WriteLine($"Read {bytesRead} bytes");
            Console.WriteLine($"Magic byte: {BitConverter.ToString(magicByte)}");

            if (magicByte[0] != (byte)'W')
            {
                Console.WriteLine($"Magic number is not 'W': {magicByte[0]}");
                return Array.Empty<byte>();
            }

            // Read the body length
            byte[] bodyLengthBytes = new byte[4];
            await ReceiveExactly(bodyLengthBytes, 0, 4);
            uint bodyLength = BitConverter.ToUInt32(bodyLengthBytes, 0);
            Console.WriteLine($"Body length: {bodyLength}");

            // Read the body
            byte[] body = new byte[bodyLength];
            await ReceiveExactly(body, 0, (int)bodyLength);
            Console.WriteLine($"Body: {BitConverter.ToString(body)}");

            return body;
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
