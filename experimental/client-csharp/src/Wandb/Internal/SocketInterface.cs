using System.Text.Json;
using Google.Protobuf.WellKnownTypes;
using WandbInternal;


namespace Wandb.Internal
{
    /// <summary>
    /// Provides an interface for communication over a socket connection with wandb-core.
    /// </summary>
    public class SocketInterface : IDisposable
    {
        private readonly WandbTcpClient _client;
        private readonly string _streamId;

        /// <summary>
        /// Initializes a new instance of the <see cref="SocketInterface"/> class.
        /// </summary>
        /// <param name="port">The port to connect to.</param>
        /// <param name="streamId">The stream identifier.</param>
        /// <exception cref="ArgumentNullException">Thrown if <paramref name="streamId"/> is <c>null</c>.</exception>
        public SocketInterface(int port, string streamId)
        {
            _client = new WandbTcpClient();
            _client.Connect("localhost", port);
            _streamId = streamId ?? throw new ArgumentNullException(nameof(streamId));
        }

        /// <summary>
        /// Delivers a Run record to wandb-core.
        /// </summary>
        /// <param name="run">The Run record to deliver.</param>
        /// <param name="timeoutMilliseconds">
        /// The timeout in milliseconds to wait for a response. Defaults to 0 (no timeout).
        /// </param>
        /// <returns>
        /// A task representing the asynchronous operation. The task result contains the <see cref="Result"/>.
        /// </returns>
        /// <exception cref="ArgumentNullException">Thrown if <paramref name="run"/> is <c>null</c>.</exception>
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

        /// <summary>
        /// Delivers a run start request to the server.
        /// </summary>
        /// <param name="run">The run information to start.</param>
        /// <param name="timeoutMilliseconds">
        /// The timeout in milliseconds to wait for a response. Defaults to 0 (no timeout).
        /// </param>
        /// <returns>
        /// A task representing the asynchronous operation. The task result contains the <see cref="Result"/>.
        /// </returns>
        /// <exception cref="ArgumentNullException">Thrown if <paramref name="run"/> is <c>null</c>.</exception>
        public async Task<Result> DeliverRunStart(
            Run run,
            SummaryRecord summary,
            int timeoutMilliseconds = 0
        )
        {
            ArgumentNullException.ThrowIfNull(run);

            Console.WriteLine(summary);

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
                            Resumed = run.Settings.Resumed,
                            StartTime = Timestamp.FromDateTime(run.Settings.StartDatetime.ToUniversalTime()),
                            StartingStep = run.StartingStep,
                            Summary = summary
                        }
                    },
                }
            };
            return await Deliver(record, timeoutMilliseconds).ConfigureAwait(false);
        }

        public async Task<Result> DeliverGetSummary(int timeoutMilliseconds = 0)
        {
            var record = new Record
            {
                Request = new Request
                {
                    GetSummary = new GetSummaryRequest { }
                }
            };
            return await Deliver(record, timeoutMilliseconds).ConfigureAwait(false);
        }


        /// <summary>
        /// Delivers a run exit record to the server.
        /// </summary>
        /// <param name="exitCode">The exit code of the run. Defaults to 0.</param>
        /// <param name="timeoutMilliseconds">
        /// The timeout in milliseconds to wait for a response. Defaults to 0 (no timeout).
        /// </param>
        /// <returns>
        /// A task representing the asynchronous operation. The task result contains the <see cref="Result"/>.
        /// </returns>
        public async Task<Result> DeliverExit(int exitCode = 0, int timeoutMilliseconds = 0)
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

        /// <summary>
        /// Delivers a record to wandb-core and waits for a response.
        /// </summary>
        /// <param name="record">The record to deliver.</param>
        /// <param name="timeoutMilliseconds">
        /// The timeout in milliseconds to wait for a response. Defaults to 0 (no timeout).
        /// </param>
        /// <returns>
        /// A task representing the asynchronous operation. The task result contains the <see cref="Result"/>.
        /// </returns>
        /// <exception cref="ArgumentNullException">Thrown if <paramref name="record"/> is <c>null</c>.</exception>
        /// <exception cref="TimeoutException">Thrown if the request times out.</exception>
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

        /// <summary>
        /// Publishes partial history data to wandb-core.
        /// </summary>
        /// <param name="data">A dictionary containing the history data to publish.</param>
        /// <returns>A task representing the asynchronous operation.</returns>
        /// <exception cref="ArgumentNullException">Thrown if <paramref name="data"/> is <c>null</c>.</exception>
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

        /// <summary>
        /// Publishes a metric definition to wandb-core.
        /// </summary>
        /// <param name="name">The name of the metric.</param>
        /// <param name="stepMetric">The name of the step metric.</param>
        /// <param name="summary">The summary type for the metric.</param>
        /// <param name="hidden">Indicates whether the metric is hidden.</param>
        /// <returns>A task representing the asynchronous operation.</returns>
        public async Task PublishMetricDefinition(
            string name,
            string? stepMetric,
            SummaryType? summary,
            bool? hidden
        )
        {
            var metricDefinition = new MetricRecord
            {
                Name = name,
                Options = new MetricOptions { },
                Summary = new MetricSummary { }
            };
            if (stepMetric != null)
            {
                metricDefinition.StepMetric = stepMetric;
            }
            if (hidden == true)
            {
                metricDefinition.Options.Hidden = true;
            }
            if (summary.HasValue)
            {
                if (summary == SummaryType.None)
                {
                    metricDefinition.Summary.None = true;
                }
                else
                {
                    metricDefinition.Summary.None = false;
                    metricDefinition.Summary.Min = summary.Value.HasFlag(SummaryType.Min);
                    metricDefinition.Summary.Max = summary.Value.HasFlag(SummaryType.Max);
                    metricDefinition.Summary.Mean = summary.Value.HasFlag(SummaryType.Mean);
                    metricDefinition.Summary.Last = summary.Value.HasFlag(SummaryType.Last);
                }
            }
            var record = new Record
            {
                Metric = metricDefinition
            };
            await Publish(record).ConfigureAwait(false);
        }

        /// <summary>
        /// Publishes a configuration update to wandb-core.
        /// </summary>
        /// <param name="update">A dictionary containing the configuration update.</param>
        /// <returns>A task representing the asynchronous operation.</returns>
        public async Task PublishConfig(Dictionary<string, object> update)
        {
            if (update == null || update.Count == 0)
            {
                return;
            }

            var config = new ConfigRecord();
            foreach (var (key, value) in update)
            {
                config.Update.Add(new ConfigItem
                {
                    Key = key,
                    ValueJson = JsonSerializer.Serialize(value)
                });
            }

            var record = new Record
            {
                Config = config
            };
            await Publish(record).ConfigureAwait(false);
        }

        /// <summary>
        /// Publishes a record to the server without waiting for a response.
        /// </summary>
        /// <param name="record">The record to publish.</param>
        /// <returns>A task representing the asynchronous operation.</returns>
        /// <exception cref="ArgumentNullException">Thrown if <paramref name="record"/> is <c>null</c>.</exception>
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
