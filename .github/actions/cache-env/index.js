// Appends the cache service's address and token to GITHUB_ENV. Only node
// actions are handed these, and actions/cache reads them from the environment.
const fs = require("fs");
const names = ["ACTIONS_RUNTIME_TOKEN", "ACTIONS_RESULTS_URL", "ACTIONS_CACHE_URL", "ACTIONS_CACHE_SERVICE_V2"];
if (!process.env.ACTIONS_RUNTIME_TOKEN) {
  console.log("::error::no ACTIONS_RUNTIME_TOKEN in the action's environment");
  process.exit(1);
}
let out = "";
for (const name of names) {
  const value = process.env[name];
  if (value) out += `${name}<<CT_EOF\n${value}\nCT_EOF\n`;
}
fs.appendFileSync(process.env.GITHUB_ENV, out);
