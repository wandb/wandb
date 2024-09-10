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

        public async Task<Result> DeliverRun(Run run)
        {
            RandomStringGenerator generator = new();

            var record = new Record
            {
                Run = new RunRecord
                {
                    RunId = run.Settings.GetRunId()
                },
                Info = new _RecordInfo
                {
                    StreamId = run.Settings.GetRunId()
                },
                Control = new Control
                {
                    ReqResp = true,
                    MailboxSlot = generator.GenerateRandomString(16)
                }
            };
            return await Deliver(record);
        }

        public async Task<Result> DeliverRunStart()
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

        public async Task<Result> Deliver(Record record)
        {
            ServerRequest request = new()
            {
                RecordPublish = record

            };
            Console.WriteLine("Delivering record: {0}", request);
            ServerResponse response = await SendAndRecv(request);
            return response.ResultCommunicate;
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
            ServerRequest request = new()
            {
                InformInit = new ServerInformInitRequest
                {
                    Settings = settings.ToProto(),
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
            ServerRequest request = new()
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

        // TODO: Receive should be running in a separate thread delivering
        // messages to the corresponding mailbox slots.
        // This method should wait on a mailbox slot and return the message
        // since there is no guarantee on the message reception order.
        public async Task<ServerResponse> SendAndRecv(ServerRequest request)
        {
            byte[] data = request.ToByteArray();
            Console.WriteLine("Sending data: {0}", data);
            await _tcpCommunication.Send(data);
            Console.WriteLine("Sent data: {0}", data);

            byte[] receivedData = await _tcpCommunication.Receive();
            Console.WriteLine("Received data: {0}", receivedData);
            return ServerResponse.Parser.ParseFrom(receivedData);
        }

        public void Dispose()
        {
            _tcpCommunication.Dispose();
        }
    }
}
