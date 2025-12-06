#!/usr/bin/env node
/**
 * Angular auto-fix agent:
 * - Reads failing test output (Jest or Karma).
 * - Attempts deterministic fixes (lint --fix, prettier).
 * - (Optional) Asks Azure OpenAI to propose a minimal unified diff.
 * - Applies patch, re-runs tests, iterates up to N times.
 * - Leaves changes staged for create-pull-request step.
 */

import { execSync, spawnSync } from "node:child_process";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import path from "node:path";
import process from "node:process";

// Optional AI (Azure OpenAI via openai SDK)
let OpenAI = null;
try {
  ({ default: OpenAI } = await import("openai"));
} catch (_) {}

function run(cmd, opts = {}) {
  console.log(`\n::group::RUN ${cmd}`);
  const res = spawnSync(cmd, { shell: true, stdio: "pipe", encoding: "utf-8", ...opts });
  if (res.stdout) process.stdout.write(res.stdout);
  if (res.stderr) process.stderr.write(res.stderr);
  console.log("::endgroup::");
  return { code: res.status ?? 0, stdout: res.stdout ?? "", stderr: res.stderr ?? "" };
}

function listRepoFiles(limit = 400) {
  const out = run("git ls-files", { }).stdout.trim().split("\n");
  return out.slice(0, limit).join("\n");
}

function readOrEmpty(p) {
  try { return readFileSync(p, "utf-8"); } catch { return ""; }
}

function detectAngularInfo() {
  const pkg = readOrEmpty("package.json");
  const angularJson = readOrEmpty("angular.json");
  const karmaConf = readOrEmpty("karma.conf.js") || readOrEmpty("karma.conf.ts");
  const jestConfig =
    readOrEmpty("jest.config.js") || readOrEmpty("jest.config.ts") || readOrEmpty("jest.preset.js");
  const isJest =
    jestConfig.includes("jest") || pkg.includes('"jest"') || pkg.includes("jest-preset-angular");
  return { pkg, angularJson, karmaConf, jestConfig, runner: isJest ? "jest" : "karma" };
}

function runTests(runner = "karma") {
  if (runner === "jest") {
    const r = run("npm test --silent -- --ci");
    return { log: r.stdout + "\n" + r.stderr, code: r.code };
  } else {
    // Prefer an existing CI script if present
    const hasCi = run("npm run | grep -q \"test:ci\"; echo $?", { }).stdout.trim() === "0";
    const cmd = hasCi
      ? "npm run test:ci"
      : "npx ng test --watch=false --browsers=ChromeHeadless --code-coverage=false";
    const r = run(cmd);
    return { log: r.stdout + "\n" + r.stderr, code: r.code };
  }
}

function applyPatch(diffText) {
  const patchPath = path.join(process.cwd(), "autofix.patch");
  writeFileSync(patchPath, diffText, "utf-8");
  const r = run(`git apply --index ${patchPath}`, { });
  return r.code === 0;
}

function hasChanges() {
  return run("git status --porcelain", {}).stdout.trim().length > 0;
}

function deterministicFixes(runner = "karma") {
  // 1) ESLint auto-fix
  if (existsSync("node_modules/.bin/eslint")) {
    run("npx eslint . --ext .ts,.js --fix || true");
  }
  // 2) Prettier
  if (existsSync("node_modules/.bin/prettier")) {
    run('npx prettier "**/*.{ts,js,html,scss,css,md,json}" --write || true');
  }
  // 3) For Jest snapshot projects (optional, conservative)
  if (runner === "jest") {
    // Only update snapshots if the failure explicitly mentions snapshots
    // You can relax this if your workflow prefers auto-update.
    // run("npm test -- -u || true");
  }
}

function buildPrompt(repoFiles, failingLog, info, runner) {
  return `
You are an automated Angular code-fix agent.

Goal:
- Read the failing ${runner.toUpperCase()} unit test output.
- Propose a minimal patch (unified diff) to make tests pass.
- Do not weaken tests unnecessarily; prefer fixing source where appropriate.
- Keep Angular, RxJS, and test idioms intact (e.g., TestBed, HttpTestingController, fakeAsync/tick).
- Respect existing coding style.

Constraints:
- Output ONLY a unified diff starting with 'diff --git'.
- The patch must apply cleanly with \`git apply --index\`.
- Avoid adding new dependencies without strong reason.
- For Jest, do not silently update snapshots; only adjust code unless messages show clear snapshot drift rationale.

Context:
- package.json (excerpt):
${info.pkg.slice(0, 2500)}

- angular.json (excerpt):
${info.angularJson.slice(0, 2500)}

- karma.conf (excerpt):
${info.karmaConf.slice(0, 1500)}

- jest config (excerpt):
${info.jestConfig.slice(0, 1500)}

- Repo files (truncated):
${repoFiles}

Failing test output:
${failingLog}
`.trim();
}

