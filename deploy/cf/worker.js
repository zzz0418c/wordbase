/**
 * vocabcurve · Cloudflare Worker
 *
 * 规则（按你的要求）：
 *   - 只看 schedule.csv 里写的「下一篇的下次日期」，不再用记忆曲线推算
 *   - 日期 <= 今天 且还没更新日期 => 今天要背（漏了就自动顺延到第二天，直到你更新日期）
 *   - 每天北京时间 07:25（早间）/ 20:00（晚间复盘）各发一条
 */

const BASE = "https://raw.githubusercontent.com/zzz0418c/wordbase/main";
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

function head(day, icon, tail) {
  return `${icon} ${fmt(day)} 周${WEEK[new Date(day).getUTCDay()]} · ${tail}`;
}

function parseCsv(text) {
  const rows = [];
  for (const line of text.split(/\r?\n/)) {
    const row = line.trim();
    if (!row || row.startsWith("#")) continue;
    const parts = row.split(",");
    if (parts.length < 2) continue;
    const title = parts[0].trim();
    const value = parts[1].trim();
    if (!title || !value || title === "title") continue;
    rows.push({ title, value });
  }
  return rows;
}

/** 今天该背的：日期 <= 今天，且不是 done */
function dueToday(rows, today) {
  const out = [];
  for (const row of rows) {
    if (row.value === "done" || row.value === "完成") continue;
    const when = parseDay(row.value);
    if (Number.isFinite(when) && when <= today) out.push(row.title);
  }
  return out;
}

/** 明天该背的：日期正好是明天 */
function dueTomorrow(rows, today) {
  const tomorrow = today + DAY;
  const out = [];
  for (const row of rows) {
    if (row.value === "done" || row.value === "完成") continue;
    const when = parseDay(row.value);
    if (Number.isFinite(when) && when === tomorrow) out.push(row.title);
  }
  return out;
}

function morningText(rows, today) {
  const items = dueToday(rows, today);
  if (!items.length) return `${head(today, "📚", "今天没有复习任务")}\n（${rows.length} 篇在册）`;
  return [
    head(today, "📚", `今天 ${items.length} 项`),
    ...items.map((t) => `· ${t}`),
    `（${rows.length} 篇在册）`,
  ].join("\n");
}

function eveningText(rows, today) {
  const items = dueToday(rows, today);
  const tomorrow = dueTomorrow(rows, today);
  const lines = [head(today, "🌙", "今日复习")];
  if (items.length) {
    lines.push(`还有 ${items.length} 篇没更新日期：`);
    for (const t of items) lines.push(`⬜ ${t}`);
    lines.push("⚠️ 背完记得在笔记里把「下次」改成新日期");
  } else {
    lines.push("✅ 今天的都更新过了");
  }
  lines.push(tomorrow.length ? "📅 明天：" + tomorrow.join("、") : "📅 明天：没有安排");
  return lines.join("\n");
}

async function loadCsv() {
  const response = await fetch(`${BASE}/schedule.csv?t=${Date.now()}`, { cf: { cacheTtl: 0 } });
  if (!response.ok) throw new Error(`拉取 schedule.csv 失败：${response.status}`);
  return parseCsv(await response.text());
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
      const rows = await loadCsv();
      const today = todayCST();
      const text = evening ? eveningText(rows, today) : morningText(rows, today);
      const result = await push(env, text);
      record = { ...record, ok: true, text, result, rows: rows.length };
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
    const rows = await loadCsv();
    const day = url.searchParams.get("day") ? parseDay(url.searchParams.get("day")) : todayCST();
    const text =
      url.pathname === "/evening" ? eveningText(rows, day) : morningText(rows, day);
    if (url.pathname === "/send") {
      const result = await push(env, text);
      return new Response(`${text}\n\n${result}`, {
        headers: { "content-type": "text/plain; charset=utf-8" },
      });
    }
    return new Response(text, { headers: { "content-type": "text/plain; charset=utf-8" } });
  },
};
