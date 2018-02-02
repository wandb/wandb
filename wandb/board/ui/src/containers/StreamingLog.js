import {withApollo} from 'react-apollo';
import {connect} from 'react-redux';
import Log from '../components/Log';
import {logsChannel, runsChannel} from '../util/pusher';
import {fragments} from '../graphql/runs';

function gidToIdx(gid) {
  //return parseInt(atob(gid).split(':')[2]);
  return parseInt(gid, 10);
}

//This likely belongs in the Run page
function stream(client, params, bucket, callback) {
  logsChannel(bucket.name).bind('history', payload => {
    const data = client.readFragment({
      id: bucket.id,
      fragment: fragments.detailedRun,
      variables: {bucketName: bucket.name},
    });
    //TODO: this has duplicates sometimes
    data.history = Array.from(new Set(data.history.concat(payload)));
    client.writeFragment({
      id: bucket.id,
      fragment: fragments.detailedRun,
      data: data,
    });
  });

  logsChannel(bucket.name).bind('events', payload => {
    const data = client.readFragment({
      id: bucket.id,
      fragment: fragments.detailedRun,
      variables: {bucketName: bucket.name},
    });
    //TODO: this has duplicates sometimes
    data.events = Array.from(new Set(data.events.concat(payload)));
    client.writeFragment({
      id: bucket.id,
      fragment: fragments.detailedRun,
      data: data,
    });
  });

  //TODO: performance
  logsChannel(bucket.name).bind('lines', payload => {
    const data = client.readFragment({
        id: bucket.id,
        fragment: fragments.detailedRun,
        variables: {bucketName: bucket.name},
      }),
      edges = data.logLines.edges;

    let changed = false,
      del = 1,
      idx = edges.findIndex(e => gidToIdx(e.node.id) === payload[0].number);
    payload.forEach(log_line => {
      if (idx < 0) {
        del = 0;
        idx = edges.length;
      }

      edges.splice(idx, del, {
        node: {
          id: log_line.number,
          line: log_line.line,
          level: log_line.level,
          __typename: 'LogLine',
        },
        __typename: 'LogLineEdge',
      });
      if (idx >= 0) {
        changed = true;
        idx = -1;
        del = 0;
      }
    });
    client.writeFragment({
      id: bucket.id,
      fragment: fragments.detailedRun,
      data: data,
    });
    if (changed) callback();
  });

  runsChannel(`${params.entity}@${params.model}`).bind('updated', payload => {
    // Overwrite files data only if payload belongs to particular run
    if (bucket.id === payload.id) {
      //Update files
      const data = client.readFragment({
        id: bucket.id,
        fragment: fragments.detailedRun,
      });

      data.files = payload.files;
      data.fileCount = payload.fileCount;
      client.writeFragment({
        id: bucket.id,
        fragment: fragments.detailedRun,
        data: data,
      });
    }
  });
}

function mapStateToProps(state, ownProps) {
  return {stream};
}

export default withApollo(connect(mapStateToProps)(Log));
