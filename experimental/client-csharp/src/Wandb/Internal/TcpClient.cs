using System.Collections.Concurrent;
using System.Net.Sockets;
using Google.Protobuf;

namespace Wandb.Internal
{
    using WandbInternal;

    /// <summary>
    /// Provides functionality to communicate with the Wandb server over TCP.
    /// </summary>
    public class WandbTcpClient : IDisposable
    {
        private readonly TcpClient _tcpClient;
        private NetworkStream? _networkStream;
        private readonly CancellationTokenSource _cancellationTokenSource;
        private Task? _receiveTask;
        private readonly ConcurrentDictionary<string, TaskCompletionSource<ServerResponse>> _pendingRequests;

        /// <summary>
        /// Initializes a new instance of the <see cref="WandbTcpClient"/> class.
        /// </summary>
        public WandbTcpClient()
        {
            _tcpClient = new TcpClient();
            _cancellationTokenSource = new CancellationTokenSource();
            _pendingRequests = new ConcurrentDictionary<string, TaskCompletionSource<ServerResponse>>();
        }

        /// <summary>
        /// Connects to the specified host and port.
        /// </summary>
        /// <param name="host">The hostname or IP address to connect to.</param>
        /// <param name="port">The port number to connect to.</param>
        /// <exception cref="SocketException">Thrown when a socket error occurs during connection.</exception>
        public void Connect(string host, int port)
        {
            _tcpClient.Connect(host, port);
            _networkStream = _tcpClient.GetStream();
            _receiveTask = Task.Run(() => ReceiveLoopAsync(_cancellationTokenSource.Token));
        }

        /// <summary>
        /// Sends a <see cref="ServerRequest"/> message asynchronously and optionally waits for a response.
        /// </summary>
        /// <param name="message">The message to send.</param>
        /// <param name="timeoutMilliseconds">
        /// The timeout in milliseconds to wait for a response. If zero or less, does not wait for a response.
        /// </param>
        /// <returns>
        /// A task representing the asynchronous operation. The task result contains the <see cref="ServerResponse"/>
        /// if a response is received within the timeout period; otherwise, <c>null</c>.
        /// </returns>
        /// <exception cref="ArgumentNullException">Thrown when the <paramref name="message"/> is <c>null</c>.</exception>
        /// <exception cref="InvalidOperationException">Thrown when the client is not connected.</exception>
        /// <exception cref="TimeoutException">Thrown when the response is not received within the timeout period.</exception>
        public async Task<ServerResponse?> SendAsync(ServerRequest message, int timeoutMilliseconds = 0)
        {
            ArgumentNullException.ThrowIfNull(message);

            // TODO: This must exist in the message, but need to gracefully handle it if it doesn't
            // + check if it's empty, but we're asked to wait for a response
            string messageId;
            if (message.RecordCommunicate != null)
            {
                messageId = message.RecordCommunicate.Control.MailboxSlot;
            }
            else
            {
                messageId = string.Empty;
            }

            var data = message.ToByteArray();
            var packet = Pack(data);

            var tcs = new TaskCompletionSource<ServerResponse>();
            if (timeoutMilliseconds > 0)
            {
                _pendingRequests[messageId] = tcs;
            }

            if (_networkStream == null)
            {
                throw new InvalidOperationException("Not connected.");
            }
            await _networkStream.WriteAsync(packet).ConfigureAwait(false);

            // Don't wait for a response if timeout is <= 0
            if (timeoutMilliseconds <= 0)
            {
                return null;
            }

            // Wait for a response
            CancellationTokenSource? cts = null;
            cts = new CancellationTokenSource(timeoutMilliseconds);
            cts.Token.Register(() => tcs.TrySetCanceled(), useSynchronizationContext: false);

            try
            {
                return await tcs.Task.ConfigureAwait(false);
            }
            catch (TaskCanceledException)
            {
                _pendingRequests.TryRemove(messageId, out _);
                throw new TimeoutException("The request timed out.");
            }
            finally
            {
                cts?.Dispose();
            }
        }

