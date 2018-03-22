import Enzyme, {shallow, render, mount} from 'enzyme';
import Adapter from 'enzyme-adapter-react-16';
import chai, {expect} from 'chai';
import sinon from 'sinon';
import sinonChai from 'sinon-chai';
import configureStore from 'redux-mock-store';
chai.use(sinonChai);

Enzyme.configure({adapter: new Adapter()});

// TODO: replace it with jest-localstorage-mock
const localStorageMock = {
  getItem: jest.fn(),
  setItem: jest.fn(),
  clear: jest.fn(),
};

const RunsDataWorkerMock = function() {
  this.onmessage = jest.fn();
  this.postMessage = jest.fn();
};

global.sinon = sinon;
global.shallow = shallow;
global.render = render;
global.mount = mount;
global.expect = expect;
global.mockStore = configureStore();
global.localStorage = localStorageMock;
global.RunsDataWorkerMock = RunsDataWorkerMock;
