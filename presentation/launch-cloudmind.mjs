import { execSync, spawnSync } from "node:child_process";
import { readFile, stat } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const project = fileURLToPath(new URL(".", import.meta.url));
const dist = join(project, "dist");

async function hasBuild() {
  try {
    const manifest = JSON.parse(await readFile(join(dist, ".vite", "manifest.json"), "utf8"));
    if (!manifest["index.html"]?.isEntry) return false;

    const files = ["index.html", "mesures-cloudmind.json"];
    for (const entry of Object.values(manifest)) {
      files.push(entry.file, ...(entry.css ?? []), ...(entry.assets ?? []));
    }
    const stats = await Promise.all(files.map((file) => stat(join(dist, file))));
    return stats.every((file) => file.isFile() && file.size > 0);
  } catch (error) {
    if (error.code === "ENOENT" || error instanceof SyntaxError) return false;
    throw error;
  }
}

async function launch() {
  if (Number(process.versions.node.split(".")[0]) < 20) {
    throw new Error("Install Node.js 20 or newer and reopen this launcher.");
  }

  let preview;
  try {
    ({ preview } = await import("vite"));
  } catch (error) {
    throw new Error(`Vite could not load. Run npm.cmd ci in "${project}" and try again. ${error.message}`);
  }

  if (!(await hasBuild())) {
    console.log("Building CloudMind...");
    try {
      execSync("npm.cmd run build", { cwd: project, stdio: "inherit" });
    } catch {
      throw new Error("Build failed. Review the output above. Check that npm is on PATH and run npm.cmd ci if dependencies are missing.");
    }
    if (!(await hasBuild())) throw new Error("The build did not produce all required presentation files.");
  }

  const server = await preview({
    root: project,
    preview: { host: "127.0.0.1", port: 0, strictPort: true, open: false },
  });
  const url = `http://127.0.0.1:${server.httpServer.address().port}/`;
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(5000) });
    await response.body?.cancel();
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
  } catch (error) {
    await server.close();
    throw new Error(`The local server did not serve the presentation at ${url} (${error.message}).`);
  }

  console.log(`CloudMind is ready at ${url}`);
  console.log("Keep this window open. Close it to stop the local server.");
  const browser = spawnSync("cmd.exe", ["/d", "/c", "start", url], { stdio: "inherit" });
  if (browser.error || browser.status !== 0) {
    console.error(`Windows could not open the default browser. Open ${url} manually.`);
  }
}

launch().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
