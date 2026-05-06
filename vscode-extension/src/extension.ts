import * as vscode from 'vscode';

const MCP_SERVER_URL = 'https://ffbb.desimone.fr/mcp';

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
        })
    );
}

export function deactivate(): void {}
