import React from 'react';
import {Button, Dropdown, Form, Checkbox} from 'semantic-ui-react';
import withRunsDataLoader from '../containers/RunsDataLoader';
import RunKeySelector from '../components/RunKeySelector';
import * as Run from '../util/runs';
import * as UIHelpers from '../util/uihelpers';
import * as _ from 'lodash';

class RunFeedConfig extends React.Component {
  render() {
    const configCols = this.props.config.config || {};
    const configAuto = configCols.auto == null || configCols.auto;
    const summaryCols = this.props.config.summary || {};
    const summaryAuto = summaryCols.auto == null || summaryCols.auto;

    const grouping = this.props.config.grouping || {};

    const configKeys = this.props.data.keys.filter(key =>
      _.startsWith(key, 'config')
    );
    const summaryKeys = this.props.data.keys.filter(key =>
      _.startsWith(key, 'summary')
    );

    return (
      <Form style={{minWidth: 500}}>
        <Form.Field>
          <label>Config Columns</label>
          <Form.Radio
            label="Auto"
            toggle
            checked={configAuto}
            onChange={() =>
              this.props.update({
                ...this.props.config,
                config: {
                  ...configCols,
                  auto: !configAuto,
                },
              })
            }
          />
          <Dropdown
            placeholder="Columns"
            fluid
            search
            multiple
            selection
            options={UIHelpers.makeOptions(configKeys)}
            value={configCols.columns || []}
            disabled={!!configAuto || this.props.loading}
            onChange={(e, {value}) => {
              this.props.update({
                ...this.props.config,
                config: {
                  auto: false,
                  columns: value,
                },
              });
            }}
            loading={this.props.loading}
          />
        </Form.Field>
        <Form.Field>
          <label>Summary Columns</label>
          <Form.Radio
            label="Auto"
            toggle
            checked={summaryAuto}
            onChange={() =>
              this.props.update({
                ...this.props.config,
                summary: {
                  ...summaryCols,
                  auto: !summaryAuto,
                },
              })
            }
          />
          <Dropdown
            placeholder="Columns"
            fluid
            search
            multiple
            selection
            options={UIHelpers.makeOptions(summaryKeys)}
            value={summaryCols.columns || []}
            disabled={!!summaryAuto || this.props.loading}
            onChange={(e, {value}) => {
              this.props.update({
                ...this.props.config,
                summary: {
                  auto: false,
                  columns: value,
                },
              });
            }}
            loading={this.props.loading}
          />
        </Form.Field>
        <Form.Field>
          <label>Group</label>
          <RunKeySelector
            allowBlank
            loading={this.props.loading}
            keys={configKeys}
            storedKey={grouping.group}
            onClear={() =>
              this.props.update({
                ...this.props.config,
                grouping: {},
              })
            }
            onValidSelection={keyString =>
              this.props.update({
                ...this.props.config,
                grouping: {group: keyString},
              })
            }
            disabled={this.props.loading}
          />
        </Form.Field>
        <Form.Field>
          <label>Subgroup</label>
          <RunKeySelector
            allowBlank
            loading={this.props.loading}
            keys={configKeys}
            storedKey={grouping.subgroup}
            onClear={() =>
              this.props.update({
                ...this.props.config,
                grouping: {...this.props.config.grouping, subgroup: undefined},
              })
            }
            onValidSelection={keyString =>
              this.props.update({
                ...this.props.config,
                grouping: {...this.props.config.grouping, subgroup: keyString},
              })
            }
            disabled={!grouping.group || this.props.loading}
          />
        </Form.Field>
        <Form.Field>
          <Button
            color="yellow"
            floated="right"
            content="Save Changes"
            disabled={!this.props.isModified}
            onClick={() => {
              this.props.saveChanges();
            }}
          />
        </Form.Field>
      </Form>
    );
  }
}

export default withRunsDataLoader(RunFeedConfig);
