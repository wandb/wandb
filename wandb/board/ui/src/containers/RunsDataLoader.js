/*eslint-disable import/no-webpack-loader-syntax*/
// The above is required for client, but not core... we seem to have stricter build settings
// in client.
// TODO:
//   - use strict build settings in core
//   - fixup webpack so that we don't need the worker-loader! syntax
// Loads Runs data, potentially including histories, based on a Query (see util/query.js)
//
// There is a lot of old cruft in here, from before switching to backend querying.
// TODO: Lots of cleanup

import React from 'react';
import {bindActionCreators} from 'redux';
import {connect} from 'react-redux';
import {graphql, withApollo} from 'react-apollo';
import {RUNS_QUERY} from '../graphql/runs';
import {fragments, FAKE_HISTORY_QUERY, HISTORY_QUERY} from '../graphql/runs';
import {BOARD} from '../util/board';
import {makeShouldUpdate} from '../util/shouldUpdate';
import {
  updateRuns,
  setupKeySuggestions,
  sortRuns,
  getColumns,
} from '../util/runhelpers.js';
import withHistoryLoader from '../containers/HistoryLoader';
// TODO: read this from query
import {MAX_HISTORIES_LOADED} from '../util/constants.js';
import {JSONparseNaN} from '../util/jsonnan';
import * as Query from '../util/query';
import * as Run from '../util/runs';
import * as RunHelpers2 from '../util/runhelpers2';
import * as Filter from '../util/filters';
import _ from 'lodash';

// Load the graphql data for this panel.
function withRunsData() {
  return graphql(RUNS_QUERY, {
    alias: 'withRunsData',
    skip: ({query}) => !Query.needsOwnRunsQuery(query),
    options: ({query, requestSubscribe}) => {
      let order = 'timeline';
      if (query.sort && query.sort.name) {
        const serverPath = Run.keyStringToServerPath(query.sort.name);
        if (serverPath) {
          order = (query.sort.ascending ? '-' : '+') + serverPath;
        }
      }
      const defaults = {
        fetchPolicy: 'network-only',
        variables: {
          entityName: query.entity,
          name: query.model,
          order: order,
          requestSubscribe: requestSubscribe || false,
          history: !!query.history,
          limit: query.page && query.page.size,
          filters: JSON.stringify(Filter.toMongo(query.filters)),
          fields: query.select,
          basicEnable: !query.select,
        },
        notifyOnNetworkStatusChange: true,
      };
      if (BOARD) {
        defaults.pollInterval = 5000;
      }
      if (Query.shouldPoll(query)) {
        defaults.pollInterval = 60000;
      }
      return defaults;
    },
    props: ({
      data: {loading, project, viewer, fetchMore},
      ownProps,
      errors,
    }) => {
      let lastFetchMoreEndCursor;
      return {
        loading,
        runs: project && project.runs,
        views: project && project.views,
        projectID: project && project.id,
        historyBuckets: ownProps.query.history && project && project.runs,
        runCount: project && project.runCount,
        loadMore:
          project &&
          project.runs &&
          project.runs.pageInfo.hasNextPage &&
          (onDone => {
            if (lastFetchMoreEndCursor === project.runs.pageInfo.endCursor) {
              onDone();
              return;
            }
            lastFetchMoreEndCursor = project.runs.pageInfo.endCursor;
            fetchMore({
              variables: {
                cursor: project.runs.pageInfo.endCursor,
              },
              updateQuery: (previousResult, {fetchMoreResult}) => {
                const newEdges = fetchMoreResult.project.runs.edges;
                const pageInfo = fetchMoreResult.project.runs.pageInfo;

                return newEdges.length
                  ? {
                      project: {
                        __typename: previousResult.project.__typename,
                        id: previousResult.project.id,
                        runs: {
                          __typename: previousResult.project.runs.__typename,
                          edges: [
                            ...previousResult.project.runs.edges,
                            ...newEdges,
                          ],
                          pageInfo,
                        },
                      },
                    }
                  : previousResult;
              },
            }).then(onDone);
          }),
      };
    },
  });
}

// Parses runs into runs/keySuggestions
function withDerivedRunsData(WrappedComponent) {
  let RunsDataDerived = class extends React.Component {
    defaultData = {
      loading: false,
      base: [],
      filtered: [],
      filteredRunsById: {},
      keys: [],
      axisOptions: [],
      columnNames: [],
      loadMore: null,
      histories: {
        maxRuns: MAX_HISTORIES_LOADED,
        totalRuns: 0,
        data: [],
        keys: [],
      },
    };

    constructor(props) {
      super(props);
      this.keySuggestions = [];
      this._shouldUpdate = makeShouldUpdate({
        name: 'RunsDataDerived',
        deep: ['query', 'pageQuery', 'config'],
        ignoreFunctions: true,
        debug: false,
      });
    }

    _setup(prevProps, props) {
      this.views = props.views ? JSON.parse(props.views) : null;

      const prevRuns = prevProps.runs;
      const curRuns = props.runs;
      const query = props.query;

      const runs = updateRuns(prevRuns, curRuns, []);
      let filteredRuns = runs;
      let keys = curRuns && RunHelpers2.keySuggestions(curRuns.paths);
      keys = keys || [];
      let filteredRunsById = {};
      for (var run of filteredRuns) {
        filteredRunsById[run.name] = run;
      }

      let axisOptions = keys.map(key => {
        let displayKey = Run.displayKey(key);
        return {
          key: displayKey,
          value: displayKey,
          text: displayKey,
        };
      });

      let runHistories;
      if (props.historyBuckets) {
        const runHistory = props.historyBuckets.edges.map(edge => ({
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
                      }`
                    );
                    return null;
                  }
                })
                .filter(row => row !== null)
            : null,
        }));
        const historyKeys = _.uniq(
          _.flatMap(
            _.uniq(
              _.flatMap(
                runHistory,
                o => (o.history ? o.history.map(row => _.keys(row)) : [])
              )
            )
          )
        );
        runHistories = {
          data: runHistory.filter(o => o.history),
          keys: historyKeys,
        };
      }

      let columnNames = getColumns(runs);
      let data = {
        loading: props.loading,
        base: runs,
        filtered: filteredRuns,
        filteredRunsById,
        keys: keys,
        axisOptions,
        columnNames,
        loadMore: props.loadMore,
        totalRuns: props.runCount,
        limit: props.query.page.size,
        histories: runHistories || {
          data: [],
          keys: [],
        },
      };
      this.data = data;
    }

    componentWillMount() {
      if (!Query.needsOwnRunsQuery(this.props.query)) {
        this.data = this.defaultData;
        return;
      }
      this._setup({}, this.props);
    }

    shouldComponentUpdate(nextProps, nextState) {
      return this._shouldUpdate(this.props, nextProps, this.props.histQueryKey);
    }

    componentWillReceiveProps(nextProps) {
      if (!Query.needsOwnRunsQuery(nextProps.query)) {
        this.data = this.defaultData;
        return;
      }
      if (
        this.props.loading !== nextProps.runs ||
        this.props.runs !== nextProps.runs ||
        this.props.historyBuckets !== nextProps.historyBuckets ||
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
          data={this.data}
          views={this.views}
          keySuggestions={this.keySuggestions}
        />
      );
    }
  };

  return RunsDataDerived;
}

export default function withRunsDataLoader(WrappedComponent) {
  let RunsDataLoader = class extends React.Component {
    render() {
      return <WrappedComponent {...this.props} />;
    }
  };

  return withRunsData()(withDerivedRunsData(RunsDataLoader));
}
