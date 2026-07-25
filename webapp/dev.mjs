#!/usr/bin/env node
/**
 * 一键起前后端：Flask(127.0.0.1:8787) + Vite dev server。
 * CLI 参数（--port / --host 等）原样透传给 vite。
 * 退出时（Ctrl+C / 信号）同时回收两个子进程，不留后台残留。
 */
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.dirname(fileURLToPath(import.meta.url));
const passthrough = process.argv.slice(2);

const procs = [];
function run(name, cmd, args, opts = {}) {
  const child = spawn(cmd, args, {
    cwd: root,
    stdio: "inherit",
    env: { ...process.env },
    ...opts,
  });
  child.on("error", (err) => {
    console.error(`[dev] ${name} 启动失败: ${err.message}`);
    shutdown(1);
  });
  procs.push(child);
  return child;
}

// Flask 后端（项目自带依赖，系统 python3 即可）
run("flask", "python3", [path.join("server", "app.py")]);
// Vite 前端
run("vite", "npx", ["vite", ...passthrough]);

let shuttingDown = false;
function shutdown(code = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const p of procs) {
    try { p.kill("SIGTERM"); } catch { /* already dead */ }
  }
  setTimeout(() => process.exit(code), 300).unref();
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));
for (const p of procs) {
  p.on("exit", (code) => {
    if (!shuttingDown && code !== 0 && code !== null) shutdown(code);
  });
}
