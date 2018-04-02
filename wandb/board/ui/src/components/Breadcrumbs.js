import React from 'react';
import {Breadcrumb} from 'semantic-ui-react';
import {NavLink} from 'react-router-dom';

const Breadcrumbs = ({model, entity, runs, run, sweep, extra, style}) => {
  const slug = '/' + entity + '/' + model;
  return (
    <Breadcrumb style={style} size="big">
      <Breadcrumb.Section>
        <NavLink to={'/' + entity}>{entity}</NavLink>
      </Breadcrumb.Section>
      {model && <Breadcrumb.Divider />}
      {model && (
        <Breadcrumb.Section>
          <NavLink to={slug}>{model}</NavLink>
        </Breadcrumb.Section>
      )}
      {runs && <Breadcrumb.Divider />}
      {runs && (
        <Breadcrumb.Section>
          <NavLink to={slug + '/runs'}>runs</NavLink>
        </Breadcrumb.Section>
      )}
      {run && <Breadcrumb.Divider />}
      {run && (
        <Breadcrumb.Section>
          <NavLink to={slug + '/runs/' + run}>{run}</NavLink>
        </Breadcrumb.Section>
      )}
      {sweep && <Breadcrumb.Divider />}
      {sweep && (
        <Breadcrumb.Section>
          <NavLink to={slug + '/sweeps/' + sweep}>{sweep}</NavLink>
        </Breadcrumb.Section>
      )}
      {extra && <Breadcrumb.Divider />}
      {extra && <Breadcrumb.Section>{extra}</Breadcrumb.Section>}
    </Breadcrumb>
  );
};
export default Breadcrumbs;
