import React from 'react';
import {Dimmer, Header, Icon} from 'semantic-ui-react';
import {connect} from 'react-redux';
import {resetError, setFlash} from '../actions';
import _ from 'lodash';

const ErrorPage = ({error, history, dispatch}) => {
  // If production, auto-reload after 20s
  if (process.env.NODE_ENV === 'production') {
    setTimeout(() => window.location.reload(true), 20000);
  }

  let icon,
    title,
    message,
    knownError = true;
  //For now let's grab the first error from the GQL server
  //TODO: why is this sometimes an array?
  if (Array.isArray(error)) error = error[0];
  //TODO: not sure what the null error case is...
  error = error || {message: 'Unknown error'};
  const fatal = error.fatal;
  message = error.message || 'Fatal error';
  if (error.graphQLErrors && error.graphQLErrors.length > 0)
    error = error.graphQLErrors[0];
  //TODO: Temporary fix
  if (!error.code && message.indexOf('not found') >= 0) error.code = 404;
  window.ga('send', 'exception', {
    exDescription: error.message,
    exFatal: fatal === true,
  });
  let instructions = 'Report the issue at github.com/wandb/client/issues.';
  if (message.match('has been deemed inappropriate')) {
    // this is a 400 when the name is on our banned list
    icon = 'frown';
    title = 'Bad name';
    message = 'Nice work! You found a name that is not allowed.';
    instructions = 'Try a different name.';
  } else {
    switch (error.code) {
      case 400:
        icon = 'ban';
        title = 'Invalid Record';
        message = message;
        instructions = 'Click to refresh.';
        break;
      case 403:
        icon = 'hide';
        title = 'Permission Denied';
        //For invite only signups
        if (error.error_description === 'Signup disabled') {
          message =
            'You must signup with the private invitation link provided in the slides.';
        } else {
          message =
            error.message ||
            'You do not have permission to access this resource.';
        }
        instructions = '';

        break;
      case 404:
        icon = 'stop circle outline';
        title = 'Not Found';
        message = "We couldn't find what you're looking for.";
        instructions = '';

        break;
      default:
        icon = 'bug';
        title = error.message || 'Application Error';
        message = 'You may have found a bug.';
        knownError = false;
    }
  }

  if (!knownError) {
    dispatch(setFlash({message: title, color: 'red'}));
    return false;
  }

  return (
    <Dimmer
      active={true}
      onClickOutside={() => {
        dispatch(resetError());
        if (error.code > 400 && history) history.goBack();
      }}>
      <Header as="h2" icon inverted>
        <Icon name={icon} />
        {title}
        <Header.Subheader>{message}</Header.Subheader>
      </Header>
      <p>{instructions}</p>
    </Dimmer>
  );
};

export default connect()(ErrorPage);
