import React from 'react';
import {graphql, compose, withApollo} from 'react-apollo';
import {
  Checkbox,
  Confirm,
  Container,
  Dropdown,
  Button,
  Grid,
  Icon,
  Input,
  Popup,
  Transition,
} from 'semantic-ui-react';
import RunFeed from '../components/RunFeed';
import RunFiltersRedux from './RunFiltersRedux';
import RunColumnsSelector from '../components/RunColumnsSelector';
import ViewModifier from './ViewModifier';
import HelpIcon from '../components/HelpIcon';
import {PROJECT_QUERY, MODIFY_RUNS} from '../graphql/runs';
import {MODEL_UPSERT} from '../graphql/models';
import {connect} from 'react-redux';
import queryString from 'query-string';
import _ from 'lodash';
import {
  sortRuns,
  defaultViews,
  parseBuckets,
  setupKeySuggestions,
} from '../util/runhelpers.js';
import {MAX_HISTORIES_LOADED} from '../util/constants.js';
import {bindActionCreators} from 'redux';
import {setColumns, setFilters} from '../actions/run';
import {
  resetViews,
  setServerViews,
  setBrowserViews,
  setActiveView,
  addView,
} from '../actions/view';
import update from 'immutability-helper';
import {BOARD} from '../util/board';
import withRunsDataLoader from '../containers/RunsDataLoader';
import withRunsQueryRedux from '../containers/RunsQueryRedux';
import * as Filter from '../util/filters';
import * as Selection from '../util/selections';
import * as Query from '../util/query';

class Runs extends React.Component {
  state = {showFailed: false, activeTab: 0, showFilters: false};

  componentDidUpdate() {
    window.Prism.highlightAll();
  }

  onSort = (column, order = 'descending') => {
    this.props.refetch({order: [column, order].join(' ')});
  };

  _updateQueryFromProps(query, props) {
    if (!_.isEmpty(props.runFilters)) {
      query.filters = Filter.toURL(props.runFilters);
    }
    if (!_.isEmpty(props.runSelections)) {
      query.selections = Filter.toURL(props.runSelections);
    }
    if (!_.isNil(props.activeView)) {
      query.activeView = props.activeView;
    }
  }

  _shareableUrl(props) {
    let query = {};
    this._updateQueryFromProps(query, props);
    return (
      `${window.location.protocol}//${window.location.host}${
        window.location.pathname
      }` +
      '?' +
      queryString.stringify(query)
    );
  }

  _setUrl(props, nextProps) {
    if (
      props.runFilters !== nextProps.runFilters ||
      props.runSelections !== nextProps.runSelections ||
      props.activeView !== nextProps.activeView
    ) {
      let query = queryString.parse(window.location.search) || {};
      this._updateQueryFromProps(query, nextProps);
      let url = `/${nextProps.match.params.entity}/${
        nextProps.match.params.model
      }/runs`;
      if (!_.isEmpty(query)) {
        url += '?' + queryString.stringify(query);
      }
      window.history.replaceState(null, null, url);
    }
  }

  _readUrl(props) {
    var parsed = queryString.parse(window.location.search);
    if (!parsed) {
      return;
    }
    let filterFilters;
    if (parsed.filters) {
      filterFilters = Filter.fromURL(parsed.filters);
    } else if (parsed.filter) {
      let filts = parsed.filter;
      if (!_.isArray(filts)) {
        filts = [filts];
      }
      filterFilters = Filter.fromOldURL(filts);
    }
    let selectFilters;
    if (parsed.selections) {
      selectFilters = Filter.fromURL(parsed.selections);
    } else if (parsed.select) {
      let filts = parsed.select;
      if (!_.isArray(filts)) {
        filts = [filts];
      }
      selectFilters = Filter.fromOldURL(filts);
    }

    if (filterFilters) {
      this.props.setFilters('filter', filterFilters);
    } else {
      this.props.setFilters('filter', {
        op: 'OR',
        filters: [
          {
            op: 'AND',
            filters: [
              {key: {section: 'tags', name: 'hidden'}, op: '=', value: false},
            ],
          },
        ],
      });
    }

    if (selectFilters) {
      this.props.setFilters('select', selectFilters);
    } else {
      this.props.setFilters('select', Selection.all());
    }

    if (!_.isNil(parsed.activeView)) {
      this.props.setActiveView('runs', parseInt(parsed.activeView, 10));
    }
  }

  componentWillMount() {
    this._readUrl(this.props);
  }

  componentDidMount() {
    this.doneLoading = false;

    this._setUrl({}, this.props);
  }

