import React from 'react';
import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';
import {Button, Popup} from 'semantic-ui-react';
import {enableColumn} from '../actions/run';
import {displayValue} from '../util/runhelpers.js';

class ValueDisplay extends React.PureComponent {
  render() {
    return (
      <Popup
        on="hover"
        hoverable
        position="left center"
        style={{padding: 6}}
        trigger={
          <span className="config">
            {this.props.content ? (
              <span className="value"> {this.props.content} </span>
            ) : (
              <span>
                <span className="value">{displayValue(this.props.value)}</span>{' '}
                {!this.props.justValue && (
                  <span className="key">{this.props.valKey}</span>
                )}
              </span>
            )}
          </span>
        }
        content={
          <span>
            {this.props.enablePopout && (
              <Popup
                on="hover"
                inverted
                size="tiny"
                trigger={
                  <Button
                    style={{padding: 6}}
                    icon="external square"
                    onClick={() => {
                      this.props.enableColumn(
                        this.props.section + ':' + this.props.valKey
                      );
                    }}
                  />
                }
                content="Pop out"
              />
            )}
            <Popup
              on="hover"
              inverted
              size="tiny"
              trigger={
                <Button
                  style={{padding: 6}}
                  icon="unhide"
                  onClick={() => {
                    let filterKey = {
                      section: this.props.section,
                      name: this.props.valKey,
                    };
                    this.props.addFilter(
                      'filter',
                      filterKey,
                      '=',
                      sortableValue(this.props.value)
                    );
                  }}
                />
              }
              content="Add filter"
            />
          </span>
        }
      />
    );
  }
}

const mapValueDisplayDispatchToProps = (dispatch, ownProps) => {
  return bindActionCreators({enableColumn}, dispatch);
};

export default connect(null, mapValueDisplayDispatchToProps)(ValueDisplay);
