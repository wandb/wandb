ROOT_DIR="$PWD"
CORE_SRC_DIR="$PWD/../../../../core/frontends/app/src"

rm -rf util
rm -rf components
rm -rf assets
rm -rf config.ts

cp "${CORE_SRC_DIR}/config.ts" .

mkdir -p util
cd util
cp "${CORE_SRC_DIR}/util/data.ts" .
cp "${CORE_SRC_DIR}/util/digest.ts" .
cp "${CORE_SRC_DIR}/util/flatten.ts" .
cp "${CORE_SRC_DIR}/util/fuzzyMatch.tsx" .
cp "${CORE_SRC_DIR}/util/netron.ts" .
cp "${CORE_SRC_DIR}/util/json.ts" .
cp "${CORE_SRC_DIR}/util/markdown.ts" .
cp "${CORE_SRC_DIR}/util/obj.ts" .
cp "${CORE_SRC_DIR}/util/links.tsx" .
cp "../profiler.tsx" .
cp "${CORE_SRC_DIR}/util/path.ts" .
cp "${CORE_SRC_DIR}/util/shouldUpdate.ts" .
cp "${CORE_SRC_DIR}/util/string.ts" .
cp "${CORE_SRC_DIR}/util/update.ts" .
cp "${CORE_SRC_DIR}/util/vegaCommon.ts" .

cd "$ROOT_DIR"
mkdir -p types
cd types
cp "${CORE_SRC_DIR}/types/base.ts" .

cd "$ROOT_DIR"
mkdir -p css
cd css
cp "${CORE_SRC_DIR}/css/Code.less" .
cp "${CORE_SRC_DIR}/css/Markdown.less" .
cp "${CORE_SRC_DIR}/css/NoMatch.less" .
cp "${CORE_SRC_DIR}/css/ModifiedDropdown.less" .

cd "$ROOT_DIR"
mkdir -p components
cd components
cp -r "${CORE_SRC_DIR}/components/Panel2" .
cp "${CORE_SRC_DIR}/components/Code.tsx" .
cp "${CORE_SRC_DIR}/components/Code.styles.ts" .
cp "${CORE_SRC_DIR}/components/Markdown.tsx" .
cp "${CORE_SRC_DIR}/components/ShowMoreContainer.tsx" .
cp "${CORE_SRC_DIR}/components/NoMatch.tsx" .
cp "${CORE_SRC_DIR}/components/Input.tsx" .
cp "${CORE_SRC_DIR}/components/JupyterViewerRaw.tsx" .
cp "${CORE_SRC_DIR}/components/JupyterViewer.css" .
cp "${CORE_SRC_DIR}/components/WandbLoader.tsx" .

cd "$ROOT_DIR"
mkdir -p components/elements
cd components/elements
cp "${CORE_SRC_DIR}/components/elements/WBIcon.tsx" .
cp "${CORE_SRC_DIR}/components/elements/LegacyWBIcon.tsx" .
cp "${CORE_SRC_DIR}/components/elements/ModifiedDropdown.tsx" .
cp "${CORE_SRC_DIR}/components/elements/PanelError.tsx" .

cd "$ROOT_DIR"
mkdir -p assets
cd assets
cp -r "${CORE_SRC_DIR}/assets/wb-icons" .

cd "$ROOT_DIR"
mkdir -p components/Vega3
cd components/Vega3
cp "${CORE_SRC_DIR}/components/Vega3/CustomPanelRenderer.tsx" .
cp "${CORE_SRC_DIR}/components/Vega3/CustomPanelRenderer.styles.ts" .
cp "${CORE_SRC_DIR}/components/Vega3/Rasterize.js" .
