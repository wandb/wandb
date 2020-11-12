import React from 'react';
import {useState} from 'react';
import logo from './logo.svg';
import {FilesPanel} from './components/Panel2/PanelFiles';

import 'semantic-ui-css/semantic.min.css'

export interface Bla {
  name: 5;
}
function App() {
  const [context, setContext] = useState<any>({path: []});
  const [config, setConfig] = useState<any>({path: []});
  return (
    <div style={{width: 1200, marginLeft: 'auto', marginRight: 'auto', paddingTop: 80, paddingBottom: 80}}>
      <FilesPanel
        input={{
          columns: ['local'],
          context: [
            {
              entityName: 'local',
              projectName: 'local',
              artifactTypeName: 'local',
              artifactSequenceName: 'local',
              artifactCommitHash: 'local',
              path: '',
            },
          ],
          data: [
            [
              {
                entityName: 'local',
                projectName: 'local',
                artifactTypeName: 'local',
                artifactSequenceName: 'local',
                artifactCommitHash: 'local',
              },
            ],
          ],
        }}
        loading={false}
        context={context}
        config={config}
        configMode={false}
        updateConfig={(newConfig) => setConfig({...config, ...newConfig})}
        updateContext={(newContext) => setContext({...context, ...newContext})}
      />
    </div>
  );
}

export default App;
