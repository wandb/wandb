import {withApollo} from 'react-apollo';
import {connect} from 'react-redux';
import RunViewer from '../components/RunViewer';
import {fragments} from '../graphql/runs';
import {pusherRunSlug, pusherProjectSlug} from '../util/runhelpers';

let logsChannel, runsChannel, runChannel;
try {
  const p = require('Cloud/util/pusher');
  logsChannel = p.logsChannel;
  runsChannel = p.runsChannel;
  runChannel = p.runChannel;
} catch (e) {
  const p = require('../util/pusher');
  logsChannel = p.dummyChannel;
  runsChannel = p.dummyChannel;
  runChannel = p.dummyChannel;
}

function gidToIdx(gid) {
  //return parseInt(atob(gid).split(':')[2]);
  return parseInt(gid, 10);
}

//This likely belongs in the Run page
function stream(client, params, run, callback) {
  logsChannel(run.name).bind('history', payload => {
    const data = client.readFragment({
      id: run.id,
      fragment: fragments.detailedRun,
      variables: {bucketName: run.name},
    });
    console.log('Streamed history');
    //TODO: this has duplicates sometimes
    data.history = Array.from(new Set(data.history.concat(payload)));
    client.writeFragment({
      id: run.id,
      fragment: fragments.detailedRun,
      data: data,
    });
  });

  logsChannel(run.name).bind('events', payload => {
    const data = client.readFragment({
      id: run.id,
      fragment: fragments.detailedRun,
      variables: {bucketName: run.name},
    });
    //TODO: this has duplicates sometimes
    data.events = Array.from(new Set(data.events.concat(payload)));
    client.writeFragment({
      id: run.id,
      fragment: fragments.detailedRun,
      data: data,
    });
  });

  runChannel(pusherRunSlug(params)).bind('log', payload => {
    //console.time('log lines', payload.length);
    const data = client.readFragment({
      id: run.id,
      fragment: fragments.detailedRun,
      variables: {bucketName: run.name},
    });
    const edges = data.logLines.edges;

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
      id: run.id,
      fragment: fragments.detailedRun,
      data: data,
    });
    if (changed) callback();
    //console.timeEnd('log lines', payload.length);
  });

  runsChannel(pusherProjectSlug(params)).bind('updated', payload => {
    // Overwrite files data only if payload belongs to particular run
    if (run.id === payload.id) {
      //Update files
      const data = client.readFragment({
        id: run.id,
        fragment: fragments.detailedRun,
      });

      data.files = payload.files;
      data.fileCount = payload.fileCount;
      client.writeFragment({
        id: run.id,
        fragment: fragments.detailedRun,
        data: data,
      });
    }
  });
}

function mapStateToProps(state, ownProps) {
  return {stream};
}
export default withApollo(connect(mapStateToProps)(RunViewer));
