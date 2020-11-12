import * as _ from 'lodash';
import React from 'react';
import {Icon, Table, Pagination} from 'semantic-ui-react';
import {useState} from 'react';
import LegacyWBIcon from '../elements/LegacyWBIcon';
import numeral from 'numeral';

import * as Panel2 from './panel';
import * as File from './files';
import * as Path from '../../util/path';
import makeComp from '../../util/profiler';

const PAGE_SIZE = 25;

const inputType = {
  type: 'dir' as const,
};

type PanelPreviewDirProps = Panel2.PanelProps<typeof inputType>;

interface DirViewProps {
  dir: File.DirMetadata;
  path: string[];
  setFilePath(path: string[]): void;
}

const DirView: React.FC<DirViewProps> = makeComp(
  props => {
    const {dir, path, setFilePath} = props;
    // TODO: make this use config?
    const [displayOffset, setDisplayOffset] = useState(0);

    // Dirs above files
    const dirNames = Object.keys(dir.dirs).sort();
    const fileNames = Object.keys(dir.files).sort();
    const dirsAndFiles = [...dirNames, ...fileNames];

    return (
      <>
        <Table unstackable selectable className="file-browser-table">
          <Table.Body>
            {dirsAndFiles
              .slice(displayOffset, displayOffset + PAGE_SIZE)
              .map(dirOrFile => {
                if (dir.dirs[dirOrFile] != null) {
                  return (
                    <SubdirRow
                      key={'folder-' + dirOrFile}
                      dir={dir.dirs[dirOrFile]}
                      dirName={dirOrFile}
                      path={path}
                      setFilePath={setFilePath}
                    />
                  );
                  // return this.renderSubFolder(currentFolder, folderOrFile, i);
                } else {
                  const file = dir.files[dirOrFile];
                  return (
                    <SubfileRow
                      key={'file-' + dirOrFile}
                      fileName={dirOrFile}
                      file={file}
                      path={path}
                      setFilePath={setFilePath}
                    />
                  );
                }
              })}
          </Table.Body>
        </Table>
        {dirsAndFiles.length > PAGE_SIZE && (
          <div style={{display: 'flex', justifyContent: 'center'}}>
            <Pagination
              defaultActivePage={1}
              totalPages={Math.ceil(dirsAndFiles.length / PAGE_SIZE)}
              onPageChange={(e, data) => {
                const pg = data.activePage;
                if (pg != null && _.isNumber(pg)) {
                  setDisplayOffset((pg - 1) * PAGE_SIZE);
                }
              }}
              size="small"
            />
          </div>
        )}
      </>
    );
  },
  {id: 'DirView'}
);

interface SubdirRowProps {
  dir: File.DirMetadata;
  dirName: string;
  path: string[];
  setFilePath(path: string[]): void;
}

const SubdirRow: React.FC<SubdirRowProps> = makeComp(
  props => {
    const {dir, dirName, path, setFilePath} = props;
    const subFolderCount = Object.keys(dir.dirs).length;
    const fileCount = Object.keys(dir.files).length;
    const newPath = path.concat([dirName]);
    return (
      <Table.Row
        className="file-browser-folder"
        onClick={() => setFilePath(newPath)}>
        <Table.Cell className="folder-name-cell">
          <div className="file-browser-name-cell-wrapper">
            <LegacyWBIcon className="file-browser-icon" name="folder" />
            <span className="file-browser-folder-name">{dirName}</span>
            &nbsp;/
          </div>
        </Table.Cell>
        <Table.Cell className="file-link-cell" />
        <Table.Cell className="file-size-cell">
          {numeral(dir.size).format('0.0b')}
        </Table.Cell>
        <Table.Cell className="contents-cell">
          {subFolderCount !== 0 &&
            subFolderCount +
              (subFolderCount === 1 ? ' subfolder, ' : ' subfolders, ')}
          {fileCount + (fileCount === 1 ? ' file' : ' files')}
        </Table.Cell>
        {/* <Table.Cell className="hide-in-mobile" /> */}
      </Table.Row>
    );
  },
  {id: 'SubdirRow'}
);

interface SubfileRowProps {
  file: File.FileMetadata;
  fileName: string;
  path: string[];
  setFilePath(path: string[]): void;
}

const SubfileRow: React.FC<SubfileRowProps> = makeComp(
  props => {
    const {file, fileName, path, setFilePath} = props;
    const newPath = path.concat([fileName]);
    const iconName = iconFromFileName(fileName);
    // const iconName = fileInfo.iconName;

    return (
      <Table.Row
        onClick={() => {
          if (file.ref) {
            if (file.ref.startsWith('http://')) {
              window.open(file.ref);
            }
          } else {
            setFilePath(newPath);
          }
        }}>
        <Table.Cell className="file-name-cell">
          <div className="file-browser-name-cell-wrapper">
            {file.ref != null ? (
              <Icon
                style={{color: '#007faf', width: 28}}
                name="arrow alternate circle right outline"
              />
            ) : (
              <LegacyWBIcon className="file-browser-icon" name={iconName} />
            )}
            <span className="file-browser-file-name">
              {fileName.split('/').pop()}
            </span>
          </div>
        </Table.Cell>
        <Table.Cell className="file-link-cell">{file.ref ?? ''}</Table.Cell>
        <Table.Cell className="file-size-cell">
          {numeral(file.size).format('0.0b')}
        </Table.Cell>
        <Table.Cell>
          <a href={file.url} onClick={e => e.stopPropagation()}>
            <LegacyWBIcon name="download" />
          </a>
        </Table.Cell>
      </Table.Row>
    );
  },
  {id: 'SubfileRow'}
);

function iconFromFileName(fileName: string): string {
  const extension = Path.extension(fileName);
  switch (extension) {
    case 'md':
      return 'file-markdown';
    case 'log':
    case 'text':
    case 'txt':
      return 'file';
    case 'js':
    case 'css':
    case 'patch':
    case 'json':
      return 'file-code';
    case 'ipynb':
    case 'py':
      return 'file-python';
    case 'yaml':
    case 'xml':
    case 'html':
    case 'htm':
      return 'file-yaml';
    case 'jpg':
    case 'jpeg':
    case 'png':
    case '.tiff':
    case '.tif':
    case '.gif':
      return 'file-image';
  }
  return 'file';
}

export const PanelPreviewDir: React.FC<PanelPreviewDirProps> = props => {
  const dir = props.input.val.node as File.DirMetadata;
  return (
    <DirView
      dir={dir}
      path={props.context.path!}
      setFilePath={path => props.updateContext({path})}
    />
  );
};

export const Spec: Panel2.PanelSpec = {
  id: 'dir',
  displayName: 'Directory',
  Component: PanelPreviewDir,
  inputType,
};
