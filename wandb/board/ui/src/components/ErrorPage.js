import React from 'react';
import {Dimmer, Header, Icon} from 'semantic-ui-react';
import {connect} from 'react-redux';
import {resetError} from '../actions';

const ErrorPage = ({error, history, dispatch}) => {
  let icon, title, message;
  //For now let's grab the first error from the GQL server
  //TODO: why is this sometimes an array?
  if (Array.isArray(error)) error = error[0];
  //TODO: not sure what the null error case is...
  error = error || {message: 'Unknown error'};
  const fatal = error.fatal;
  if (error.graphQLErrors && error.graphQLErrors.length > 0)
    error = error.graphQLErrors[0];
  //TODO: Temporary fix
  if (!error.code && error.message.indexOf('not found') >= 0) error.code = 404;
  window.ga('send', 'exception', {
    exDescription: error.message,
    exFatal: fatal === true,
  });
  let instructions = 'Click anywhere to go back to the last page you visited.';
  switch (error.code) {
    case 400:
      icon = 'ban';
      title = 'Invalid Record';
      message = error.message;
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

      break;
    case 404:
      icon = 'stop circle outline';
      title = 'Not Found';
      message = "We couldn't find what you're looking for.";
      break;
    default:
      icon = 'bug';
      title = 'Application Error';
      message = "You may have found a bug, we've been notified.";
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
