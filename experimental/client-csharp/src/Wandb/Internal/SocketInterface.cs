using System.Text.Json;
using Google.Protobuf.WellKnownTypes;
using WandbInternal;


namespace Wandb.Internal
{
    public class SocketInterface : IDisposable
    {
        private readonly WandbTcpClient _client;
        private readonly string _streamId;

        public SocketInterface(int port, string streamId)
        {
            _client = new WandbTcpClient();
            _client.Connect("localhost", port);
            _streamId = streamId ?? throw new ArgumentNullException(nameof(streamId));
        }

        public async Task<Result> DeliverRun(Run run, int timeoutMilliseconds = 0)
        {
            ArgumentNullException.ThrowIfNull(run);

            var record = new Record
            {
                Run = new RunRecord
                {
                    Project = run.Settings.Project,
                    RunId = run.Settings.RunId,
                }
            };
            return await Deliver(record, timeoutMilliseconds).ConfigureAwait(false);
        }

        public async Task<Result> DeliverRunStart(Run run, int timeoutMilliseconds = 0)
        {
            ArgumentNullException.ThrowIfNull(run);

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
            return await Deliver(record, timeoutMilliseconds).ConfigureAwait(false);
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
            return await Deliver(record, timeoutMilliseconds).ConfigureAwait(false);
        }

        public async Task<Result> Deliver(Record record, int timeoutMilliseconds = 0)
        {
            ArgumentNullException.ThrowIfNull(record);

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
            ServerResponse? response = await _client.SendAsync(request, timeoutMilliseconds).ConfigureAwait(false) ?? throw new TimeoutException("The request timed out.");
            return response.ResultCommunicate;
        }

        public async Task PublishPartialHistory(Dictionary<string, object> data)
        {
            ArgumentNullException.ThrowIfNull(data);

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
            await Publish(record).ConfigureAwait(false);
        }

        public async Task PublishMetricDefinition(
            string name,
            string stepMetric,
            string? summary,
            bool? hidden
        )
        {
            var metricDefinition = new MetricRecord
            {
                Name = name,
                StepMetric = stepMetric,
                Options = new MetricOptions { },
                Summary = new MetricSummary { }
            };
            if (hidden == true)
            {
                metricDefinition.Options.Hidden = true;
            }
            // Split the summary string into individual values
            if (summary != null)
            {

                string[] summaries = summary.Split(',');

                foreach (string s in summaries)
                {
                    // Trim any whitespace from each value
                    switch (s.Trim())
                    {
                        case "min":
                            metricDefinition.Summary.Min = true;
                            break;
                        case "max":
                            metricDefinition.Summary.Max = true;
                            break;
                        case "mean":
                            metricDefinition.Summary.Mean = true;
                            break;
                        case "last":
                            metricDefinition.Summary.Last = true;
                            break;
                        case "none":
                            metricDefinition.Summary.None = true;
                            break;
                    }
                }
            }
            var record = new Record
            {
                Metric = metricDefinition
            };
            await Publish(record).ConfigureAwait(false);
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
            await Publish(record).ConfigureAwait(false);
        }

        public async Task Publish(Record record)
        {
            ArgumentNullException.ThrowIfNull(record);

            record.Info = new _RecordInfo
            {
                StreamId = _streamId
            };
            ServerRequest request = new()
            {
                RecordPublish = record
            };
            await _client.SendAsync(request).ConfigureAwait(false);
        }

        public async Task InformInit(Settings settings)
        {
            ArgumentNullException.ThrowIfNull(settings);

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
            await _client.SendAsync(request).ConfigureAwait(false);
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
            await _client.SendAsync(request).ConfigureAwait(false);
        }

        public void Dispose()
        {
            _client.Dispose();
        }
    }
}
