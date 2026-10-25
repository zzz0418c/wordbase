/**
 * vocabcurve · Cloudflare Worker
 *
 * 每天北京时间 07:25 / 20:00 触发：
 *   1. 拉公开仓库里的 book.json（进度）和 schedule.csv（人工校准的「下次复习日」）
 *   2. schedule.csv 里写了的篇目，以它为准；没写的才按 1/2/4/7/15/30 推
 *   3. 推送到企业微信群机器人
 */

const BASE = "https://raw.githubusercontent.com/zzz0418c/wordbase/main";
const OFFSETS = [1, 3, 6, 14, 29]; // 第 2/4/7/15/30 天
const ROUNDS = OFFSETS.length;

const WEEK = "日一二三四五六";
const DAY = 86400000;

function todayCST() {
  const shifted = new Date(Date.now() + 8 * 3600 * 1000);
  return Date.UTC(shifted.getUTCFullYear(), shifted.getUTCMonth(), shifted.getUTCDate());
}

function parseDay(text) {
  const [y, m, d] = String(text).trim().split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

function fmt(ts) {
  const d = new Date(ts);
  return `${d.getUTCMonth() + 1}月${d.getUTCDate()}日`;
}

function doneRounds(list) {
  const done = list.done || {};
  return Array.from({ length: ROUNDS + 1 }, (_, r) => String(r))
    .filter((k) => k in done)
    .map(Number);
}

function nextRound(list) {
  const done = new Set(doneRounds(list).map(String));
  for (let r = 0; r <= ROUNDS; r += 1) if (!done.has(String(r))) return r;
  return null;
}

/** 这一篇每一轮的日期；schedule.csv 有覆盖就把覆盖值当锚点 */
function dues(list, override) {
  const start = parseDay(list.start);
  const r = nextRound(list);
  let base = start;
  if (override && override !== "done" && r !== null) {
    const back = r === 0 ? 0 : OFFSETS[r - 1];
    base = parseDay(override) - back * DAY;
  }
  const out = [];
  for (let i = 0; i <= ROUNDS; i += 1) out.push(i === 0 ? base : base + OFFSETS[i - 1] * DAY);
  return out;
}

function isFinished(list, override) {
  if (override === "done") return true;
  return nextRound(list) === null;
}

function itemsOn(book, overrides, day) {
  const out = [];
  for (const list of book.lists || []) {
    const override = overrides[list.title.trim()];
    if (!list.start || isFinished(list, override)) continue;
    const dates = dues(list, override);
    if (day > dates[ROUNDS]) continue;
    const done = new Set(doneRounds(list).map(String));
    for (let r = 0; r <= ROUNDS; r += 1) {
      if (done.has(String(r))) continue;
      if (dates[r] === day) out.push({ title: list.title, round: r });
    }
  }
  return out;
}

function doneOn(book, day) {
  let count = 0;
  for (const list of book.lists || []) {
    for (const stamp of Object.values(list.done || {})) {
      const ts = Date.parse(stamp);
      if (!Number.isFinite(ts)) continue;
      const shifted = new Date(ts + 8 * 3600 * 1000);
      const d = Date.UTC(shifted.getUTCFullYear(), shifted.getUTCMonth(), shifted.getUTCDate());
      if (d === day) count += 1;
    }
  }
  return count;
}

function head(day, icon, tail) {
  return `${icon} ${fmt(day)} 周${WEEK[new Date(day).getUTCDay()]} · ${tail}`;
}

function morningText(book, overrides, today) {
  const items = itemsOn(book, overrides, today);
  const lines = [];
  if (items.length) {
    lines.push(head(today, "📚", `今天 ${items.length} 项`));
    for (const item of items) lines.push(`· ${item.title}`);
  } else {
    lines.push(head(today, "📚", "今天没有复习任务"));
  }
  lines.push(`（${(book.lists || []).length} 篇在册）`);
  return lines.join("\n");
}

function eveningText(book, overrides, today) {
  const items = itemsOn(book, overrides, today);
  const done = doneOn(book, today);
  const lines = [head(today, "🌙", "今日复习")];
  lines.push(`今天记上了 ${done} 项，今天该做 ${items.length + done} 项`);
  for (const item of items) lines.push(`⬜ ${item.title}`);
  lines.push(items.length ? "⚠️ 有遗漏，睡前补一下" : "✅ 今天的都完成了");
  const tomorrow = itemsOn(book, overrides, today + DAY);
  lines.push(tomorrow.length ? "📅 明天：" + tomorrow.map((x) => x.title).join("、") : "📅 明天：没有安排");
  return lines.join("\n");
}

function parseCsv(text) {
  const map = {};
  for (const line of text.split(/\r?\n/)) {
    const row = line.trim();
    if (!row || row.startsWith("#")) continue;
    const parts = row.split(",");
    if (parts.length < 2) continue;
    const title = parts[0].trim();
    const value = parts[1].trim();
    if (!title || !value || title === "title") continue;
    map[title] = value === "done" || value === "完成" ? "done" : value;
  }
  return map;
}

async function loadJson(path) {
  const response = await fetch(`${BASE}/${path}?t=${Date.now()}`, { cf: { cacheTtl: 0 } });
  if (!response.ok) throw new Error(`拉取 ${path} 失败：${response.status}`);
  return response.json();
}

async function loadOverrides() {
  try {
    const response = await fetch(`${BASE}/schedule.csv?t=${Date.now()}`, { cf: { cacheTtl: 0 } });
    if (!response.ok) return {};
    return parseCsv(await response.text());
  } catch (e) {
    return {};
  }
}

async function push(env, text) {
  if (!env.WECOM_WEBHOOK) throw new Error("没有配置 WECOM_WEBHOOK");
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
    const started = new Date().toISOString();
    const evening = event.cron === "0 12 * * *";
    let record = { started, cron: event.cron, evening };
    try {
      const [book, overrides] = await Promise.all([loadJson("book.json"), loadOverrides()]);
      const today = todayCST();
      const text = evening
        ? eveningText(book, overrides, today)
        : morningText(book, overrides, today);
      const result = await push(env, text);
      record = { ...record, ok: true, text, result, override_count: Object.keys(overrides).length };
      console.log(`[${event.cron}]`, text, result);
    } catch (error) {
      record = { ...record, ok: false, error: String(error && error.stack ? error.stack : error) };
      console.log("FAILED", record.error);
    }
    if (env.LOG) {
      try {
        await env.LOG.put("last_run", JSON.stringify(record));
      } catch (e) {
        /* ignore */
      }
    }
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    const [book, overrides] = await Promise.all([loadJson("book.json"), loadOverrides()]);
    const day = url.searchParams.get("day") ? parseDay(url.searchParams.get("day")) : todayCST();
    const text =
      url.pathname === "/evening"
        ? eveningText(book, overrides, day)
        : morningText(book, overrides, day);
    if (url.pathname === "/send") {
      const result = await push(env, text);
      return new Response(`${text}\n\n${result}`, {
        headers: { "content-type": "text/plain; charset=utf-8" },
      });
    }
    return new Response(text, { headers: { "content-type": "text/plain; charset=utf-8" } });
  },
};
