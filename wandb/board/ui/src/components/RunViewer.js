import React from 'react';
import {Grid, List, Popup, Header, Tab, Segment} from 'semantic-ui-react';
import RunSummary from './RunSummary';
import numeral from 'numeral';
import ReactTable from 'react-table';
import 'react-table/react-table.css';
import Breadcrumbs from '../components/Breadcrumbs';
import StreamingLog from '../containers/StreamingLog';
import Files from '../components/Files';
import ConfigList from '../components/ConfigList';
import SummaryList from '../components/SummaryList';
import SystemList from '../components/SystemList';
import ViewModifier from '../containers/ViewModifier';
import './Run.css';
import {JSONparseNaN} from '../util/jsonnan';
import _ from 'lodash';

/*
 * This component shows a big table of runs
 */

export default class RunViewer extends React.Component {
  state = {};
  static defaultProps = {};

  handleTabChange = (e, data) => {
    this.setState({
      activeIndex: data.activeIndex,
    });
  };

  panes() {
    // NOTE as an alternative, fc value can be extracted directly from files length
    const fc = this.props.run.fileCount,
      files = fc === 1 ? '1 File' : fc + ' Files';
    const panes = [
      {
        menuItem: 'Training Log',
        render: () => (
          <Tab.Pane>
            <StreamingLog
              match={this.props.match}
              run={this.props.run}
              logLines={this.props.run.logLines}
            />
          </Tab.Pane>
        ),
      },
    ];
    if (fc > 0) {
      panes.push({
        menuItem: files,
        render: () => (
          <Tab.Pane>
            <Segment inverted>
              <Files files={this.props.run.files} />
            </Segment>
          </Tab.Pane>
        ),
      });
    }
    return panes;
  }

  config() {
    this._config =
      this._config ||
      (this.props.run.config && JSONparseNaN(this.props.run.config));
    return this._config;
  }

  parseData(rows, type) {
    if (!rows) {
      return [null, null];
    }
    let data = rows
      .map((line, i) => {
        try {
          return JSONparseNaN(line);
        } catch (error) {
          console.log(`WARNING: JSON error parsing ${type}:${i}:`, error);
          return null;
        }
      })
      .filter(row => row !== null);
    let keys = _.flatMap(data, row =>
      _.keys(row).filter(key => !row[key] || !row[key]._type),
    );
    keys = _.uniq(keys);
    keys = _.sortBy(keys);
    return [keys, data];
  }

  render() {
    const {project, run, condensed} = this.props;
    let [histKeys, histData] = this.parseData(run.history, 'history');
    let [eventKeys, eventData] = this.parseData(run.events, 'events');
    const summaryMetrics = JSONparseNaN(run.summaryMetrics),
      systemMetrics = JSONparseNaN(run.systemMetrics);
    const columns = Object.keys(systemMetrics || {}).length > 0 ? 3 : 2;

    let exampleTableTypes = JSONparseNaN(run.exampleTableTypes);
    let exampleTable = JSONparseNaN(run.exampleTable);
    let exampleTableColumns = JSONparseNaN(run.exampleTableColumns);
    return (
      <Grid stackable className="run">
        <Grid.Row>
          <Grid.Column>
            <Breadcrumbs
              entity={this.props.project.entityName}
              model={this.props.project.name}
            />
          </Grid.Column>
        </Grid.Row>
        <Grid.Row>
          <Grid.Column>
            <RunSummary
              onStop={this.props.onStop}
              project={project}
              run={run}
              condensed={condensed}
            />
          </Grid.Column>
        </Grid.Row>
        <Grid.Row columns={1}>
          <Grid.Column>
            <ViewModifier
              viewType="run"
              data={{
                historyKeys: histKeys,
                history: histData,
                eventKeys: eventKeys,
                events: eventData,
                match: this.props.match,
              }}
              blank={!histData || histData.length === 0}
              updateViews={this.props.updateViews}
              loader={true}
            />
          </Grid.Column>
        </Grid.Row>
        {exampleTable &&
          exampleTable.length !== 0 && (
            <Grid.Row columns={1}>
              <Grid.Column>
                <Header>Examples</Header>
                <ReactTable
                  style={{width: '100%'}}
                  defaultPageSize={10}
                  columns={exampleTableColumns.map((name, i) => {
                    let type = exampleTableTypes[name];
                    return {
                      Header: name,
                      accessor: name,
                      //minWidth: type == 'histogram' ? 400 : undefined,
                      Cell: row => {
                        let val = row.value;
                        if (type === 'image') {
                          val = (
                            <Popup
                              trigger={
                                <img
                                  style={{'max-width': 128}}
                                  src={'data:image/png;base64,' + val}
                                  alt="example"
                                />
                              }>
                              <img
                                style={{width: 256}}
                                src={'data:image/png;base64,' + val}
                                alt="example"
                              />
                            </Popup>
                          );
                        } else if (type === 'float' && val) {
                          // toPrecision converts to exponential notation only
                          // when abs(exponent) >-= 7, so we get a lot of zeroes
                          // that make for a long string at exponent==6. We control
                          // the conversion more carefully here to control the displayed
                          // string length.
                          if (Math.abs(val) > 1000 || Math.abs(val) < 0.001) {
                            val = val.toExponential(4);
                          } else {
                            val = val.toPrecision(4);
                          }
                        } else if (type === 'percentage' && val) {
                          let percentage = val * 100;
                          val = (
                            <div
                              style={{
                                width: '100%',
                                backgroundColor: '#dadada',
                                borderRadius: '2px',
                              }}>
                              <div
                                style={{
                                  width: `${percentage}%`,
                                  height: 12,
                                  backgroundColor:
                                    percentage > 66
                                      ? '#85cc00'
                                      : percentage > 33 ? '#ffbf00' : '#ff2e00',
                                  borderRadius: '2px',
                                  transition: 'all .2s ease-out',
                                }}
                              />
                            </div>
                          );
                        }
                        return (
                          <div
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              width: '100%',
                              height: '100%',
                            }}>
                            {val}
                          </div>
                        );
                      },
                    };
                  })}
                  data={exampleTable}
                />
              </Grid.Column>
            </Grid.Row>
          )}
        <Grid.Row columns={columns} className="vars">
          <Grid.Column>
            <Header>Configuration</Header>
            <ConfigList data={this.config()} />
          </Grid.Column>
          <Grid.Column>
            <Header>Summary</Header>
            <SummaryList data={summaryMetrics} />
          </Grid.Column>
          {columns === 3 && (
            <Grid.Column>
              <Header>Utilization</Header>
              <SystemList data={systemMetrics} />
            </Grid.Column>
          )}
        </Grid.Row>
        <Grid.Row columns={1}>
          <Grid.Column>
            <Tab
              onTabChange={this.handleTabChange}
              activeIndex={this.state.activeIndex}
              panes={this.panes()}
            />
          </Grid.Column>
        </Grid.Row>
      </Grid>
    );
  }
}
