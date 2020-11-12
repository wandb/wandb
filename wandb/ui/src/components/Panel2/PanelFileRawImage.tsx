import React from 'react';
import * as Panel2 from './panel';
import * as File from './files';

const IMAGE_FILE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'tiff', 'tif', 'gif'];

const inputType = {
  type: 'union' as const,
  members: IMAGE_FILE_EXTENSIONS.map(ext => ({
    type: 'file' as const,
    extension: ext,
  })),
};

type PanelPreviewImageProps = Panel2.PanelProps<typeof inputType>;

export const PanelPreviewImage: React.FC<PanelPreviewImageProps> = props => {
  // TODO: we don't need this case if we improve the type system more
  // to differentiate directories from files
  const file = props.input.val.node as File.FileMetadata;
  const path = props.input.val.fullPath;
  return (
    <div>
      <div>NEW PANEL!</div>
      <img style={{maxWidth: '100%'}} alt={path.path} src={file.url} />
    </div>
  );
};

export const Spec: Panel2.PanelSpec = {
  id: 'rawimage',
  displayName: 'Image',
  Component: PanelPreviewImage,
  inputType,
};
