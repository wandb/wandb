using Google.Protobuf;
using WandbInternal;


namespace Wandb.Internal
{
    public class SocketInterface : IDisposable
    {
        private readonly TcpCommunication _tcpCommunication;

        public SocketInterface()
        {
            _tcpCommunication = new TcpCommunication();
        }

        public async Task Initialize(int port)
        {
            await _tcpCommunication.Open(port);
        }

        public async Task<Record> DeliverRun(Run run)
        {
            var record = new Record
            {
                Run = new RunRecord
                {
                    RunId = run.Settings.GetRunId()
                }
            };
            return await Deliver(record);
        }

        public async Task<Record> DeliverRunStart()
        {
            var record = new Record
            {
                Request = new Request
                {
                    RunStart = new RunStartRequest()
                }
            };
            return await Deliver(record);
        }

        public async Task<Record> Deliver(Record record)
        {
            ServerRequest request = new ServerRequest
            {
                RecordPublish = record
            };

            return await SendAndRecv(request);
        }

        public async Task PublishPartialHistory()
        {
            var record = new Record
            {
                Request = new Request
                {
                    PartialHistory = new PartialHistoryRequest()
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


        public async Task InformInit(Settings settings, string streamId)
        {
            ServerRequest request = new ServerRequest
            {
                InformInit = new ServerInformInitRequest
                {
                    // TODO: add conversion settings to protobuf
                    Settings = new WandbInternal.Settings
                    {
                        RunId = settings.GetRunId(),
                    },
                    Info = new _RecordInfo
                    {
                        StreamId = streamId
                    }
                }
            };
            await Send(request);
        }

        public async Task InformFinish(string streamId)
        {
            ServerRequest request = new ServerRequest
            {
                InformFinish = new ServerInformFinishRequest
                {
                    Info = new _RecordInfo
                    {
                        StreamId = streamId
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

        public async Task<Record> SendAndRecv(ServerRequest request)
        {

            byte[] data = request.ToByteArray();
            await _tcpCommunication.Send(data);

            byte[] receivedData = await _tcpCommunication.Receive();
            return Record.Parser.ParseFrom(receivedData);


        }

        public void Dispose()
        {
            _tcpCommunication.Dispose();
        }
    }
}
