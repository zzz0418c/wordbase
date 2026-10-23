/**
 * vocabcurve · Cloudflare Worker
 *
 * 每天两次（北京时间 07:25 / 20:00）由 Cron Trigger 触发：
 *   1. 从公开仓库拉最新 book.json
 *   2. 按「第 1 天 = 首学，之后第 2/4/7/15/30 天复习」算出今天该做什么
 *   3. 推到企业微信群机器人
 *
 * 不需要 KV、不需要 GitHub token：仓库是公开的，直接读 raw 文件。
 */

const RAW = "https://raw.githubusercontent.com/zzz0418c/wordbase/main/book.json";
const OFFSETS = [1, 3, 6, 14, 29]; // 第 2/4/7/15/30 天相对首学的偏移
const ROUNDS = OFFSETS.length; // 5 次复习 + 首学

const WEEK = "日一二三四五六";
const DAY = 86400000;

function todayCST() {
  const shifted = new Date(Date.now() + 8 * 3600 * 1000);
  return Date.UTC(shifted.getUTCFullYear(), shifted.getUTCMonth(), shifted.getUTCDate());
}

function parseDay(text) {
  const [y, m, d] = String(text).split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

function fmt(ts) {
  const d = new Date(ts);
  return `${d.getUTCMonth() + 1}月${d.getUTCDate()}日`;
}

function dueOf(list, round) {
  const start = parseDay(list.start);
  return round === 0 ? start : start + OFFSETS[round - 1] * DAY;
}

function pending(list) {
  const done = list.done || {};
  const out = [];
  for (let r = 0; r <= ROUNDS; r += 1) {
    if (String(r) in done) continue;
    out.push({ round: r, due: dueOf(list, r) });
  }
  return out;
}

function finished(list) {
  const done = list.done || {};
  return Array.from({ length: ROUNDS + 1 }, (_, r) => String(r)).every((k) => k in done);
}

function itemsOn(book, day) {
  const out = [];
  for (const list of book.lists || []) {
    if (!list.start || finished(list)) continue;
    if (day > dueOf(list, ROUNDS)) continue;
    for (const item of pending(list)) {
      if (item.due === day) out.push({ title: list.title, round: item.round });
    }
  }
  return out;
}

function doneOn(book, day) {
  let count = 0;
  for (const list of book.lists || []) {
    for (const stamp of Object.values(list.done || {})) {
      const ts = Date.parse(stamp);
      if (Number.isFinite(ts)) {
        const shifted = new Date(ts + 8 * 3600 * 1000);
        const d = Date.UTC(shifted.getUTCFullYear(), shifted.getUTCMonth(), shifted.getUTCDate());
        if (d === day) count += 1;
      }
    }
  }
  return count;
}

function head(book, day, icon, tail) {
  const d = new Date(day);
  return `${icon} ${fmt(day)} 周${WEEK[d.getUTCDay()]} · ${tail}`;
}

function morningText(book, today) {
  const items = itemsOn(book, today);
  const lines = [];
  if (items.length) {
    lines.push(head(book, today, "📚", `今天 ${items.length} 项`));
    for (const item of items) lines.push(`· ${item.title}`);
  } else {
    lines.push(head(book, today, "📚", "今天没有复习任务"));
  }
  lines.push(`（${(book.lists || []).length} 篇在册）`);
  return lines.join("\n");
}

function eveningText(book, today) {
  const items = itemsOn(book, today);
  const done = doneOn(book, today);
  const lines = [head(book, today, "🌙", "今日复习")];
  lines.push(`今天记上了 ${done} 项，今天该做 ${items.length + done} 项`);
  for (const item of items) lines.push(`⬜ ${item.title}`);
  lines.push(items.length ? "⚠️ 有遗漏，睡前补一下" : "✅ 今天的都完成了");
  const tomorrow = itemsOn(book, today + DAY);
  lines.push(tomorrow.length ? "📅 明天：" + tomorrow.map((x) => x.title).join("、") : "📅 明天：没有安排");
  return lines.join("\n");
}

async function loadBook() {
  const response = await fetch(`${RAW}?t=${Date.now()}`, { cf: { cacheTtl: 0 } });
  if (!response.ok) throw new Error(`拉取 book.json 失败：${response.status}`);
  return response.json();
}

async function push(env, text) {
  if (!env.WECOM_WEBHOOK) throw new Error("没有配置 WECOM_WEBHOOK 环境变量");
  const response = await fetch(env.WECOM_WEBHOOK, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ msgtype: "text", text: { content: text } }),
  });
  const body = await response.text();
  if (!body.includes('"errcode":0')) throw new Error(`企业微信返回：${body}`);
  return body;
}

export default {
  async scheduled(event, env, ctx) {
    const book = await loadBook();
    const today = todayCST();
    const evening = event.cron === "0 12 * * *";
    const text = evening ? eveningText(book, today) : morningText(book, today);
    const result = await push(env, text);
    console.log(`[${event.cron}]`, text, result);
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    const book = await loadBook();
    const day = url.searchParams.get("day") ? parseDay(url.searchParams.get("day")) : todayCST();
    const text = url.pathname === "/evening" ? eveningText(book, day) : morningText(book, day);
    if (url.pathname === "/send") {
      const result = await push(env, text);
      return new Response(`${text}\n\n${result}`, { headers: { "content-type": "text/plain; charset=utf-8" } });
    }
    return new Response(text, { headers: { "content-type": "text/plain; charset=utf-8" } });
  },
};
