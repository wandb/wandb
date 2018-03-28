import React from 'react';
import _ from 'lodash';
import {Form, Icon} from 'semantic-ui-react';
import {registerPanelClass} from '../util/registry.js';
import {BOARD} from '../util/board';

class ImagesPanel extends React.Component {
  state = {epoch: 0};
  static type = 'Images';
  static options = {};

  static validForData(data) {
    return (
      !_.isNil(data.history) &&
      _.values(data.history[0]).find(v => v && v._type === 'images')
    );
  }

  zoomLevels() {
    return [0.25, 0.5, 1, 1.5, 2, 4].map(z => {
      return {
        key: z,
        value: z,
        text: z,
      };
    });
  }

  filters() {
    return [
      ['invert', 1],
      ['brightness', 1.5],
      ['contrast', 1.5],
      ['grayscale', 1],
      ['saturate', 2],
    ].map(([f, v]) => {
      return {
        key: f,
        value: f + '(' + v + ')',
        text: f,
      };
    });
  }

  renderConfig() {
    return (
      <Form>
        <Form.Group widths="equal">
          <Form.Select
            label="Zoom"
            options={this.zoomLevels()}
            value={this.props.config.zoom || 1}
            onChange={(e, {value}) =>
              this.props.updateConfig({...this.props.config, zoom: value})
            }
          />
          <Form.Select
            label="Filter"
            options={this.filters()}
            value={this.props.config.filter}
            onChange={(e, {value}) =>
              this.props.updateConfig({
                ...this.props.config,
                filter: value,
              })
            }
          />
        </Form.Group>
      </Form>
    );
  }

  renderError(message) {
    return (
      <div
        style={{
          position: 'absolute',
          height: 200,
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}>
        <div
          style={{
            maxWidth: 300,
            backgroundColor: 'white',
            border: '1px dashed #999',
            padding: 15,
            color: '#666',
          }}>
          <Icon name="file image outline" />
          {message}
        </div>
      </div>
    );
  }

  renderNormal() {
    let {history} = this.props.data;
    //TODO: performance / don't hard code imageKey
    let imageKey = 'examples';
    let images = history.map(h => h[imageKey]);

    if (images.length == 0) {
      return this.renderError(
        <p>
          There are no images. For more information on how to collect history,
          check out our documentation at{' '}
          <a href="http://docs.wandb.com/#media">
            http://docs.wandb.com/#media
          </a>
        </p>,
      );
    }

    let captions = images[this.state.epoch]
      ? images[this.state.epoch].captions ||
        new Array(images[this.state.epoch].count)
      : '';
    let {width, height} = images[0];
    let sprite;
    if (BOARD) {
      sprite =
        'http://localhost:7177' +
        this.props.data.match.url +
        `/${imageKey}_` +
        this.state.epoch +
        '.jpg';
    } else {
      let {entity, model, run} = this.props.data.match.params;
      sprite = `https://api.wandb.ai/${entity}/${model}/${run}/media/images/${imageKey}_${
        this.state.epoch
      }.jpg`;
    }
    let ticks = Math.min(8, history.length);
    let tickMarks = [];
    for (let i = 0; i < ticks; i++) {
      if (ticks < 8) tickMarks.push(i);
      else tickMarks.push(Math.ceil(i * (history.length / 8)));
    }
    return (
      <div>
        <h3>Epoch {this.state.epoch}</h3>
        {captions.map((label, i) => {
          return (
            <div
              key={i}
              style={{
                float: 'left',
                zoom: this.props.config.zoom || 1,
                filter: this.props.config.filter || 'none',
                padding: 5,
                textAlign: 'center',
              }}>
              <div
                style={{
                  backgroundImage: `url(${sprite})`,
                  width: width,
                  height: height,
                  backgroundPosition: `${i * width}px 0`,
                }}
              />
              <span style={{fontSize: '0.6em', lineHeight: '1em'}}>
                {label}
              </span>
            </div>
          );
        })}
        <input
          type="range"
          list="epochs"
          min={0}
          max={history.length - 2}
          step={1}
          value={this.state.epoch}
          style={{width: '100%'}}
          onChange={e => {
            this.setState({epoch: e.target.value});
          }}
        />
        <datalist id="epochs">
          {tickMarks.map(i => {
            return <option key={i}>{i}</option>;
          })}
        </datalist>
      </div>
    );
  }

  render() {
    this.lines = this.props.config.lines || [];
    if (this.props.configMode) {
      return (
        <div>
          {this.renderNormal()}
          {this.renderConfig()}
        </div>
      );
    } else {
      return this.renderNormal();
    }
  }
}
registerPanelClass(ImagesPanel);
