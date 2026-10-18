import { readFile, readdir, writeFile, mkdir } from "node:fs/promises";
import { resolve, sep } from "node:path";

const root = process.cwd();
const lock = JSON.parse(await readFile(resolve(root, "package-lock.json"), "utf-8"));
const sections = [
  "Hades Mirage - third-party runtime notices",
  "Generated from locked installed runtime dependencies. This is not a license grant for the new project.",
  "Upstream copyright and license text follows, including the bundled Inter font notices.",
];
for (const [entry, metadata] of Object.entries(lock.packages).sort(([a], [b]) =>
  a.localeCompare(b),
)) {
  if (!entry.startsWith("node_modules/") || metadata.dev) continue;
  const directory = resolve(root, entry.split("/").join(sep));
  const pkg = JSON.parse(await readFile(resolve(directory, "package.json"), "utf-8"));
  const licenses = (await readdir(directory)).filter((name) =>
    /^(licen[cs]e|copying|ofl)([._-]|$)/i.test(name),
  );
  if (!licenses.length && !(pkg.name === "react-remove-scroll-bar" && pkg.version === "2.3.8")) {
    throw new Error(`Review missing runtime license text: ${pkg.name}`);
  }
  sections.push(
    `\n${"=".repeat(72)}\n${pkg.name} ${pkg.version} / ${pkg.license ?? "See original text"}\n${"=".repeat(72)}`,
  );
  for (const filename of licenses)
    sections.push(await readFile(resolve(directory, filename), "utf-8"));
  if (!licenses.length) {
    sections.push(
      "Current upstream MIT notice retained for the declared MIT package; see third_party/README.md for the exact provenance and historical-file limitation.",
    );
    sections.push(
      await readFile(
        resolve(root, "..", "..", "third_party", "react-remove-scroll-bar-LICENSE.txt"),
        "utf-8",
      ),
    );
  }
}
await mkdir(resolve(root, "public"), { recursive: true });
await writeFile(
  resolve(root, "public", "THIRD-PARTY-NOTICES.txt"),
  sections.join("\n\n") + "\n",
  "utf-8",
);
console.log("Runtime dependency and font notices retained in public/THIRD-PARTY-NOTICES.txt");
