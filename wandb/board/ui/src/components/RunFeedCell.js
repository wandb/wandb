import React from 'react';
import TimeAgo from 'react-timeago';
import {Checkbox, Table} from 'semantic-ui-react';
import RunFeedDescription from './RunFeedDescription';
import ValueDisplay from './RunFeedValueDisplay';
import {getRunValue} from '../util/runhelpers.js';

export default class RunFeedCell extends React.Component {
  render() {
    const {columnName, selected, run} = this.props;

    if (columnName === 'Select') {
      return (
        <Table.Cell collapsing>
          <Checkbox
            checked={selected}
            onChange={() => {
              let selections = this.props.selections;
              if (selected) {
                selections = Selection.Update.deselect(selections, run.name);
              } else {
                selections = Selection.Update.select(selections, run.name);
              }
              this.props.setFilters('select', selections);
            }}
          />
        </Table.Cell>
      );
    } else if (columnName === 'Description') {
      return <RunFeedDescription {...this.props} />;
    } else if (columnName === 'Ran') {
      return (
        <Table.Cell key={columnName} collapsing>
          <TimeAgo date={new Date(run.createdAt)} />
        </Table.Cell>
      );
    } else if (columnName === 'Runtime') {
      return (
        <Table.Cell key={columnName} collapsing>
          {run.heartbeatAt && (
            <TimeAgo
              date={new Date(run.createdAt)}
              now={() => new Date(run.heartbeatAt)}
              formatter={(v, u, s, d, f) => f().replace(s, '')}
              live={false}
            />
          )}
        </Table.Cell>
      );
    } else {
      let [section, key] = columnName.split(':');
      return (
        <Table.Cell
          key={columnName}
          style={{
            maxWidth: 200,
            direction: 'rtl',
            textOverflow: 'ellipsis',
            overflow: 'hidden',
          }}
          collapsing>
          <ValueDisplay
            section={section}
            valKey={key}
            value={getRunValue(run, columnName)}
            justValue
            addFilter={this.props.addFilter}
          />
        </Table.Cell>
      );
    }
  }
}
