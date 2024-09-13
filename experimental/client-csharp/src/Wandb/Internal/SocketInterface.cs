using System.Text.Json;
using Google.Protobuf.WellKnownTypes;
using WandbInternal;


namespace Wandb.Internal
{
    public class SocketInterface(WandbTcpClient client, string streamId) : IDisposable
    {
        private readonly WandbTcpClient _client = client;
        private string _streamId = streamId;

        public async Task<Result> DeliverRun(Run run, int timeoutMilliseconds = 0)
        {
            var record = new Record
            {
                Run = new RunRecord
                {
                    Project = run.Settings.Project,
                    RunId = run.Settings.RunId,
                }
            };
            return await Deliver(record, timeoutMilliseconds);
        }

        public async Task<Result> DeliverRunStart(Run run, int timeoutMilliseconds = 0)
        {
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
                }
            };
            return await Deliver(record, timeoutMilliseconds);
        }


        public async Task<Result> DelieverExit(int exitCode = 0, int timeoutMilliseconds = 0)
        {
            var record = new Record
            {
                Exit = new RunExitRecord
                {
                    ExitCode = exitCode
                }
            };
            return await Deliver(record, timeoutMilliseconds);
        }

        public async Task<Result> Deliver(Record record, int timeoutMilliseconds = 0)
        {
            record.Info = new _RecordInfo
            {
                StreamId = _streamId
            };
            record.Control = new Control
            {
                ReqResp = true,
                MailboxSlot = Guid.NewGuid().ToString()
            };

            ServerRequest request = new()
            {
                RecordCommunicate = record
            };
            ServerResponse? response = await _client.SendAsync(request, timeoutMilliseconds) ?? throw new TimeoutException("The request timed out.");
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
                Config = config
            };
            await Publish(record);
        }

        public async Task Publish(Record record)
        {
            record.Info = new _RecordInfo
            {
                StreamId = _streamId
            };
            ServerRequest request = new ServerRequest
            {
                RecordPublish = record
            };
            await _client.SendAsync(request);
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
            await _client.SendAsync(request);
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
            await _client.SendAsync(request);
        }

        public void Dispose()
        {
            _client.Dispose();
        }
    }
}
