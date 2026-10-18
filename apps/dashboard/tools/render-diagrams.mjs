import { chromium } from "playwright";
import { createServer } from "vite";
import { readFile, readdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const directory = resolve(process.cwd(), "..", "..", "docs", "diagrams");
const server = await createServer({
  configFile: false,
  root: process.cwd(),
  server: { host: "127.0.0.1", port: 5199, strictPort: true },
  plugins: [
    {
      name: "owned-diagram-shell",
      configureServer(runtime) {
        runtime.middlewares.use("/__diagram_render", (_request, response) => {
          response.setHeader("Content-Type", "text/html");
          response.end(
            '<!doctype html><html lang="en"><head><title>Owned diagram renderer</title></head><body></body></html>',
          );
        });
      },
    },
  ],
});
let browser;
try {
  await server.listen();
  browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto("http://127.0.0.1:5199/__diagram_render");
  let index = 0;
  for (const file of (await readdir(directory)).filter((name) => name.endsWith(".mmd")).sort()) {
    const source = await readFile(resolve(directory, file), "utf-8");
    const svg = await page.evaluate(
      async ({ source, index }) => {
        const { default: mermaid } = await import("/node_modules/mermaid/dist/mermaid.esm.min.mjs");
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: "base",
          themeVariables: {
            primaryColor: "#162235",
            primaryTextColor: "#e4ebf5",
            primaryBorderColor: "#5d728d",
            lineColor: "#8294ae",
            secondaryColor: "#153b39",
            tertiaryColor: "#111d2d",
            background: "#0b1220",
            mainBkg: "#111d2d",
            textColor: "#e4ebf5",
            actorBkg: "#162235",
            actorTextColor: "#e4ebf5",
            actorBorder: "#5d728d",
            noteBkgColor: "#253247",
            noteTextColor: "#e4ebf5",
            edgeLabelBackground: "#0b1220",
            fontFamily: "Arial",
          },
          flowchart: { htmlLabels: false, useMaxWidth: false },
        });
        const rendered = (await mermaid.render(`mirage-diagram-${index}`, source)).svg;
        const document = new DOMParser().parseFromString(rendered, "image/svg+xml");
        document.documentElement.style.backgroundColor = "#0b1220";
        return new XMLSerializer().serializeToString(document);
      },
      { source, index: index++ },
    );
    if (!svg.includes("<svg")) throw new Error(`Invalid rendered diagram: ${file}`);
    await writeFile(resolve(directory, file.replace(/\.mmd$/, ".svg")), svg, "utf-8");
    console.log(`Rendered ${file}`);
  }
} finally {
  if (browser) await browser.close();
  await server.close();
}
