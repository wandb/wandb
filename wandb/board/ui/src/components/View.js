import React from 'react';
import ReactDOM from 'react-dom';
import {Button, Form, Grid} from 'semantic-ui-react';
import Panel from '../components/Panel';

class View extends React.Component {
  _makeUpdatePanelMethods(config) {
    // We do this so that child props don't change
    if (config) {
      this.updateConfig = config.map((panelConfig, i) => newConfig =>
        this.props.updatePanel(i, {
          ...panelConfig,
          config: newConfig,
        }),
      );
    }
  }

  componentWillMount() {
    this._makeUpdatePanelMethods(this.props.config);
  }

  componentWillReceiveProps(nextProps) {
    if (nextProps.config !== this.props.config) {
      this._makeUpdatePanelMethods(nextProps.config);
    }
    if (nextProps.editMode) {
      const tab = ReactDOM.findDOMNode(this).querySelector('.tab-name input');
      if (tab) {
        tab.focus();
      }
    }
  }

  render() {
    return (
      <Grid>
        {this.props.editMode && (
          <Grid.Column width={16}>
            <Form>
              <Form.Group>
                <Form.Input
                  placeholder="Tab Name"
                  value={this.props.name}
                  className="tab-name"
                  onChange={(e, {value}) => this.props.changeViewName(value)}
                />
                {/* hidden button so the remove button's onClick doesn't fire when the
                    user presses enter within the Tab Name input field */}
                <Form.Button style={{display: 'none'}} />
                <Form.Button
                  icon="x"
                  content="Remove Tab"
                  onClick={() => {
                    this.props.removeView();
                  }}
                />
              </Form.Group>
            </Form>
          </Grid.Column>
        )}
        {this.props.config.map((panelConfig, i) => (
          <Panel
            key={i}
            editMode={this.props.editMode}
            type={panelConfig.viewType}
            size={panelConfig.size}
            config={panelConfig.config}
            data={this.props.data}
            updateType={newType =>
              this.props.updatePanel(i, {...panelConfig, viewType: newType})
            }
            updateSize={newSize =>
              this.props.updatePanel(i, {...panelConfig, size: newSize})
            }
            panelIndex={i}
            updateConfig={this.updateConfig[i]}
            removePanel={() => this.props.removePanel(i)}
          />
        ))}
        {this.props.editMode && (
          <Grid.Column width={8}>
            <Button
              icon="plus"
              content="Add Panel"
              onClick={() => this.props.addPanel({})}
            />
          </Grid.Column>
        )}
      </Grid>
    );
  }
}

export default View;