async function proposePatchWithAzure(prompt) {
  if (!OpenAI) return null;
  const endpoint = "https://openai-test-cinema.openai.azure.com/";
  const apiKey = "DDpB2gjNSrFjRRF1E1nvybxWc9jBnAZ77BY0ueaKHMbUuhzNVivxJQQJ99BLACYeBjFXJ3w3AAABACOGe0Pd";
  const deployment = "gpt-5-chat";
  const apiVersion = "2025-10-03";
  if (!(endpoint && apiKey && deployment)) return null;

    console.log('------------------------------------------------------');

  // openai@4 supports Azure via baseURL + api-version
//   const client = new OpenAI({
//     apiKey,
//     baseURL: `${endpoint}/openai/deployments/${deployment}`,
//     defaultQuery: { "api-version": apiVersion },
//     defaultHeaders: { "api-key": apiKey },
//   });

//   console.log('++++++++++++++++++++++++++++++++++++++++++++');

//   const resp = await client.chat.completions.create({
//     model: deployment,
//     temperature: 0.2,
//     max_tokens: 2000,
//     messages: [
//       { role: "system", content: "You generate minimal unified diffs that fix Angular tests." },
//       { role: "user", content: prompt },
//     ],
//   });
//   console.log('----------------------->>>>>>>>>>>>>>>>>>>>>>>>>>>>>');
//   const content = resp?.choices?.[0]?.message?.content || "";
//   if (content.includes("diff --git")) return content;
  return null;
}

async function main() {
  const args = process.argv.slice(2);
  const testOutputPath = args.includes("--test-output")
    ? args[args.indexOf("--test-output") + 1]
    : "test_output.txt";
  const maxIterations = args.includes("--max-iterations")
    ? parseInt(args[args.indexOf("--max-iterations") + 1], 10)
    : 1;
  const runnerArg = args.includes("--runner") ? args[args.indexOf("--runner") + 1] : null;

  const info = detectAngularInfo();
  const runner = runnerArg || info.runner;

  let failingLog = readOrEmpty(testOutputPath).trim();

  // If no log provided, run tests to capture
  if (!failingLog) {
    const r = runTests(runner);
    failingLog = r.log;
    if (r.code === 0) {
      console.log("Tests already pass; no fix required.");
      return 0;
    }
    writeFileSync("test_output.txt", failingLog, "utf-8");
  }

  // First pass: deterministic fixes
  deterministicFixes(runner);
  if (hasChanges()) {
    run("git add -A && git commit -m \"chore: lint/format before AI autofix\" || true");
  }

  // Test after deterministic fixes
  let { log, code } = runTests(runner);
  writeFileSync("post_deterministic_test_output.txt", log, "utf-8");
  if (code === 0) {
    console.log("Tests pass after deterministic fixes ✅");
    return 0;
  }

  // AI iterations
  for (let i = 0; i < maxIterations; i++) {
    console.log(`--- AI auto-fix iteration ${i + 1}/${maxIterations} ---`);
    const repoFiles = listRepoFiles(400);
    console.log('------ ENTER --------------');
    const prompt = buildPrompt(repoFiles, log || failingLog, info, runner);
    const diff = await proposePatchWithAzure(prompt);

    if (!diff) {
      console.log("No AI patch produced; stopping.");
      break;
    }

    console.log(diff.slice(0, 1000) + "\n...\n");

    const ok = applyPatch(diff);
    if (!ok) {
      console.log("Patch failed to apply; stopping.");
      break;
    }

    // Re-test
    const r2 = runTests(runner);
    writeFileSync("post_fix_test_output.txt", r2.log, "utf-8");
    if (r2.code === 0) {
      console.log("Tests pass after AI auto-fix ✅");
      return 0;
    }
    log = r2.log;
  }

  // Leave changes (if any) for PR creation step
  if (hasChanges()) {
    console.log("Changes proposed though tests still failing. Raising PR for review.");
    return 0;
  }

  console.log("No changes to propose.");
  return 0;
}

main().then(
  () => process.exit(0),
  (e) => {
    console.error(e);
    process.exit(0); // do not fail the job; let PR step decide
  }
);
