import React from 'react';
import {Checkbox, Form, List} from 'semantic-ui-react';
import {enableColumn, disableColumn, toggleColumn} from '../actions/run';
import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';
import {batchActions} from 'redux-batched-actions';
import _ from 'lodash';

class Runs extends React.Component {
  render() {
    let sectionDropdown = (section, disabled) => {
      let cols = this.props.columnNames.filter(col =>
        _.startsWith(col, section),
      );
      let options = cols.map(name => ({
        key: name,
        value: name,
        text: name,
      }));
      let value = cols.filter(name => this.props.columns[name]);
      return (
        <Form.Dropdown
          placeholder="Columns"
          fluid
          search
          multiple
          selection
          options={disabled ? [{key: '_', value: '_', text: 'Auto'}] : options}
          value={disabled ? ['_'] : value}
          disabled={disabled}
          onChange={(e, {value}) => {
            let enables = value.map(col => enableColumn(col));
            let disables = _.without(cols, ...value).map(col =>
              disableColumn(col),
            );
            this.props.batchActions([...enables, ...disables]);
          }}
        />
      );
    };
    return (
      <Form style={{minWidth: 500}}>
        <h5>Columns</h5>
        <Form.Group inline>
          {['Description', 'Sweep', 'Ran', 'Runtime'].map(colName => (
            <Form.Checkbox
              key={colName}
              label={colName}
              checked={this.props.columns[colName]}
              onChange={() =>
                this.props.columns[colName]
                  ? this.props.disableColumn(colName)
                  : this.props.enableColumn(colName)}
            />
          ))}
        </Form.Group>
        <h5>Config</h5>
        <Form.Radio
          label="Auto"
          toggle
          checked={this.props.columns['_ConfigAuto']}
          onChange={() => this.props.toggleColumn('_ConfigAuto')}
        />
        {sectionDropdown('config', this.props.columns['_ConfigAuto'])}
        <h5>Summary</h5>
        {sectionDropdown('summary')}
      </Form>
    );
  }
}

function mapStateToProps(state, ownProps) {
  return {
    columns: state.runs.columns,
  };
}

const mapDispatchToProps = (dispatch, ownProps) => {
  return bindActionCreators(
    {batchActions, enableColumn, disableColumn, toggleColumn},
    dispatch,
  );
};

export default connect(mapStateToProps, mapDispatchToProps)(Runs);
