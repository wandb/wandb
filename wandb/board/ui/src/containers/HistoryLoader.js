// This module is not used currently.
// It can load individual histories in, smartly batching queries together.

import React from 'react';
import {graphql, withApollo} from 'react-apollo';
import {fragments, FAKE_HISTORY_QUERY, HISTORY_QUERY} from '../graphql/runs';
import {bindActionCreators} from 'redux';
import {connect} from 'react-redux';
import {sortRuns} from '../util/runhelpers.js';
import {JSONparseNaN} from '../util/jsonnan';
import {MAX_HISTORIES_LOADED} from '../util/constants.js';
import _ from 'lodash';
import * as Query from '../util/query';
import * as Filter from '../util/filters';

// We track which histories are in the process of loading globally.
let loadingHistories = {};

export default function withHistoryLoader(WrappedComponent) {
  let HistoryLoader = class extends React.Component {
    constructor(props) {
      super(props);
    }

    _setup(props, nextProps) {
      // In polling mode we always reload all history data. Note the check below
      // to see if selectedRuns has changed from previous props to now will only
      // be true when the withRunsData loader upstream from us has polled new data
      // (or when some other parameters have changed, which doesn't happen on the
      // dashboard page right now)
      let pollingMode = true;

      if (nextProps.data.filtered !== props.data.filtered) {
        //console.log('SelectionQueryThing willReceiveProps', nextProps);
        let selected = _.fromPairs(
          nextProps.data.filtered
            .slice(0, MAX_HISTORIES_LOADED)
            .map(run => [run.name, run.id])
        );
        // find set of selected runs that have not been fetched
        //console.log('n selected', _.size(selected));
        let selectedInfo = _.map(selected, (id, name) => {
          // if (this.historyLoadedRuns[id]) {
          //   return {id: id, alreadyLoaded: true};
          // }
          let history = null;
          try {
            let result = nextProps.client.readFragment({
              id,
              fragment: fragments.historyRun,
            });
            //console.log('readFragment history result', result);
            history = result.history;
          } catch (err) {
            //console.log("name doesn't have history", name);
          }
          let loadingHistory = loadingHistories[id];
          return {
            id: id,
            name: name,
            history: history,
            loadingHistory: loadingHistory,
          };
        });
        //console.log('selectedInfo', selectedInfo);
        let numLoaded = selectedInfo.filter(o => o.history || o.loadingHistory)
          .length;
        if (pollingMode || numLoaded < MAX_HISTORIES_LOADED) {
          let toLoad = selectedInfo;
          if (!pollingMode) {
            toLoad = toLoad.filter(o => !(o.history || o.loadingHistory));
          }
          if (toLoad.length > 0) {
            for (var load of toLoad) {
              loadingHistories[load.id] = true;
            }
            nextProps.client
              .query({
                fetchPolicy: pollingMode ? 'network-only' : 'cache-first',
                query: HISTORY_QUERY,
                variables: {
                  entityName: nextProps.query.entity,
                  name: nextProps.query.model,
                  filters: JSON.stringify(
                    Filter.toMongo({
                      op: 'AND',
                      filters: toLoad.map(o => ({
                        key: {section: 'run', name: 'name'},
                        op: '=',
                        value: o.name,
                      })),
                    })
                  ),
                },
              })
              .then(result => {
                //console.log('result', result);
                for (var load of toLoad) {
                  loadingHistories[load.id] = false;
                }
              });
          }
        }
        nextProps.client.writeQuery({
          query: FAKE_HISTORY_QUERY,
          variables: {histQueryKey: nextProps.histQueryKey},
          data: {
            project: {
              id: 'fake_history_query_' + nextProps.histQueryKey,
              __typename: 'Project',
              runs: {
                __typename: 'RunConnectionType',
                edges: selectedInfo.map(o => ({
                  node: {
                    id: o.id,
                    name: o.name,
                    history: o.history,
                    __typename: 'Run',
                  },
                  __typename: 'RunEdge',
                })),
              },
            },
          },
        });
      }
    }

    componentWillMount() {
      this.historyLoadedRuns = {};
      this._setup({data: {}}, this.props);
    }

    componentWillReceiveProps(nextProps) {
      this._setup(this.props, nextProps);
    }

    render() {
      return <WrappedComponent {...this.props} />;
    }
  };

  const withData = graphql(FAKE_HISTORY_QUERY, {
    options: ({histQueryKey}) => {
      return {
        fetchPolicy: 'cache-only',
        variables: {
          histQueryKey: histQueryKey,
        },
      };
    },
    props: ({data, errors}) => ({
      historyBuckets: (data.project && data.project.runs) || {edges: []},
    }),
  });

  return withApollo(withData(HistoryLoader));
}
