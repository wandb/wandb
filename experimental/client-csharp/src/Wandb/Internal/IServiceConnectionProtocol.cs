using System.Net.Sockets;

namespace Wandb.Internal
{
    /// <summary>
    /// A way to establish a connection to the service.
    /// </summary>
    public interface IServiceConnectionProtocol
    {
        /// <summary>
        /// Opens a connection to the service.
        /// </summary>
        /// <returns>A connected socket.</returns>
        Socket Connect();
    }

    /// <summary>
    /// Connects to the service over a localhost socket.
    /// </summary>
    public sealed class TcpConnectionProtocol : IServiceConnectionProtocol
    {
        private readonly int _port;

        public TcpConnectionProtocol(int port)
        {
            _port = port;
        }

        /// <inheritdoc />
        public Socket Connect()
        {
            var socket = new Socket(
                AddressFamily.InterNetwork,
                SocketType.Stream,
                ProtocolType.Tcp
            );

            socket.Connect("localhost", _port);

            return socket;
        }
    }

    /// <summary>
    /// Connects to the service using a Unix domain socket.
    /// </summary>
    public sealed class UnixSocketProtocol : IServiceConnectionProtocol
    {
        private readonly string _path;

        public UnixSocketProtocol(string path)
        {
            _path = path;
        }

        /// <inheritdoc />
        public Socket Connect()
        {
            var socket = new Socket(
                AddressFamily.Unix,
                SocketType.Stream,
                ProtocolType.Unspecified
            );

            socket.Connect(new UnixDomainSocketEndPoint(_path));

            return socket;
        }
    }
}
