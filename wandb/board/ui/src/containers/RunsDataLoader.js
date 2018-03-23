// Loads Runs data, potentially including histories, based on a Query (see util/query.js)

import React from 'react';
import {bindActionCreators} from 'redux';
import {connect} from 'react-redux';
import {graphql, withApollo} from 'react-apollo';
import {RUNS_QUERY} from '../graphql/runs';
import {fragments, FAKE_HISTORY_QUERY, HISTORY_QUERY} from '../graphql/runs';
import {BOARD} from '../util/board';
import {makeShouldUpdate} from '../util/shouldUpdate';
import {
  displayFilterKey,
  updateRuns,
  setupKeySuggestions,
  filterRuns,
  sortRuns,
  getColumns,
} from '../util/runhelpers.js';
import withHistoryLoader from '../containers/HistoryLoader';
// TODO: read this from query
import {MAX_HISTORIES_LOADED} from '../util/constants.js';
import {JSONparseNaN} from '../util/jsonnan';
import * as Query from '../util/query';
import _ from 'lodash';

// TODO: imporve this hack
let RunsDataWorker;
try {
  RunsDataWorker = require('worker-loader!./workers/RunsDataDerived.js');
} catch (e) {
  RunsDataWorker = RunsDataWorkerMock;
}

// Load the graphql data for this panel, currently loads all data for this project and entity.
function withRunsData() {
  return graphql(RUNS_QUERY, {
    alias: 'withRunsData',
    skip: ({query}) => !Query.needsOwnRunsQuery(query),
    options: ({query, requestSubscribe}) => {
      const defaults = {
        variables: {
          entityName: query.entity,
          name: query.model,
          order: 'timeline',
          requestSubscribe: requestSubscribe || false,
        },
      };
      if (BOARD) {
        defaults.pollInterval = 5000;
      }
      if (Query.shouldPoll(query)) {
        defaults.pollInterval = 60000;
      }
      return defaults;
    },
    props: ({data: {loading, model, viewer, refetch}, errors}) => {
      //TODO: For some reason the first poll causes loading to be true
      // if (model && model.buckets && loading) loading = false;
      return {
        loading,
        refetch,
        buckets: model && model.buckets,
        views: model && model.views,
        projectID: model && model.id,
      };
    },
  });
}

// Parses buckets into runs/keySuggestions
function withDerivedRunsData(WrappedComponent) {
  let RunsDataDerived = class extends React.Component {
    state = {
      data: {
        base: [],
        filtered: [],
        filteredRunsById: {},
        selectedRuns: [],
        selectedRunsById: {},
        keys: [],
        axisOptions: [],
        columnNames: [],
      },
    };
    constructor(props) {
      super(props);
      this.runs = [];
      this.keySuggestions = [];
      this._shouldUpdate = makeShouldUpdate({
        name: 'RunsDataDerived',
        deep: ['query', 'pageQuery', 'config'],
        ignoreFunctions: true,
        debug: false,
      });
    }

    _setup(prevProps, props) {
      let strategy = Query.strategy(props.query);
      if (strategy === 'page') {
        this.setState({data: props.data});
      } else {
        let messageData = {
          base: props.data && props.data.base,
          prevBuckets: prevProps.buckets,
          buckets: props.buckets,
          query: props.query,
        };
        this.worker.postMessage(messageData);
      }
      this.views = props.views ? JSON.parse(props.views) : null;
    }

    componentWillMount() {
      this.worker = new RunsDataWorker();
      this.worker.onmessage = m => {
        this.setState({data: m.data});
      };
      this._setup({}, this.props);
    }

    shouldComponentUpdate(nextProps, nextState) {
      return (
        this._shouldUpdate(this.props, nextProps, this.props.histQueryKey) ||
        this.state.data !== nextState.data
      );
    }

    componentWillReceiveProps(nextProps) {
      if (
        this.props.buckets !== nextProps.buckets ||
        this.props.views !== nextProps.views ||
        this.props.data !== nextProps.data ||
        !_.isEqual(this.props.query, nextProps.query)
      ) {
        this._setup(this.props, nextProps);
      }
    }

    render() {
      return (
        <WrappedComponent
          {...this.props}
          data={this.state.data}
          views={this.views}
          keySuggestions={this.keySuggestions}
          runs={this.runs}
        />
      );
    }
  };

  return RunsDataDerived;
}

function withDerivedHistoryData(WrappedComponent) {
  let HistoryDataDerived = class extends React.Component {
    constructor(props) {
      super(props);
    }

    _setup(props, nextProps) {
      if (
        this.props.historyBuckets !== nextProps.historyBuckets ||
        this.props.data !== nextProps.data ||
        this.props.loading !== nextProps.loading
      ) {
        if (
          (nextProps.historyBuckets &&
            props.historyBuckets !== nextProps.historyBuckets) ||
          props.loading !== nextProps.loading
        ) {
          this.runHistory = nextProps.historyBuckets.edges.map(edge => ({
            name: edge.node.name,
            history: edge.node.history
              ? edge.node.history
                  .map((row, i) => {
                    try {
                      return JSONparseNaN(row);
                    } catch (error) {
                      console.log(
                        `WARNING: JSON error parsing history (HistoryLoader). Row: ${i}, Bucket: ${
                          edge.node.name
                        }`,
                      );
                      return null;
                    }
                  })
                  .filter(row => row !== null)
              : null,
          }));
          this.historyKeys = _.uniq(
            _.flatMap(
              _.uniq(
                _.flatMap(
                  this.runHistory,
                  o => (o.history ? o.history.map(row => _.keys(row)) : []),
                ),
              ),
            ),
          );
        }
        this.runHistories = {
          loading: nextProps.loading || this.runHistory.some(o => !o.history),
          maxRuns: MAX_HISTORIES_LOADED,
          totalRuns: _.keys(nextProps.data.selectedRunsById).length,
          data: this.runHistory.filter(
            o => o.history && nextProps.data.selectedRunsById[o.name],
          ),
          keys: this.historyKeys,
        };
        this.data = {...nextProps.data, histories: this.runHistories};
      }
    }

    componentWillMount() {
      this.data = this.props.data;
      this.runHistory = [];
      this._setup({}, this.props);
    }

    componentWillReceiveProps(nextProps) {
      if (!nextProps.historyBuckets) {
        this.data = nextProps.data;
        return;
      }
      this._setup(this.props, nextProps);
    }

    render() {
      return <WrappedComponent {...this.props} data={this.data} />;
    }
  };

  return HistoryDataDerived;
}

export default function withRunsDataLoader(WrappedComponent) {
  let RunsDataLoader = class extends React.Component {
    render() {
      return <WrappedComponent {...this.props} />;
    }
  };

  return withRunsData()(
    withDerivedRunsData(
      withHistoryLoader(withDerivedHistoryData(RunsDataLoader)),
    ),
  );
}