  componentWillReceiveProps(nextProps) {
    // Columns selction is disabled now, everything is automatic. We can re-enable
    // if someone asks for it.
    // if (
    //   !this.doneLoading &&
    //   nextProps.loading === false &&
    //   nextProps.data.base.length > 0
    // ) {
    //   this.doneLoading = true;
    //   let defaultColumns = {
    //     Description: true,
    //     Ran: true,
    //     Runtime: true,
    //     _ConfigAuto: true,
    //     Sweep: _.indexOf(nextProps.data.columnNames, 'Sweep') !== -1,
    //   };
    //   let summaryColumns = nextProps.data.columnNames.filter(col =>
    //     _.startsWith(col, 'summary')
    //   );
    //   for (var col of summaryColumns) {
    //     defaultColumns[col] = true;
    //   }
    //   this.props.setColumns(defaultColumns);
    // }
    // Setup views loaded from server.
    if (
      nextProps.views &&
      nextProps.views.runs &&
      !_.isEqual(nextProps.views, this.props.reduxServerViews)
    ) {
      if (
        _.isEqual(this.props.reduxServerViews, this.props.reduxBrowserViews)
      ) {
        this.props.setBrowserViews(nextProps.views);
      }
      this.props.setServerViews(nextProps.views);
    }

    this._setUrl(this.props, nextProps);
  }

  handleTabChange = (e, {activeIndex}) =>
    this.setState({activeTab: activeIndex});

  render() {
    let ModelInfo = this.props.ModelInfo;
    const filterCount = Filter.countIndividual(this.props.runFilters);
    return (
      <div>
        <Confirm
          open={this.state.showConfirm}
          onCancel={this.state.handleCancel}
          onConfirm={this.state.handleConfirm}
          content={this.state.confirmText}
          confirmButton={this.state.confirmButton}
        />
        <Grid>
          <Grid.Row divided columns={2}>
            <Grid.Column>{ModelInfo}</Grid.Column>
            <Grid.Column textAlign="right">
              <p style={{marginBottom: '.5em'}}>
                <Popup
                  content={
                    <Input
                      style={{minWidth: 520}}
                      value={this._shareableUrl(this.props)}
                    />
                  }
                  style={{width: '100%'}}
                  on="click"
                  position="bottom right"
                  wide="very"
                  trigger={
                    <Button
                      style={{marginRight: 6}}
                      icon="linkify"
                      size="mini"
                    />
                  }
                />
                {this.props.counts.runs} total runs,{' '}
                {this.props.counts.filtered} filtered,{' '}
                {this.props.counts.selected} selected
              </p>
              <div style={{marginTop: 8, marginBottom: 8}}>
                <Checkbox label="Grouping" />
              </div>
              <p>
                <span
                  style={{cursor: 'pointer'}}
                  onClick={() =>
                    this.setState({showFilters: !this.state.showFilters})
                  }>
                  <Icon
                    rotated={this.state.showFilters ? null : 'counterclockwise'}
                    name="dropdown"
                  />
                  {filterCount + ' Filter' + (filterCount === 1 ? '' : 's')}
                </span>
              </p>
            </Grid.Column>
          </Grid.Row>
          <Grid.Row>
            <Grid.Column>
              <Transition.Group
                className="ui grid"
                animation="slide right"
                duration={200}>
                {this.state.showFilters && (
                  <Grid.Row>
                    <Grid.Column width={16}>
                      <h5 style={{marginBottom: 6}}>
                        Filters{' '}
                        <HelpIcon text="Filters limit the set of runs that will be displayed in charts and tables on this page." />
                      </h5>
                      <RunFiltersRedux
                        entityName={this.props.match.params.entity}
                        projectName={this.props.match.params.model}
                        kind="filter"
                        buttonText="Add Filter"
                        filteredRunsCount={this.props.counts.filtered}
                      />
                    </Grid.Column>
                  </Grid.Row>
                )}
              </Transition.Group>
            </Grid.Column>
          </Grid.Row>
          {
            <Grid.Column width={16}>
              {this.props.haveViews && (
                <ViewModifier
                  viewType="runs"
                  data={this.props.data}
                  pageQuery={{
                    entity: this.props.match.params.entity,
                    project: this.props.match.params.model,
                    sort: this.props.sort,
                    filters: this.props.runFilters,
                    selections: this.props.runSelections,
                  }}
                  updateViews={views =>
                    this.props.updateModel({
                      entityName: this.props.match.params.entity,
                      name: this.props.match.params.model,
                      id: this.props.projectID,
                      views: views,
                    })
                  }
                />
              )}
            </Grid.Column>
          }
          <Grid.Column width={16} style={{zIndex: 2}}>
            {/* <Popup
              trigger={
                <Button
                  disabled={this.props.loading}
                  floated="right"
                  icon="columns"
                  content="Columns"
                />
              }
              content={
                <RunColumnsSelector columnNames={this.props.data.columnNames} />
              }
              on="click"
              position="bottom left"
            /> */}
            {!this.props.haveViews && (
              <Button
                floated="right"
                content="Add Charts"
                disabled={this.props.loading}
                icon="area chart"
                onClick={() => this.props.addView('runs', 'Charts', [])}
              />
            )}
            <Button
              floated="right"
              disabled={this.props.counts.selected === 0}
              onClick={e => {
                // TODO(adrian): this should probably just be a separate component
                e.preventDefault();

                this.setState({
                  showConfirm: true,
                  confirmText:
                    'Are you sure you would like to hide these runs? You can reverse this later by removing the "hidden" label.',
                  confirmButton: `Hide ${this.props.counts.selected} run(s)`,
                  handleConfirm: e => {
                    e.preventDefault();
                    this.props.modifyRuns({
                      filters: JSON.stringify(
                        Filter.toMongo(
                          Filter.And([
                            this.props.runFilters,
                            this.props.runSelections,
                          ])
                        )
                      ),
                      entityName: this.props.match.params.entity,
                      projectName: this.props.match.params.model,
                      addTags: ['hidden'],
                    });
                    this.setState({
                      showConfirm: false,
                      handleConfirm: null,
                      handleCancel: null,
                    });
                  },
                  handleCancel: e => {
                    e.preventDefault();
                    this.setState({
                      showConfirm: false,
                      handleConfirm: null,
                      handleCancel: null,
                    });
                  },
                });
              }}>
              <Icon name="hide" />
              Hide {this.props.counts.selected} run(s)
            </Button>
            <Dropdown
              icon={null}
              trigger={
                <Button>
                  <Icon
                    name={
                      this.props.counts.selected === 0
                        ? 'square outline'
                        : this.props.counts.selectedRuns ===
                          this.props.counts.filtered
                          ? 'checkmark box'
                          : 'minus square outline'
                    }
                  />
                  Select
                </Button>
              }
              onClick={(e, {value}) => console.log('dropdown click', value)}>
              <Dropdown.Menu>
                <Dropdown.Item
                  onClick={() =>
                    this.props.setFilters('select', Selection.all())
                  }>
                  <Icon
                    style={{marginRight: 4}}
                    color="grey"
                    name="checkmark box"
                  />{' '}
                  All
                </Dropdown.Item>
                <Dropdown.Item
                  onClick={() =>
                    this.props.setFilters('select', Selection.none())
                  }>
                  <Icon
                    style={{marginRight: 4}}
                    color="grey"
                    name="square outline"
                  />{' '}
                  None
                </Dropdown.Item>
              </Dropdown.Menu>
            </Dropdown>
            {/* <p style={{float: 'right'}}>
              Select
              <a>all</a>
              <a>none</a>
            </p> */}
          </Grid.Column>
        </Grid>
        <RunFeed
          match={this.props.match}
          loading={this.props.loading}
          project={this.props.project}
          onSort={this.onSort}
          query={{
            entity: this.props.match.params.entity,
            project: this.props.match.params.model,
            filters: this.props.runFilters,
            page: {
              // num: state.runs.pages[id] ? state.runs.pages[id].current : 0,
              size: 10,
            },
            sort: this.props.sort,
            disabled: this.props.loading,
            // TODO: Don't hardcode this
            grouping: {
              group: 'config:evaluation',
              // subgroup: 'config:machine_pool',
            },
            level: 'group',
          }}
        />
      </div>
    );
  }
}

