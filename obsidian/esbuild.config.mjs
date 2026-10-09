import builtins from "builtin-modules";
import esbuild from "esbuild";

// Obsidian supplies these at runtime; bundling them would break the plugin.
await esbuild.build({
  entryPoints: ["src/main.ts"],
  bundle: true,
  external: ["obsidian", "electron", "@codemirror/*", "@lezer/*", ...builtins],
  format: "cjs",
  target: "es2020",
  outfile: "main.js",
  logLevel: "info",
});
