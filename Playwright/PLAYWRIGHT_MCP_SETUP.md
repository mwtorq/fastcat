# Playwright MCP Server Setup Guide

This guide will help you install and configure the Playwright MCP (Model Context Protocol) server for Cursor IDE.

## Prerequisites

1. **Node.js**: You need Node.js installed on your system. If you don't have it:
   - Download and install from [https://nodejs.org/](https://nodejs.org/)
   - Make sure to add Node.js to your system PATH during installation
   - Verify installation by running: `node --version` and `npm --version`

## Installation Methods

### Method 1: Automated Setup (Recommended)

Run the provided PowerShell script:

```powershell
.\setup_playwright_mcp.ps1
```

This script will:
- Check for Node.js installation
- Install the Playwright MCP server using Smithery CLI (recommended for Cursor)
- Install Playwright browser binaries
- Configure the server for Cursor

### Method 2: Manual Installation

If you prefer to install manually:

1. **Install Playwright MCP Server using Smithery (Recommended for Cursor):**
   ```bash
   npx -y @smithery/cli install @automatalabs/mcp-server-playwright --client cursor
   ```

2. **Or install using npm:**
   ```bash
   npm install -g @playwright/mcp
   ```

3. **Install Playwright browsers:**
   ```bash
   npx playwright install
   ```

## Configuration

### For Cursor IDE

The Smithery CLI should automatically configure Cursor. However, if you need to configure manually:

1. **Locate Cursor's configuration directory:**
   - Windows: `%APPDATA%\Cursor\User\`
   - The MCP configuration might be in a settings file or in the globalStorage directory

2. **Add MCP server configuration:**
   
   If you need to manually configure, add the following to your Cursor settings (the exact location depends on Cursor's current configuration system):

   ```json
   {
     "mcpServers": {
       "playwright": {
         "command": "npx",
         "args": [
           "-y",
           "@automatalabs/mcp-server-playwright"
         ]
       }
     }
   }
   ```

   A template configuration file (`cursor_mcp_config.json`) has been created for reference.

### Alternative Configuration (if using @playwright/mcp)

If you installed using `@playwright/mcp` instead, use this configuration:

```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": [
        "-y",
        "@playwright/mcp"
      ]
    }
  }
}
```

## Verification

To verify the installation:

1. **Test the MCP server manually:**
   ```bash
   npx -y @automatalabs/mcp-server-playwright
   ```

2. **Restart Cursor IDE** to ensure the MCP server is loaded

3. **Check in Cursor:**
   - The Playwright MCP server should appear in Cursor's MCP server list
   - You should be able to use browser automation features through the AI assistant

## Troubleshooting

### Node.js not found
- Make sure Node.js is installed and added to your system PATH
- Restart your terminal/IDE after installing Node.js
- Verify with: `node --version`

### Installation fails
- Try running the installation command with administrator privileges
- Check your internet connection
- Ensure npm is working: `npm --version`

### MCP server not appearing in Cursor
- Restart Cursor IDE completely
- Check Cursor's settings for MCP server configuration
- Verify the configuration file is in the correct location
- Check Cursor's logs for any error messages

### Browser installation issues
- Run `npx playwright install` manually
- Check that you have sufficient disk space
- Some browsers may require additional system dependencies

## Additional Resources

- [Playwright MCP Documentation](https://github.com/microsoft/playwright-mcp)
- [MCP Server Playwright (Automata Labs)](https://www.mcp.bar/server/Automata-Labs-team/MCP-Server-Playwright)
- [Smithery CLI Documentation](https://github.com/modelcontextprotocol/servers/tree/main/src/smithery)

## Support

If you encounter issues:
1. Check the error messages in the terminal
2. Review Cursor's logs
3. Verify all prerequisites are met
4. Try the manual installation method if automated setup fails


