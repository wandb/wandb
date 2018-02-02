export let panelClasses = {};

export function registerPanelClass(panelClass) {
  panelClasses[panelClass.type] = panelClass;
}
