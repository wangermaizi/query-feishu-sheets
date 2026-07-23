import fs from "node:fs";

import * as lark from "@larksuiteoapi/node-sdk";

function responseData(response, operation) {
  if (response?.code && response.code !== 0) {
    throw new Error(`${operation}失败 ${response.code}: ${response.msg || "unknown error"}`);
  }
  return response?.data || {};
}

export class FeishuTransport {
  constructor(config, logger) {
    this.config = config;
    this.logger = logger;
    this.client = new lark.Client({
      appId: config.appId,
      appSecret: config.appSecret,
      appType: lark.AppType.SelfBuild,
      domain: lark.Domain.Feishu,
      loggerLevel: lark.LoggerLevel.error,
      source: "feishu-codex-gateway",
    });
    this.wsClient = null;
  }

  writeStatus(state, details = {}) {
    const payload = {
      state,
      pid: process.pid,
      updated_at: new Date().toISOString(),
      ...details,
    };
    fs.writeFileSync(this.config.statusFile, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  }

  start(onMessage) {
    const eventDispatcher = new lark.EventDispatcher({
      loggerLevel: lark.LoggerLevel.error,
    }).register({
      "im.message.receive_v1": async (event) => {
        await onMessage(event);
      },
    });
    this.wsClient = new lark.WSClient({
      appId: this.config.appId,
      appSecret: this.config.appSecret,
      domain: lark.Domain.Feishu,
      loggerLevel: lark.LoggerLevel.error,
      autoReconnect: true,
      handshakeTimeoutMs: 30000,
      wsConfig: { pingTimeout: 10 },
      source: "feishu-codex-gateway",
      onReady: () => {
        this.logger.info("飞书长连接已建立");
        this.writeStatus("connected");
      },
      onReconnecting: () => {
        this.logger.warn("飞书长连接正在重连");
        this.writeStatus("reconnecting");
      },
      onReconnected: () => {
        this.logger.info("飞书长连接已恢复");
        this.writeStatus("connected");
      },
      onError: (error) => {
        this.logger.error("飞书长连接失败", { message: error.message });
        this.writeStatus("failed", { error: error.message });
      },
    });
    this.writeStatus("connecting");
    void this.wsClient.start({ eventDispatcher });
  }

  close() {
    this.wsClient?.close();
    this.writeStatus("stopped");
  }

  async replyCard(messageId, card) {
    const response = await this.client.im.v1.message.reply({
      path: { message_id: messageId },
      data: {
        msg_type: "interactive",
        content: JSON.stringify(card),
        reply_in_thread: false,
        uuid: crypto.randomUUID(),
      },
    });
    const data = responseData(response, "回复飞书消息");
    if (!data.message_id) throw new Error("飞书回复响应缺少 message_id");
    return data.message_id;
  }
}
