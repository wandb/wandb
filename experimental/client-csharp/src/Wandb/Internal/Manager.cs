using System.Diagnostics;

namespace Wandb.Internal
{
    /// <summary>
    /// Manages the wandb-core process, which is responsible for handling communication with the Wandb server.
    /// </summary>
    public class Manager : IDisposable
    {
        private Process? _coreProcess;
        private string _portFilePath;
        private static readonly char[] separator = ['\r', '\n'];
        private const int PollDelayMs = 20;
        private const string EndOfFileMarker = "EOF";
        private const string UnixKey = "unix";
        private const string TcpKey = "sock";

        public Manager()
        {
            _portFilePath = Path.Combine(Path.GetTempPath(), $"port-{Environment.ProcessId}.txt");
        }

        /// <summary>
        /// Launches the wandb-core process and returns how to connect to it.
        /// </summary>
        /// <param name="timeout">The maximum amount of time to wait for the port number.</param>
        /// <returns>How to connect to the service.</returns>
        /// <exception cref="TimeoutException">
        /// Thrown if the port is not provided within the specified timeout.
        /// </exception>
        /// <exception cref="InvalidOperationException">
        /// Thrown if the port number cannot be parsed.
        /// </exception>
        public async Task<IServiceConnectionProtocol> LaunchCore(TimeSpan timeout)
        {
            await File.Create(_portFilePath).DisposeAsync().ConfigureAwait(false); // Create empty file

            _coreProcess = new Process
            {
                StartInfo = new ProcessStartInfo
                {
                    FileName = "wandb-core",
                    Arguments = $"--port-filename {_portFilePath} --pid {Environment.ProcessId} --no-observability true",
                    UseShellExecute = false,
                    RedirectStandardOutput = false,
                    RedirectStandardError = false
                }
            };

            _coreProcess.Start();

            return await WaitForPort(timeout).ConfigureAwait(false);
        }

        /// <summary>
        /// Waits for wandb-core to start and returns its connection information.
        /// </summary>
        /// <param name="timeout">The maximum amount of time to wait.</param>
        /// <returns>
        /// A connection protocol object that can be used to open a socket
        /// to wandb-core.
        /// </returns>
        /// <exception cref="TimeoutException">
        /// Thrown if the port number is not written within the specified timeout.
        /// </exception>
        /// <exception cref="InvalidOperationException">
        /// Thrown if the file cannot be parsed.
        /// </exception>
        private async Task<IServiceConnectionProtocol> WaitForPort(TimeSpan timeout)
        {
            using var cts = new CancellationTokenSource(timeout);
            var token = cts.Token;

            while (!token.IsCancellationRequested)
            {
                await Task.Delay(PollDelayMs, token).ConfigureAwait(false);

                if (!File.Exists(_portFilePath))
                    continue;

                var proto = await TryReadProtocolAsync().ConfigureAwait(false);
                if (proto != null)
                    return proto;
            }

            throw new TimeoutException($"Timed out waiting {timeout} for wandb-core to write port number");
        }

        private async Task<IServiceConnectionProtocol?> TryReadProtocolAsync()
        {
            var text = await File.ReadAllTextAsync(_portFilePath).ConfigureAwait(false);
            var lines = text.Split(separator, StringSplitOptions.RemoveEmptyEntries);

            if (lines.Length == 0 || lines[^1] != EndOfFileMarker)
                return null;

            foreach (var line in lines[..^1])
            {
                var parts = line.Split('=', 2);
                if (parts.Length != 2)
                    continue;

                if (parts[0] == UnixKey)
                    return new UnixSocketProtocol(parts[1]);

                if (parts[0] == TcpKey)
                {
                    if (!int.TryParse(parts[1], out var port))
                        throw new InvalidOperationException($"Invalid port: '{parts[1]}'");
                    return new TcpConnectionProtocol(port);
                }
            }

            return null;
        }

        /// <summary>
        /// Releases all resources used by the <see cref="Manager"/> class.
        /// </summary>
        public void Dispose()
        {
            _coreProcess?.Kill();
            _coreProcess?.Dispose();
            File.Delete(_portFilePath);
        }
    }
}
