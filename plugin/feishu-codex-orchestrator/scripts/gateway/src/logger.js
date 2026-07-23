import fs from "node:fs";
import path from "node:path";

const MAX_LOG_BYTES = 5 * 1024 * 1024;

function sanitize(value) {
  return String(value)
    .replace(/(app[_-]?secret["'\s:=]+)[^\s,"'}]+/gi, "$1[REDACTED]")
    .replace(/(authorization["'\s:=]+bearer\s+)[^\s,"'}]+/gi, "$1[REDACTED]")
    .replace(/(access[_-]?token["'\s:=]+)[^\s,"'}]+/gi, "$1[REDACTED]");
}

export class Logger {
  constructor(file) {
    this.file = file;
    fs.mkdirSync(path.dirname(file), { recursive: true });
  }

  rotate() {
    try {
      if (fs.statSync(this.file).size < MAX_LOG_BYTES) return;
      const backup = `${this.file}.1`;
      if (fs.existsSync(backup)) fs.rmSync(backup, { force: true });
      fs.renameSync(this.file, backup);
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
  }

  write(level, message, details) {
    this.rotate();
    const suffix = details === undefined ? "" : ` ${sanitize(JSON.stringify(details))}`;
    const line = `${new Date().toISOString()} ${level.toUpperCase()} ${sanitize(message)}${suffix}\n`;
    fs.appendFileSync(this.file, line, "utf8");
    if (level === "error") process.stderr.write(line);
  }

  info(message, details) {
    this.write("info", message, details);
  }

  warn(message, details) {
    this.write("warn", message, details);
  }

  error(message, details) {
    this.write("error", message, details);
  }
}
