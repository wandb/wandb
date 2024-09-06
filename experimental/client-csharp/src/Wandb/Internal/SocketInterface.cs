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

        public async Task Publish(Record record)
        {
            byte[] data = record.ToByteArray();
            await _tcpCommunication.Send(data);
        }

        public async Task<Record> DeliverRun(Run run)
        {
            var record = new Record
            {
                Run = new RunRecord
                {

                }
            };
            return await Deliver(record);
        }


        public async Task<Record> Deliver(Record record)
        {
            byte[] data = record.ToByteArray();
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
