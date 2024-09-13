using System.Collections.Concurrent;
using System.Net.Sockets;
using Google.Protobuf;

namespace Wandb.Internal
{
    using WandbInternal;

    public class WandbTcpClient : IDisposable
    {
        private readonly TcpClient _tcpClient;
        private NetworkStream? _networkStream;
        private readonly CancellationTokenSource _cancellationTokenSource;
        private readonly Task _receiveTask;
        private readonly ConcurrentDictionary<string, TaskCompletionSource<ServerResponse>> _pendingRequests;

        public WandbTcpClient()
        {
            _tcpClient = new TcpClient();
            _cancellationTokenSource = new CancellationTokenSource();
            _pendingRequests = new ConcurrentDictionary<string, TaskCompletionSource<ServerResponse>>();
            _receiveTask = Task.Run(() => ReceiveLoopAsync(_cancellationTokenSource.Token));
        }

        public void Connect(string host, int port)
        {
            _tcpClient.Connect(host, port);
            _networkStream = _tcpClient.GetStream();
        }

        public async Task<ServerResponse?> SendAsync(ServerRequest message, int timeoutMilliseconds = 0)
        {
            // move to SocketInterface
            // var id = Guid.NewGuid().ToString();

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
            await _networkStream.WriteAsync(packet);

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
                return await tcs.Task;
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

        private async Task ReceiveLoopAsync(CancellationToken cancellationToken)
        {
            try
            {
                while (!cancellationToken.IsCancellationRequested)
                {
                    var message = await ReadMessageAsync(cancellationToken);
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
                int read = await _networkStream.ReadAsync(header.AsMemory(bytesRead, 5 - bytesRead), cancellationToken);
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
                int read = await _networkStream.ReadAsync(data, bytesRead, (int)length - bytesRead, cancellationToken);
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

        private static byte[] Pack(byte[] data)
        {
            byte[] packet = new byte[1 + 4 + data.Length];
            packet[0] = (byte)'W';
            byte[] lengthBytes = BitConverter.GetBytes((uint)data.Length);
            Array.Copy(lengthBytes, 0, packet, 1, 4);
            Array.Copy(data, 0, packet, 5, data.Length);
            return packet;
        }

        public void Dispose()
        {
            _cancellationTokenSource.Cancel();
            _receiveTask.Wait();
            if (_networkStream != null)
            {
                _networkStream.Close();
            }
            _tcpClient.Close();
        }
    }
}
