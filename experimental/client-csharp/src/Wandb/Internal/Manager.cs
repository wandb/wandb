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

        public Manager()
        {
            _portFilePath = Path.Combine(Path.GetTempPath(), $"port-{Environment.ProcessId}.txt");
        }

        /// <summary>
        /// Launches the wandb-core process and waits for it to provide a port number.
        /// </summary>
        /// <param name="timeout">The maximum amount of time to wait for the port number.</param>
        /// <returns>
        /// A task representing the asynchronous operation. The task result contains the port number.
        /// </returns>
        /// <exception cref="TimeoutException">
        /// Thrown if the port is not provided within the specified timeout.
        /// </exception>
        /// <exception cref="InvalidOperationException">
        /// Thrown if the port number cannot be parsed.
        /// </exception>
        public async Task<int> LaunchCore(TimeSpan timeout)
        {
            await File.Create(_portFilePath).DisposeAsync().ConfigureAwait(false); // Create empty file

            _coreProcess = new Process
            {
                StartInfo = new ProcessStartInfo
                {
                    FileName = "wandb-core",
                    Arguments = $"--port-filename {_portFilePath} --pid {Environment.ProcessId}",
                    UseShellExecute = false,
                    RedirectStandardOutput = false,
                    RedirectStandardError = false
                }
            };

            _coreProcess.Start();

            return await WaitForPort(timeout).ConfigureAwait(false);
        }

        /// <summary>
        /// Waits for the wandb-core process to write the port number to the port file.
        /// For more information on wandb-core, see https://wandb.me/wandb-core.
        /// </summary>
        /// <param name="timeout">The maximum amount of time to wait for the port number.</param>
        /// <returns>
        /// A task representing the asynchronous operation. The task result contains the port number.
        /// </returns>
        /// <exception cref="TimeoutException">
        /// Thrown if the port number is not written within the specified timeout.
        /// </exception>
        /// <exception cref="InvalidOperationException">
        /// Thrown if the port number cannot be parsed from the file.
        /// </exception>
        private async Task<int> WaitForPort(TimeSpan timeout)
        {
            var startTime = DateTime.Now;
            var delayTime = TimeSpan.FromMilliseconds(20);

            while (DateTime.Now - startTime < timeout)
            {
                await Task.Delay(delayTime).ConfigureAwait(false);

                if (!File.Exists(_portFilePath))
                    continue;

                var contents = await File.ReadAllTextAsync(_portFilePath).ConfigureAwait(false);
                var lines = contents.Split(separator, StringSplitOptions.RemoveEmptyEntries);

                if (lines.Length > 0 && lines[^1] == "EOF")
                {
                    foreach (var line in lines)
                    {
                        var parts = line.Split('=');
                        if (parts.Length == 2 && parts[0] == "sock")
                        {
                            if (int.TryParse(parts[1], out int port))
                            {
                                return port;
                            }
                            throw new InvalidOperationException("Failed to parse port number");
                        }
                    }
                }
            }

            throw new TimeoutException("Timed out waiting for wandb-core to write port number");
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
