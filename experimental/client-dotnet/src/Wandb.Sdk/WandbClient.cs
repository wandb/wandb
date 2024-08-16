using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text.RegularExpressions;
using System.Threading;
using System.Collections.Generic;
using System.Buffers.Binary;
using Newtonsoft.Json;


using Google.Protobuf; // Ensure you have the Protobuf C# library installed
using WandbInternal; // Namespace for protobuf

namespace Wandb.Sdk
{
    public class WandbClient
    {
        private static readonly List<TcpClient> activeClients = new List<TcpClient>();
        private TcpClient _client;
        private NetworkStream _stream;
        private Process _wandbProcess;
        private int _port = 5000; // Default port number
        private const string PortFileName = "port_file.txt";
        private const byte MagicByte = (byte)'W';
        private string _runID = "unknown";

        public void Init()
        {
            DeletePortFileIfExists();

            _runID = RandomIdGenerator.GenerateId(8);
            Console.WriteLine($"Generated ID: {_runID}");

            // Start the wandb-core process
            _wandbProcess = new Process
            {
                StartInfo = new ProcessStartInfo
                {
                    FileName = "wandb-core", // Ensure wandb-core is in your PATH or provide the full path
                    Arguments = "-debug",
                    UseShellExecute = false,
                    CreateNoWindow = true
                }
            };
            _wandbProcess.Start();

            // Watch for the port file and update the port number
            WatchForPortFile();

            // Open a TCP socket to wandb-core
            _client = new TcpClient("127.0.0.1", _port); // Replace with the correct IP and port
            _stream = _client.GetStream();
            activeClients.Add(_client);

            // Example: Send an inform_init request using ServerRequest
            var settings = InitializeSettings(_runID);
            var initRequest = new ServerRequest
            {
                InformInit = new ServerInformInitRequest
                {
                    Settings = settings,
                    Info = new _RecordInfo { StreamId = _runID }
                }
            };
            SendMessage(initRequest);

            var runRecord = new RunRecord {
                RunId = _runID
            };

            var runRequest = new ServerRequest
            {
                RecordPublish = new Record {
                    Info = new _RecordInfo { StreamId = _runID },
                    Run = runRecord,
                    Control = new Control { MailboxSlot = "junkmail" }
                }
            };
            SendMessage(runRequest);
            Console.WriteLine($"sent");
            var response = ReceiveMessage();
            Console.WriteLine($"Received Init Response: {response}");

            var startRequest = new ServerRequest
            {
                InformStart = new ServerInformStartRequest
                {
                    Settings = settings,
                    Info = new _RecordInfo { StreamId = _runID }
                }
            };
            SendMessage(startRequest);

            var runStartRequest = new ServerRequest
            {
                RecordPublish = new Record {
                    Info = new _RecordInfo { StreamId = _runID },
                    Request = new Request {
                        RunStart = new RunStartRequest {
                            Run = runRecord
                        }
                    },
                    Control = new Control { MailboxSlot = "junkstart2" }
                }
            };
            SendMessage(runStartRequest);
            Console.WriteLine($"sent");
            var responseStart = ReceiveMessage();
            Console.WriteLine($"Received RunStart Response: {responseStart}");

            // Console.WriteLine($"Received Init Response: {response.Message}");
        }

        private Settings InitializeSettings(string runId)
        {
            var now = DateTime.Now;
            string timestamp = now.ToString("yyyyMMdd_HHmmss");
            string wandbDir = "wandb";
            string runMode = "run";
            string syncDir = Path.Combine(wandbDir, $"{runMode}-{timestamp}-{runId}");
            string logDir = Path.Combine(syncDir, "logs");
            string filesDir = Path.Combine(syncDir, "files");

            // Create directories
            Directory.CreateDirectory(syncDir);
            Directory.CreateDirectory(logDir);
            Directory.CreateDirectory(filesDir);

            // Set up the Settings object
            var settings = new Settings
            {
                BaseUrl = "https://api.wandb.ai",
                // Project = "test-csharp",
                RunId = runId,
                SyncDir = syncDir,
                SyncFile = Path.Combine(syncDir, $"run-{runId}.wandb"),
                LogInternal = Path.Combine(logDir, "debug-internal.log"),
                FilesDir = filesDir
            };

            return settings;
        }

        private void DeletePortFileIfExists()
        {
            if (File.Exists(PortFileName))
            {
                try
                {
                    File.Delete(PortFileName);
                    Console.WriteLine("Deleted existing port_file.txt.");
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"Error deleting port_file.txt: {ex.Message}");
                    throw; // Re-throw the exception to handle it in the calling code
                }
            }
        }

        private void WatchForPortFile()
        {
            // Polling loop to wait for the port_file.txt to be fully written
            while (true)
            {
                if (File.Exists(PortFileName))
                {
                    var lines = File.ReadAllLines(PortFileName);

                    // Check if the last line is "EOF"
                    if (lines.Length > 0 && lines[^1] == "EOF")
                    {
                        // Search for the line that contains "sock=NUMBER"
                        foreach (var line in lines)
                        {
                            var match = Regex.Match(line, @"sock=(\d+)");
                            if (match.Success)
                            {
                                _port = int.Parse(match.Groups[1].Value);
                                Console.WriteLine($"Detected port: {_port}");
                                return;
                            }
                        }
                    }
                }

                // Sleep for a short time before polling again
                Task.Delay(100).Wait(); // Sleep for 100ms
            }
        }

