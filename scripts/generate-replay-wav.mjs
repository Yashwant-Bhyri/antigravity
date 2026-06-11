#!/usr/bin/env node

import { existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const output = resolve(process.argv[2] || "/tmp/antigravity_replay_answer.wav");
const text = process.argv.slice(3).join(" ").trim()
  || "I would start by defining the denominator, checking whether the cohort was comparable, and separating product changes from support or acquisition mix before trusting the result.";

function hasCommand(command) {
  const result = spawnSync("which", [command], { encoding: "utf-8" });
  return result.status === 0;
}

if (!hasCommand("say") || !hasCommand("afconvert")) {
  console.error("WAV fixture generation requires macOS say and afconvert. Manual replay remains available.");
  process.exit(2);
}

mkdirSync(dirname(output), { recursive: true });
const aiff = output.replace(/\.wav$/i, ".aiff");
const say = spawnSync("say", ["-o", aiff, text], { stdio: "inherit" });
if (say.status !== 0 || !existsSync(aiff)) {
  console.error("Could not generate AIFF speech fixture.");
  process.exit(say.status || 1);
}

const convert = spawnSync("afconvert", ["-f", "WAVE", "-d", "LEI16@16000", aiff, output], { stdio: "inherit" });
if (convert.status !== 0 || !existsSync(output)) {
  console.error("Could not convert speech fixture to WAV.");
  process.exit(convert.status || 1);
}

console.log(output);