        /// <summary>
        /// Continuously reads messages from the network stream until cancellation is requested.
        /// </summary>
        /// <param name="cancellationToken">A token to monitor for cancellation requests.</param>
        /// <returns>A task that represents the asynchronous receive loop operation.</returns>
        private async Task ReceiveLoopAsync(CancellationToken cancellationToken)
        {
            try
            {
                while (!cancellationToken.IsCancellationRequested)
                {
                    var message = await ReadMessageAsync(cancellationToken).ConfigureAwait(false);
                    if (message != null)
                    {
                        ProcessReceivedMessage(message);
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Receive loop exception: {ex.Message}");
            }
        }

        /// <summary>
        /// Reads a single <see cref="ServerResponse"/> message from the network stream.
        /// </summary>
        /// <param name="cancellationToken">A token to monitor for cancellation requests.</param>
        /// <returns>
        /// A task representing the asynchronous read operation. The task result contains the <see cref="ServerResponse"/>
        /// read from the stream, or <c>null</c> if the connection is closed.
        /// </returns>
        /// <exception cref="InvalidOperationException">Thrown when the client is not connected.</exception>
        /// <exception cref="InvalidDataException">Thrown when the message format is invalid.</exception>
        private async Task<ServerResponse?> ReadMessageAsync(CancellationToken cancellationToken)
        {
            byte[] header = new byte[5];
            int bytesRead = 0;
            while (bytesRead < 5)
            {
                if (_networkStream == null)
                {
                    throw new InvalidOperationException("Not connected.");
                }
                int read = await _networkStream.ReadAsync(header.AsMemory(bytesRead, 5 - bytesRead), cancellationToken).ConfigureAwait(false);
                if (read == 0)
                {
                    // Connection closed
                    return null;
                }
                bytesRead += read;
            }

            if (header[0] != (byte)'W')
            {
                throw new InvalidDataException("Invalid message format.");
            }

            uint length = BitConverter.ToUInt32(header, 1);

            byte[] data = new byte[length];
            bytesRead = 0;
            while (bytesRead < length)
            {
                if (_networkStream == null)
                {
                    throw new InvalidOperationException("Not connected.");
                }
                int read = await _networkStream.ReadAsync(data.AsMemory(bytesRead, (int)length - bytesRead), cancellationToken).ConfigureAwait(false);
                if (read == 0)
                {
                    // Connection closed
                    return null;
                }
                bytesRead += read;
            }

            var message = ServerResponse.Parser.ParseFrom(data);
            return message;
        }

        /// <summary>
        /// Processes a received <see cref="ServerResponse"/> message by completing the corresponding request task.
        /// </summary>
        /// <param name="message">The message to process.</param>
        private void ProcessReceivedMessage(ServerResponse message)
        {
            // TODO: This must exist in the message, but need to gracefully handle it if it doesn't
            var messageId = message.ResultCommunicate.Control.MailboxSlot;

            if (_pendingRequests.TryRemove(messageId, out var tcs))
            {
                tcs.SetResult(message);
            }
            else
            {
                // TODO: Handle unsolicited messages, which should not happen
                Console.WriteLine("Received unsolicited message.");
            }
        }

        /// <summary>
        /// Packs raw data into the protocol format by adding a header.
        /// </summary>
        /// <param name="data">The data to pack.</param>
        /// <returns>The packed data with the protocol header.</returns>
        private static byte[] Pack(byte[] data)
        {
            // Packet format: header + data
            byte[] packet = new byte[1 + 4 + data.Length];
            // Header format: "W" (1 byte) + data length (4 bytes)
            packet[0] = (byte)'W';
            byte[] lengthBytes = BitConverter.GetBytes((uint)data.Length);
            Array.Copy(lengthBytes, 0, packet, 1, 4);
            Array.Copy(data, 0, packet, 5, data.Length);
            return packet;
        }

        /// <summary>
        /// Releases all resources used by the <see cref="WandbTcpClient"/>.
        /// </summary>
        public void Dispose()
        {
            _cancellationTokenSource.Cancel();
            _cancellationTokenSource.Dispose();
            _receiveTask?.Wait();
            _networkStream?.Close();
            _tcpClient.Close();
        }
    }
}
