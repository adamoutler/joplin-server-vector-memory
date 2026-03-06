```json
{
  "mcpServers": {
    "plane-kanban": {
      "url": "https://plane.hackedyour.info/mcp/http/api-key/mcp",
      "headers": {
        "Authorization": "Bearer ${PLANE_KEY}",
        "X-Workspace-slug": "<SLUG>"
      }
    }
  }
}
```
1. Request the Plane Project Slug, replace SLUG with the user-provided SLUG
2. Tell user to add PLANE_KEY to `~/.bashrc` or to ensure the environmental variable is set otherwise for each session so you can connect.