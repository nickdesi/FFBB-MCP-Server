"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = require("vscode");
const MCP_SERVER_URL = 'https://ffbb.desimone.fr/mcp';
function activate(context) {
    context.subscriptions.push(vscode.lm.registerMcpServerDefinitionProvider('ffbb-mcp', {
        provideMcpServerDefinitions: async () => [
            new vscode.McpHttpServerDefinition('FFBB Basketball', vscode.Uri.parse(MCP_SERVER_URL)),
        ],
        resolveMcpServerDefinition: async (server) => server,
    }));
}
function deactivate() { }
//# sourceMappingURL=extension.js.map