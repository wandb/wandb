import React from 'react';
import _ from 'lodash';
import {Form, Icon} from 'semantic-ui-react';
import {registerPanelClass} from '../util/registry.js';
import {BOARD} from '../util/board';
import Slider from 'react-slick';
import 'slick-carousel/slick/slick.css';
import 'slick-carousel/slick/slick-theme.css';
import './PanelImages.css';

class ImagesPanel extends React.Component {
  state = {epoch: 0, containerWidth: 0};
  static type = 'Images';
  static options = {};

  static validForData(data) {
    return (
      // we are looking for any element in history with a value with
      !_.isNil(data.history) && this.imageKeys(data.history).length > 0
    );
  }

  static imageKeys(history) {
    /**
     * Find all the keys in history that ever have the type "image"
     *
     * History obejcts look like
     * [ { "loss": 1, "acc": 2},
     * { "loss": 3, "example":{"_type": "images"}}]
     * We want to find all keys where "_type" is ever set to images
     */

    let imageKeys = [];
    for (let row in history) {
      _.keys(history[row])
        .filter(k => {
          return (
            history[row][k] &&
            history[row][k]._type &&
            history[row][k]._type === 'images'
          );
        })
        .map(key => {
          if (imageKeys.indexOf(key) == -1) {
            imageKeys.push(key);
          }
        });
    }
    return imageKeys;
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

  getImageSize(images) {
    const minHeight = 60,
      maxHeight = 440;
    let image = images[0];
    if (image.height < minHeight) {
      image.width = image.width * (minHeight / image.height);
      image.height = minHeight;
    }
    if (image.height > maxHeight) {
      image.width = image.width / (image.height / maxHeight);
      image.height = maxHeight;
    }
    return image;
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
    //TODO: handle multiple keys
    let imageKey = ImagesPanel.imageKeys(history)[0];
    let images = history.map(h => h[imageKey]).filter(img => img);

    if (images.length == 0) {
      return this.renderError(
        <p>
          There are no images. For more information on how to collect history,
          check out our documentation at{' '}
          <a href="https://docs.wandb.com/docs/logs.html#media">
            https://docs.wandb.com/docs/logs.html#media
          </a>
        </p>
      );
    }

    let captions = images[this.state.epoch]
      ? images[this.state.epoch].captions ||
        new Array(images[this.state.epoch].count)
      : '';
    let {width, height, count} = this.getImageSize(images);
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
    // minus the top margin with Step label, and bottom pager and range
    let containerHeight = this.props.currentHeight - 80;
    let enableSlick = captions.length > 1;
    let zoom = this.props.config.zoom || 1;
    let rowNumber = Math.floor(containerHeight / ((height + 20) * zoom)) || 1;
    let slideNumber =
      Math.floor(this.state.containerWidth / ((width + 20) * zoom)) || 1;
    let settings = {
      dots: true,
      className: (enableSlick ? 'slickEnabled ' : '') + 'center',
      centerMode: true,
      infinite: true,
      speed: 500,
      slidesToShow: 1,
      rows: enableSlick ? rowNumber : 1,
      slidesPerRow: enableSlick ? slideNumber : 1,
      unslick: !enableSlick,
    };
    return (
      <div
        className="panelImagesWrapper"
        ref={container => (this.container = container)}>
        <h3>Step {this.state.epoch}</h3>
        {captions ? (
          <Slider {...settings}>
            {captions.map((label, i) => {
              return (
                <div key={i} className="imageWrapper">
                  <div
                    style={{
                      zoom: zoom,
                      filter: this.props.config.filter || 'none',
                      padding: 5,
                    }}>
                    <div
                      style={{
                        backgroundImage: `url(${sprite})`,
                        width: width,
                        height: height,
                        backgroundPosition: `-${i * width}px 0`,
                        backgroundSize: 'cover',
                        margin: '0 auto',
                      }}
                    />
                  </div>
                  <span style={{fontSize: '1em', lineHeight: '1em'}}>
                    {label}
                  </span>
                </div>
              );
            })}
          </Slider>
        ) : (
          <p>No Images Uploaded for epoch {this.state.epoch}</p>
        )}

        <input
          type="range"
          list="epochs"
          min={0}
          max={history.length - 2}
          step={1}
          value={this.state.epoch}
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

  componentDidMount() {
    //TODO: Window resize?
    if (this.container)
      this.setState({containerWidth: this.container.clientWidth});
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
