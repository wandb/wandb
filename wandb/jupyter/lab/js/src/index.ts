import {
    ILayoutRestorer,
    JupyterFrontEnd,
    JupyterFrontEndPlugin
} from "@jupyterlab/application";

import { Dialog, ICommandPalette, showDialog } from "@jupyterlab/apputils";

import { PageConfig } from "@jupyterlab/coreutils";

import { IDocumentManager } from "@jupyterlab/docmanager";

import { Widget } from "@phosphor/widgets";

import { IRequestResult, request } from "./request";

import Postmate from "postmate";

import "../styles/index.css";

// tslint:disable: variable-name
let unique = 0;

const extension: JupyterFrontEndPlugin<void> = {
    activate,
    autoStart: true,
    id: "@jupyterlab/wandb",
    requires: [IDocumentManager, ICommandPalette, ILayoutRestorer]
};

class IFrameWidget extends Widget {
    constructor(path: string) {
        super();
        this.id = path + "-" + unique;
        unique += 1;

        this.title.label = path;
        this.title.closable = true;

        const div = document.createElement("div");
        div.classList.add("iframe-widget");
        const iframe = document.createElement("iframe");
        iframe.src = path;
        div.appendChild(iframe);
        this.node.appendChild(div);
    }
}

// tslint:disable-next-line: max-classes-per-file
class OpenIFrameWidget extends Widget {
    constructor() {
        const body = document.createElement("div");
        const existingLabel = document.createElement("label");
        existingLabel.textContent = "Site:";

        const input = document.createElement("input");
        input.value = "";
        input.placeholder = "http://path.to.site";

        body.appendChild(existingLabel);
        body.appendChild(input);

        super({ node: body });
    }

    public getValue(): string {
        return this.inputNode.value;
    }

    get inputNode(): HTMLInputElement {
        return this.node.getElementsByTagName("input")[0] as HTMLInputElement;
    }
}

export interface JupyterConfigData {
    token: string;
    page: "tree" | "view" | "edit";
    root: string;
    contentsPath: string;
    baseUrl: string;
    appVersion: string;
    assetUrl: string;
}

export function readConfig(
    rootEl: Element | null,
    dataEl: Element | null
): JupyterConfigData {
    if (!dataEl) {
        throw new Error("No jupyter config data element");
    }
    if (!rootEl) {
        console.warn("No root element");
    }

    let config: JupyterConfigData;

    try {
        if (!dataEl.textContent) {
            throw new Error("Unable to find Jupyter config data.");
        }
        config = JSON.parse(dataEl.textContent);
    } catch (err) {
        // Re-throw error
        throw err;
    }

    return config;
}

function activate(
    app: JupyterFrontEnd,
    docManager: IDocumentManager,
    palette: ICommandPalette,
    restorer: ILayoutRestorer
) {
    // Declare a widget variable
    let widget: IFrameWidget;
    const rootEl = document.querySelector("#root");
    const dataEl = document.querySelector("#jupyter-config-data");
    const config = readConfig(rootEl, dataEl);
    config.root = PageConfig.getBaseUrl();
    const handshake = new Postmate.Model({
        height: () => document.body.offsetHeight,
        setContext: (ctx: any) => {
            request(
                "post",
                PageConfig.getBaseUrl() + "wandb/context",
                { token: config.token }, // TODO: maybe using other auth
                ctx
            ).then((res: IRequestResult) => {
                if (res.ok) {
                    console.log("Config set", ctx);
                } else {
                    console.warn(res);
                }
            });
        }
    });

    handshake.then((parent: any) => {
        // Only emit the config to wandb
        if (parent.parentOrigin.match(/wandb\.ai|app\.test/)) {
            parent.emit("jupyter-config", JSON.stringify(config));
        }
    });

    // Add an application command
    const open_command = "wandb:open-url";

    app.commands.addCommand(open_command, {
        execute: args => {
            let path =
                typeof args.path === "undefined" ? "" : (args.path as string);

            if (path === "") {
                showDialog({
                    body: new OpenIFrameWidget(),
                    buttons: [
                        Dialog.cancelButton(),
                        Dialog.okButton({ label: "GO" })
                    ],
                    focusNodeSelector: "input",
                    title: "Open site"
                }).then(result => {
                    if (result.button.label === "CANCEL") {
                        return;
                    }

                    if (!result.value) {
                        return null;
                    }
                    path = result.value as string;
                    widget = new IFrameWidget(path);
                    app.shell.add(widget);
                    app.shell.activateById(widget.id);
                });
            } else {
                widget = new IFrameWidget(path);
                app.shell.add(widget);
                app.shell.activateById(widget.id);
            }
        },
        isEnabled: () => true,
        label: "Open IFrame"
    });

    // Add the command to the palette.
    palette.addItem({ command: open_command, category: "Sites" });

    // grab sites from serverextension
    request("get", PageConfig.getBaseUrl() + "wandb/").then(
        (res: IRequestResult) => {
            if (res.ok) {
                const jsn = res.json() as { [key: string]: string };
                const sites = jsn.sites;

                for (const site of sites) {
                    // tslint:disable-next-line: no-console
                    console.log("adding quicklink for " + site);
                }
            }
        }
    );
    // tslint:disable-next-line: no-console
    console.log("JupyterLab extension @jupyterlab/wandb is activated!");
}

export default extension;
export { activate as _activate };
