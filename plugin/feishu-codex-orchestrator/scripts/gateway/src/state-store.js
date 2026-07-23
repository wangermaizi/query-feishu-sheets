import fs from "node:fs/promises";
import path from "node:path";

const INITIAL_STATE = { version: 1, processed_events: {}, message_index: {}, tasks: {} };

function clone(value) {
  return structuredClone(value);
}

function validState(value) {
  return (
    value &&
    value.version === 1 &&
    typeof value.processed_events === "object" &&
    typeof value.message_index === "object" &&
    typeof value.tasks === "object"
  );
}

export class StateStore {
  constructor(file) {
    this.file = file;
    this.pending = Promise.resolve();
  }

  async read() {
    try {
      const value = JSON.parse(await fs.readFile(this.file, "utf8"));
      if (!validState(value)) throw new Error("状态结构无效");
      return value;
    } catch (error) {
      if (error?.code === "ENOENT") return clone(INITIAL_STATE);
      throw error;
    }
  }

  mutate(callback) {
    const operation = this.pending.then(async () => {
      const state = await this.read();
      const result = await callback(state);
      await this.write(state);
      return result;
    });
    this.pending = operation.catch(() => {});
    return operation;
  }

  async write(state) {
    await fs.mkdir(path.dirname(this.file), { recursive: true });
    const temporary = `${this.file}.${process.pid}.${Date.now()}.tmp`;
    await fs.writeFile(temporary, `${JSON.stringify(state, null, 2)}\n`, "utf8");
    await fs.rename(temporary, this.file);
  }

  async claimEvent(eventId) {
    return this.mutate((state) => {
      if (state.processed_events[eventId]) return false;
      state.processed_events[eventId] = new Date().toISOString();
      const entries = Object.entries(state.processed_events);
      if (entries.length > 2000) {
        entries
          .sort((left, right) => left[1].localeCompare(right[1]))
          .slice(0, entries.length - 2000)
          .forEach(([key]) => delete state.processed_events[key]);
      }
      return true;
    });
  }

  async createTask(task) {
    return this.mutate((state) => {
      if (state.tasks[task.id]) throw new Error(`任务已存在: ${task.id}`);
      state.tasks[task.id] = clone(task);
      state.message_index[task.source_message_id] = task.id;
      return clone(task);
    });
  }

  async updateTask(taskId, updates) {
    return this.mutate((state) => {
      const task = state.tasks[taskId];
      if (!task) throw new Error(`找不到任务: ${taskId}`);
      Object.assign(task, clone(updates), { updated_at: new Date().toISOString() });
      return clone(task);
    });
  }

  async bindMessage(taskId, messageId) {
    return this.mutate((state) => {
      const task = state.tasks[taskId];
      if (!task) throw new Error(`找不到任务: ${taskId}`);
      state.message_index[messageId] = taskId;
      task.last_bot_message_id = messageId;
      task.updated_at = new Date().toISOString();
      return clone(task);
    });
  }

  async findTaskByMessages(messageIds) {
    await this.pending;
    const state = await this.read();
    for (const messageId of messageIds) {
      const taskId = messageId && state.message_index[messageId];
      if (taskId && state.tasks[taskId]) return clone(state.tasks[taskId]);
    }
    return null;
  }

  async getTask(taskId) {
    await this.pending;
    const state = await this.read();
    return state.tasks[taskId] ? clone(state.tasks[taskId]) : null;
  }

  async listTasks() {
    await this.pending;
    const state = await this.read();
    return Object.values(state.tasks).map(clone);
  }

  async markInterruptedRuns() {
    return this.mutate((state) => {
      const interrupted = [];
      for (const task of Object.values(state.tasks)) {
        if (task.status === "running") {
          task.status = "interrupted";
          task.updated_at = new Date().toISOString();
          interrupted.push(clone(task));
        }
      }
      return interrupted;
    });
  }
}
