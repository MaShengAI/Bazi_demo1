import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const dist = fileURLToPath(new URL("../dist/", import.meta.url));
const forbidden = [
  { pattern: /https?:\/\/(?:localhost|127\.0\.0\.1)/i, label: "localhost 地址" },
  { pattern: /BAZI_LLM_API_KEY|BAZI_DATABASE_URL/i, label: "后端敏感环境变量名" },
];

let failed = false;
for (const file of walk(dist)) {
  if (!/\.(?:html|js|css|json|map)$/.test(file)) continue;
  const content = readFileSync(file, "utf8");
  for (const rule of forbidden) {
    if (!rule.pattern.test(content)) continue;
    console.error(`生产构建包含${rule.label}: ${relative(dist, file)}`);
    failed = true;
  }
}

if (failed) process.exit(1);
console.log("生产构建检查通过：同源 API，无 localhost 或后端秘密配置。");

function* walk(directory) {
  for (const name of readdirSync(directory)) {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) yield* walk(path);
    else yield path;
  }
}
