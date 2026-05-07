import * as vscode from 'vscode';

const MCP_SERVER_URL = 'https://ffbb.desimone.fr/mcp';
const MCP_INSTALL_URI = 'vscode:mcp/install?%7B%22name%22%3A%22ffbb-mcp%22%2C%22type%22%3A%22http%22%2C%22url%22%3A%22https%3A%2F%2Fffbb.desimone.fr%2Fmcp%22%7D';
const HAS_SHOWN_WELCOME_KEY = 'ffbbMcp.hasShownWelcome';
const INSTALL_ACTION = 'Installer le serveur MCP';

async function openMcpInstallUri(): Promise<void> {
    const opened = await vscode.env.openExternal(vscode.Uri.parse(MCP_INSTALL_URI));
    if (!opened) {
        await vscode.window.showErrorMessage(
            'Impossible d’ouvrir le lien d’installation FFBB MCP. Utilisez la configuration .vscode/mcp.json du README.'
        );
    }
}

export function activate(context: vscode.ExtensionContext): void {
    context.subscriptions.push(
        vscode.lm.registerMcpServerDefinitionProvider('ffbb-mcp', {
            provideMcpServerDefinitions: async () => [
                new vscode.McpHttpServerDefinition(
                    'FFBB Basketball',
                    vscode.Uri.parse(MCP_SERVER_URL)
                ),
            ],
            resolveMcpServerDefinition: async (server) => server,
        }),
        vscode.commands.registerCommand('ffbbMcp.installServer', openMcpInstallUri)
    );

    const hasShownWelcome = context.globalState.get<boolean>(HAS_SHOWN_WELCOME_KEY, false);
    if (!hasShownWelcome) {
        void context.globalState.update(HAS_SHOWN_WELCOME_KEY, true);
        void vscode.window
            .showInformationMessage('FFBB Basketball MCP est disponible pour Copilot Agent.', INSTALL_ACTION)
            .then(async (choice) => {
                if (choice === INSTALL_ACTION) {
                    await vscode.commands.executeCommand('ffbbMcp.installServer');
                }
            });
    }
}

export function deactivate(): void {}
