using System.Text.Json;
using Google.Protobuf;
using Google.Protobuf.WellKnownTypes;
using WandbInternal;


namespace Wandb.Internal
{
    public class SocketInterface : IDisposable
    {
        private readonly TcpCommunication _tcpCommunication;
        private string _streamId;

        public SocketInterface(TcpCommunication tcpCommunication, string streamId)
        {
            _tcpCommunication = tcpCommunication;
            _streamId = streamId;
        }

        public async Task<Result> DeliverRun(Run run)
        {
            RandomStringGenerator generator = new();

            var record = new Record
            {
                Run = new RunRecord
                {
                    Project = run.Settings.Project,
                    RunId = run.Settings.RunId,
                },
                Info = new _RecordInfo
                {
                    StreamId = _streamId
                },
                Control = new Control
                {
                    ReqResp = true,
                    MailboxSlot = generator.GenerateRandomString(16)
                }
            };
            return await Deliver(record);
        }

        public async Task<Result> DeliverRunStart(Run run)
        {
            RandomStringGenerator generator = new();

            var record = new Record
            {
                Request = new Request
                {
                    RunStart = new RunStartRequest
                    {
                        Run = new RunRecord
                        {
                            Project = run.Settings.Project,
                            Entity = run.Settings.Entity,
                            DisplayName = run.Settings.DisplayName,
                            RunId = run.Settings.RunId,
                            StartTime = Timestamp.FromDateTime(run.Settings.StartDatetime.ToUniversalTime()),
                        },
                    },
                },
                Info = new _RecordInfo
                {
                    StreamId = _streamId
                },
                Control = new Control
                {
                    ReqResp = true,
                    MailboxSlot = generator.GenerateRandomString(16)
                }
            };
            return await Deliver(record);
        }


        public async Task<Result> DelieverExit(int exitCode = 0)
        {
            RandomStringGenerator generator = new();

            var record = new Record
            {
                Exit = new RunExitRecord
                {
                    ExitCode = exitCode
                },
                Info = new _RecordInfo
                {
                    StreamId = _streamId
                },
                Control = new Control
                {
                    ReqResp = true,
                    MailboxSlot = generator.GenerateRandomString(16)
                }

            };
            return await Deliver(record);
        }

        public async Task<Result> Deliver(Record record)
        {
            ServerRequest request = new()
            {
                RecordPublish = record

            };
            ServerResponse response = await SendAndRecv(request);
            return response.ResultCommunicate;
        }

        public async Task PublishPartialHistory(Dictionary<string, object> data)
        {
            var partialHistory = new PartialHistoryRequest();
            foreach (var kvp in data)
            {
                partialHistory.Item.Add(new HistoryItem
                {
                    Key = kvp.Key,
                    ValueJson = JsonSerializer.Serialize(kvp.Value)
                });
            }

            var record = new Record
            {
                Request = new Request
                {
                    PartialHistory = partialHistory
                },
                Info = new _RecordInfo
                {
                    StreamId = _streamId
                }
            };
            await Publish(record);
        }

        public async Task PublishConfig(string key, object value)
        {
            var config = new ConfigRecord();
            config.Update.Add(new ConfigItem
            {
                Key = key,
                ValueJson = JsonSerializer.Serialize(value)
            });
            var record = new Record
            {
                Config = config,
                Info = new _RecordInfo
                {
                    StreamId = _streamId
                }
            };
            await Publish(record);
        }

        public async Task Publish(Record record)
        {
            ServerRequest request = new ServerRequest
            {
                RecordPublish = record
            };
            await Send(request);
        }


        public async Task InformInit(Settings settings)
        {
            ServerRequest request = new()
            {
                InformInit = new ServerInformInitRequest
                {
                    Settings = settings.ToProto(),
                    Info = new _RecordInfo
                    {
                        StreamId = _streamId
                    }
                }
            };
            await Send(request);
        }

        public async Task InformFinish()
        {
            ServerRequest request = new()
            {
                InformFinish = new ServerInformFinishRequest
                {
                    Info = new _RecordInfo
                    {
                        StreamId = _streamId
                    }
                }
            };
            await Send(request);
        }

        public async Task Send(ServerRequest request)
        {
            byte[] data = request.ToByteArray();
            await _tcpCommunication.Send(data);
        }

        // TODO: Receive should be running in a separate thread delivering
        // messages to the corresponding mailbox slots.
        // This method should wait on a mailbox slot and return the message
        // since there is no guarantee on the message reception order.
        public async Task<ServerResponse> SendAndRecv(ServerRequest request)
        {
            byte[] data = request.ToByteArray();
            await _tcpCommunication.Send(data);

            byte[] receivedData = await _tcpCommunication.Receive();
            return ServerResponse.Parser.ParseFrom(receivedData);
        }

        public void Dispose()
        {
            _tcpCommunication.Dispose();
        }
    }
}