        public void Log(Dictionary<string, object> logData)
        {
            if (_client == null || !_client.Connected) throw new InvalidOperationException("Socket is not connected");

            var historyItems = logData.Select(kv => new HistoryItem
            {
                Key = kv.Key,
                ValueJson = JsonConvert.SerializeObject(kv.Value)
            }).ToList();

            var logMsg = new ServerRequest
            {
                RecordPublish = new Record {
                    Info = new _RecordInfo { StreamId = _runID },
                    Request = new Request {
                        PartialHistory = new PartialHistoryRequest {
                            Item = { historyItems },
                            Action = new HistoryAction { Flush = true }
                        }
                    },
                    // no mailbox
                    // Control = new Control { MailboxSlot = "histmail" }
                }
            };
            SendMessage(logMsg);

            // var response = ReceiveMessage();

            // Console.WriteLine($"Received Log Response: {response.Message}");
            // Console.WriteLine($"Received Log Response: {response}");
            Console.WriteLine($"sent history");
        }

        public void Finish()
        {
            if (_client == null || !_client.Connected) return;

            var exitMsg = new ServerRequest
            {
                RecordPublish = new Record {
                    Info = new _RecordInfo { StreamId = _runID },
                    Exit = new RunExitRecord { },
                    Control = new Control { MailboxSlot = "exitmail" }
                }
            };
            Console.WriteLine($"send exit");
            SendMessage(exitMsg);
            Console.WriteLine($"sent exit");
            var response = ReceiveMessage();
            Console.WriteLine($"got response {response}");

            var finishRequest = new ServerRequest
            {
                InformFinish = new ServerInformFinishRequest
                {
                    Info = new _RecordInfo { StreamId = _runID }
                }
            };
            Console.WriteLine($"send fin");
            SendMessage(finishRequest);


            // Console.WriteLine($"Received Finish Response: {response.Message}");

            _stream.Close();
            _client.Close();
            activeClients.Remove(_client);

            _wandbProcess?.Kill();
        }

        /*
        private void OldSendMessage<T>(T message) where T : IMessage
        {
            message.WriteTo(_stream);
            Console.WriteLine($"debug");
        }

        private void SendMessage<T>(T message) where T : IMessage
        {
            // Serialize the message to a byte array
            byte[] messageBytes = message.ToByteArray();

            // Create the header
            var header = new byte[5]; // 1 byte for Magic + 4 bytes for DataLength
            header[0] = MagicByte;
            BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(1), (uint)messageBytes.Length);

            // Send the header
            _stream.Write(header, 0, header.Length);

            // Send the serialized message
            _stream.Write(messageBytes, 0, messageBytes.Length);
        }

        private T OldReceiveMessage<T>() where T : IMessage<T>, new()
        {
            var parser = new MessageParser<T>(() => new T());
            return parser.ParseDelimitedFrom(_stream);
        }

        private T ReceiveMessage<T>() where T : IMessage<T>, new()
        {
            // Read the header
            var header = new byte[5];
            _stream.Read(header, 0, header.Length);

            // Verify the magic byte
            if (header[0] != MagicByte)
            {
                throw new InvalidOperationException("Invalid magic byte received.");
            }

            // Extract the data length from the header
            uint dataLength = BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(1));

            // Read the message data
            var messageData = new byte[dataLength];
            _stream.Read(messageData, 0, messageData.Length);

            // Parse the message
            var parser = new MessageParser<T>(() => new T());
            return parser.ParseFrom(messageData);
        }

        private void SendMessage(ServerRequest request)
        {
            // Serialize the ServerRequest message to a byte array
            byte[] messageBytes = request.ToByteArray();

            // Create the header
            var header = new byte[5]; // 1 byte for Magic + 4 bytes for DataLength
            header[0] = MagicByte;
            BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(1), (uint)messageBytes.Length);

            // Send the header
            _stream.Write(header, 0, header.Length);

            // Send the serialized message
            _stream.Write(messageBytes, 0, messageBytes.Length);
        }
        */

        private void SendMessage(ServerRequest request)
        {
            // Serialize the ServerRequest message to a byte array
            byte[] messageBytes = request.ToByteArray();

            // Create the header
            var header = new byte[5]; // 1 byte for Magic + 4 bytes for DataLength
            header[0] = MagicByte;
            BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(1), (uint)messageBytes.Length);

            // Send the header
            _stream.Write(header, 0, header.Length);

            // Send the serialized message
            _stream.Write(messageBytes, 0, messageBytes.Length);
        }

        private ServerResponse ReceiveMessage()
        {
            // Read the header
            var header = new byte[5];
            _stream.Read(header, 0, header.Length);

            // Verify the magic byte
            if (header[0] != MagicByte)
            {
                throw new InvalidOperationException("Invalid magic byte received.");
            }

            // Extract the data length from the header
            uint dataLength = BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(1));

            // Read the message data
            var messageData = new byte[dataLength];
            _stream.Read(messageData, 0, messageData.Length);

            // Parse the ServerResponse message
            var response = ServerResponse.Parser.ParseFrom(messageData);
            return response;
        }

        ~WandbClient()
        {
            // Ensure Finish is called on any active client
            foreach (var client in activeClients)
            {
                try
                {
                    // var finishMessage = new FinishMessage { Message = "Finish" };
                    var finishMessage = new RunExitRecord {};
                    client.GetStream().WriteAsync(finishMessage.ToByteArray(), 0, finishMessage.CalculateSize());
                }
                catch (Exception)
                {
                    // Log or handle errors as needed
                }
                finally
                {
                    client.Close();
                }
            }
        }
    }
}
