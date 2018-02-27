import React, {Component} from 'react';
import Panel from '../components/Panel';

class DashboardView extends Component {
  render() {
    return (
      <div>
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
            updateConfig={config =>
              this.props.updatePanel(i, {...panelConfig, config: config})
            }
            removePanel={() => this.props.removePanel(i)}
          />
        ))}
      </div>
    );
  }
}

export default DashboardView;