const withMutations = compose(
  graphql(MODEL_UPSERT, {
    props: ({mutate}) => ({
      updateModel: variables =>
        mutate({
          variables: {...variables},
          updateQueries: {
            Model: (prev, {mutationResult}) => {
              const newModel = mutationResult.data.upsertModel.model;
              return update(prev, {model: {$set: newModel}});
            },
          },
        }),
    }),
  }),
  graphql(MODIFY_RUNS, {
    props: ({mutate}) => ({
      modifyRuns: variables => {
        mutate({
          variables: {...variables},
        });
      },
    }),
  })
);

function mapStateToProps(state, ownProps) {
  return {
    jobId: state.runs.currentJob,
    runFilters: state.runs.filters.filter,
    runSelections: state.runs.filters.select,
    user: state.global.user,
    sort: state.runs.sort,
    filterModel: state.runs.filterModel,
    reduxServerViews: state.views.server,
    reduxBrowserViews: state.views.browser,
    activeView: state.views.other.runs.activeView,
    haveViews:
      !_.isEqual(state.views.browser, state.views.server) ||
      state.views.browser.runs.tabs.length > 0,
  };
}

// export dumb component for testing purposes
export {Runs};

const mapDispatchToProps = (dispatch, ownProps) => {
  return bindActionCreators(
    {
      setColumns,
      setFilters,
      setServerViews,
      setBrowserViews,
      setActiveView,
      resetViews,
      addView,
    },
    dispatch
  );
};

const withData = graphql(PROJECT_QUERY, {
  options: ({match, runFilters, runSelections}) => {
    return {
      variables: {
        entityName: match.params.entity,
        name: match.params.model,
        filters: JSON.stringify(Filter.toMongo(runFilters)),
        selections: JSON.stringify(
          Filter.toMongo(Filter.And([runFilters, runSelections]))
        ),
      },
    };
  },
  props: ({data: {loading, project, viewer, fetchMore}, errors}) => {
    //TODO: For some reason the first poll causes loading to be true
    // if (project && projects.runs && loading) loading = false;
    return {
      loading,
      views: project && project.views && JSON.parse(project.views),
      projectID: project && project.id,
      counts: {
        runs: project && project.runCount,
        filtered: project && project.filteredCount,
        selected: project && project.selectedCount,
      },
    };
  },
});

export default connect(mapStateToProps, mapDispatchToProps)(
  withMutations(withData(Runs))
);
