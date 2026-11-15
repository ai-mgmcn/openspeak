"use strict";
/* OpenSpeak front end. No framework, no build step: this file is the whole app. */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) el.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k != null) el.append(k.nodeType ? k : document.createTextNode(k));
  return el;
};

/* ---------------------------------------------------------------- strings */

const I18N = {
  en: {
    heroTitle: "What do you want to practise today?", heroSub: "Just talk. Mistakes are noted silently and reviewed after.",
    start: "Start", send: "Send", end: "Finish · Get report", newSession: "← New session", markdown: "Markdown", savePdf: "Save as PDF",
    settings: "Settings", history: "History", newChat: "New session", more: "More", viewReport: "View report",
    when: { today: "Today", yesterday: "Yesterday", earlier: "Earlier" }, done: "Done", next: "Next",
    welcome: "Welcome! Three quick steps: languages, AI service, voice. You can change everything later.",
    tabLang: "Languages", tabAi: "AI service", tabVoice: "Voice",
    target: "I want to practise", native: "My first language (for hints)", reportLang: "Write feedback & reports in",
    otherPh: "Type any language, e.g. Swiss German", other: "Other…",
    replyMode: "How the partner replies", level: "My level", uiLang: "Interface language",
    modes: { immersive: ["Immersive", "Only the practice language"], translate: ["With translation", "Each reply also shown in your language"], rescue: ["Hint when stuck", "A hint in your language only when you're stuck"] },
    levels: { beginner: "Beginner", intermediate: "Intermediate", advanced: "Advanced" },
    provider: "Service", chatModel: "Conversation model", graderModel: "Grading model", sameAsChat: "Same as conversation",
    graderNote: "Grading needs accuracy more than speed. Small local models (7–8B) miss mistakes; 14B+ or a cloud model is recommended here.",
    gradeWhen: "When to grade", later: "graded when you finish",
    whens: { auto: ["Automatic", "Local model: after the session. Cloud: live."], live: ["During the talk", "See progress as you go"], after: ["After the session", "Fastest replies; the report takes longer"] },
    noKey: "No key saved for this service yet", keysNote: "Each key is only sent to its own service.", customProvider: "Custom", clearKey: "Clear", fromEnv: "from OPENSPEAK_API_KEY", endpoints: "Your services", otherEndpoint: "— another service —",
    refresh: "Refresh", test: "Test connection", testing: "Testing…", testOk: "Connected ✓",
    stt: "Speech recognition", sttModel: "Local model", sttApiModel: "Transcription model",
    sttEngines: { local: ["On this device", "Free, offline (faster-whisper)"], api: ["Via API", "Uses your AI service's /audio/transcriptions"] },
    sttMissing: 'Local recognition isn\'t installed yet. In the OpenSpeak folder run:  uv tool install ".[local]"  (or pip install ".[local]"), then restart.',
    pause: "Pause that ends your turn", tts: "Partner's voice",
    ttsEngines: { browser: ["Browser voice", "Free, offline, nothing to install"], api: ["Via API", "OpenAI-compatible /audio/speech"], off: ["Off", "Text only"] },
    voice: "Voice", ttsApi: "Model / voice", rate: "Speaking speed", hear: "▶ Hear a sample",
    local: "local", cloud: "cloud",
    detected: (n, m) => `Found ${n} running on this computer (${m} models).`, use: "Use it",
    noLocal: "No local model server found. If you have Ollama or LM Studio, start it (LM Studio: Developer → Start Server) and reopen this tab.",
    noVoice: "Your system has no voice for this language, so replies will be text only. Install one in system settings, or use API voice.",
    pillTarget: "Practising", pillReport: "Feedback",
    pillTip: (t, n, r) => `You're practising ${t}. Hints are in ${n}; corrections and reports in ${r}. Click to change.`,
    customLang: "Custom language: works for conversation and grading; speech recognition auto-detects.",
    smallModel: "For this language, the “small” local model or larger recognises much better.",
    entries: { free: "Free talk", scenes: "Scenes", custom: "Custom" },
    cats: { travel: "Travel", daily: "Daily life", business: "Business" },
    freeTitle: "Free conversation", freeSub: "Talk about anything — your day, work, plans.",
    customPh: "Describe a scene, e.g. You're my landlord and the heating is broken. Start by asking what's wrong.",
    hard: "Hard", tryUse: "Try to use:",
    st: { idle: "Mic off — tap it to talk, or hold space", listening: "Listening…", hearing: "Go on — I'm listening", transcribing: "Got it…", thinking: "Thinking…", speaking: "Speaking…", ptt: "Release space to send" },
    paused: "Practice paused", typePh: "Type what you want to say…", baseUrl: "Base URL", apiKey: "API key", auto: "Auto", nModels: (n) => `${n} models`,
    sendNow: "Send now", skip: "Skip", mic: "Microphone on/off", keyboard: "Type instead", close: "Close", cantSave: "Couldn't save:",
    graded: (a, b) => `graded ${a}/${b}`, notHeard: "Didn't catch that — try again.",
    micDenied: "Microphone blocked. Allow it in the browser, or type instead.",
    preparing: "Setting the scene…",
    helpHint: "Hint", tapToHear: "tap to hear", saved: "Saved",
    noHistory: "No sessions yet.", nTurns: (n) => `${n} ${n === 1 ? "turn" : "turns"}`, nMistakes: (n) => `${n} ${n === 1 ? "mistake" : "mistakes"}`, incomplete: "incomplete", live: "in progress", current: "this session",
    repair: "Complete it", del: "Delete", confirmDel: "Delete this session and its report?",
    needSetup: "Choose an AI service and model first.",
    online: "online", onlineWarn: "This is an online voice: everything the partner says is sent to the browser maker (Google or Microsoft) to be spoken. Use it anyway?",
    noLocalVoice: "No offline voice for this language, so replies are text only. Download one in System Settings → Accessibility → Spoken Content, or pick an online voice below.",
    resume: "Continue", lastUnfinished: "Your last session didn't end.", writeReport: "Write the report", dismiss: "Dismiss",
    takeOver: "This session is open in another tab. Continue it here instead?", elsewhere: "This session was continued in another tab.",
    working: "writing report", notEnded: "not ended", backToTalk: "← Back to the conversation",
    job: { queued: "Waiting…", grading: (a, b) => `Grading ${a}/${b}`, writing: "Writing the summary…", ready: "Report ready", failed: "Failed", empty: "Nothing was said, so there's no report." },
    view: "View", nothingToAdd: "Nothing left to complete.", stillMissing: (n) => `${n} line(s) still couldn't be graded.`,
  },
  zh: {
    heroTitle: "今天想练什么？", heroSub: "只管开口说。错误会被悄悄记下，结束后一起复盘。",
    start: "开始", send: "发送", end: "结束 · 生成报告", newSession: "← 新的练习", markdown: "Markdown", savePdf: "保存为 PDF",
    settings: "设置", history: "历史", newChat: "新练习", more: "更多", viewReport: "查看报告",
    when: { today: "今天", yesterday: "昨天", earlier: "更早" }, done: "完成", next: "下一步",
    welcome: "欢迎！三步设置：语言 → AI 服务 → 语音。之后随时可以改。",
    tabLang: "语言", tabAi: "AI 服务", tabVoice: "语音",
    target: "我要练的语言", native: "我的母语（用于提示）", reportLang: "批改和报告用什么语言写",
    otherPh: "输入任意语言，比如 粤语、瑞士德语", other: "其他…",
    replyMode: "陪练怎么回复", level: "我的水平", uiLang: "界面语言",
    modes: { immersive: ["沉浸", "只用练习语言"], translate: ["附翻译", "每句回复下方显示母语翻译"], rescue: ["卡住时提示", "只有你卡住时才给母语提示"] },
    levels: { beginner: "入门", intermediate: "中级", advanced: "高级" },
    provider: "服务", chatModel: "对话模型", graderModel: "批改模型", sameAsChat: "与对话模型相同",
    gradeWhen: "什么时候批改", later: "结束后统一批改",
    whens: { auto: ["自动", "本地模型结束后批，云端边聊边批"], live: ["边聊边批", "随时看到批改进度"], after: ["结束后批改", "回复最快，报告生成会久一些"] },
    graderNote: "批改更看重准确，不看重速度。本地 7–8B 小模型容易漏错，这里建议用 14B 以上或云端模型。",
    noKey: "这个服务还没有保存 key", keysNote: "每个 key 只发给它自己的服务。", customProvider: "自定义", clearKey: "清除", fromEnv: "来自 OPENSPEAK_API_KEY", endpoints: "已注册的服务", otherEndpoint: "— 其他服务 —",
    refresh: "刷新", test: "测试连接", testing: "测试中…", testOk: "连接成功 ✓",
    stt: "语音识别", sttModel: "本地模型", sttApiModel: "转写模型",
    sttEngines: { local: ["本机识别", "免费、离线（faster-whisper）"], api: ["接口识别", "调用 AI 服务的 /audio/transcriptions"] },
    sttMissing: '本地识别还没安装。在 OpenSpeak 项目目录里运行：uv tool install ".[local]"（或 pip install ".[local]"），然后重启。',
    pause: "停顿多久算说完", tts: "陪练的声音",
    ttsEngines: { browser: ["浏览器语音", "免费、离线、无需安装"], api: ["接口语音", "OpenAI 兼容的 /audio/speech"], off: ["关闭", "只显示文字"] },
    voice: "声音", ttsApi: "模型 / 声音", rate: "语速", hear: "▶ 试听",
    local: "本地", cloud: "云端",
    detected: (n, m) => `检测到本机正在运行 ${n}（${m} 个模型）。`, use: "使用",
    noLocal: "没检测到本地模型服务。装了 Ollama 或 LM Studio 的话，先启动它（LM Studio：Developer → Start Server），再回到这里。",
    noVoice: "系统里没有这个语言的朗读声音，陪练回复将只显示文字。可以在系统设置里下载声音，或改用接口语音。",
    pillTarget: "练习", pillReport: "反馈",
    pillTip: (t, n, r) => `你在练习${t}。提示用${n}，批改和报告用${r}。点击可修改。`,
    customLang: "自定义语言：对话和批改都能用，语音识别会自动检测语言。",
    smallModel: "这个语言建议把本地识别模型调到 small 或更大，准确率会明显提高。",
    entries: { free: "自由聊", scenes: "情景练习", custom: "自定义" },
    cats: { travel: "旅行", daily: "日常", business: "商务" },
    freeTitle: "自由对话", freeSub: "想聊什么聊什么：今天、工作、计划。",
    customPh: "描述一个场景，比如：你是我的房东，暖气坏了。你先问我怎么了。（用任何语言写都行）",
    hard: "加难", tryUse: "试着用上：",
    st: { idle: "麦克风已关 — 点它开始说，或按住空格", listening: "在听…", hearing: "继续说，我在听", transcribing: "收到…", thinking: "思考中…", speaking: "说话中…", ptt: "松开空格发送" },
    paused: "练习已暂停", typePh: "输入你想说的话…", baseUrl: "接口地址", apiKey: "API 密钥", auto: "自动", nModels: (n) => `${n} 个模型`,
    sendNow: "现在发送", skip: "跳过", mic: "开关麦克风", keyboard: "打字输入", close: "关闭", cantSave: "没能保存：",
    graded: (a, b) => `已批改 ${a}/${b}`, notHeard: "没听清，再说一次吧。",
    micDenied: "麦克风被拦截了。请在浏览器里允许，或者改用打字。",
    preparing: "正在布置场景…",
    helpHint: "提示", tapToHear: "点击试听", saved: "已保存",
    noHistory: "还没有练习记录。", nTurns: (n) => `${n} 句`, nMistakes: (n) => `${n} 处错误`, incomplete: "未完成", live: "进行中", current: "当前练习",
    repair: "补全报告", del: "删除", confirmDel: "删除这次练习和报告？",
    needSetup: "请先选择 AI 服务和模型。",
    online: "联网", onlineWarn: "这是联网声音：陪练说的每句话都会发给浏览器厂商（Google 或微软）来朗读。仍然使用？",
    noLocalVoice: "这个语言没有离线声音，回复只显示文字。可以在「系统设置 → 辅助功能 → 朗读内容」下载，或在下面选一个联网声音。",
    resume: "继续对话", lastUnfinished: "上次的练习还没结束。", writeReport: "生成报告", dismiss: "忽略",
    takeOver: "这个练习正在另一个标签页里打开。改在这里继续吗？", elsewhere: "这个练习已在另一个标签页继续。",
    working: "生成报告中", notEnded: "未结束", backToTalk: "← 回到对话",
    job: { queued: "排队中…", grading: (a, b) => `批改中 ${a}/${b}`, writing: "正在写总结…", ready: "报告好了", failed: "失败", empty: "这次没有说话，不生成报告。" },
    view: "查看", nothingToAdd: "没有需要补全的内容。", stillMissing: (n) => `还有 ${n} 句没能批改。`,
  },
  ja: {
    heroTitle: "今日は何を練習しますか？", heroSub: "とにかく話すだけ。間違いは静かに記録され、あとで振り返れます。",
    start: "開始", send: "送信", end: "終了 · レポート作成", newSession: "← 新しい練習", markdown: "Markdown", savePdf: "PDFで保存",
    settings: "設定", history: "履歴", newChat: "新しい練習", more: "その他", viewReport: "レポートを見る",
    when: { today: "今日", yesterday: "昨日", earlier: "それ以前" }, done: "完了", next: "次へ",
    welcome: "ようこそ！言語 → AIサービス → 音声 の3ステップです。あとから変更できます。",
    tabLang: "言語", tabAi: "AIサービス", tabVoice: "音声",
    target: "練習する言語", native: "母語（ヒント用）", reportLang: "フィードバックとレポートの言語",
    otherPh: "任意の言語を入力", other: "その他…",
    replyMode: "相手の返答スタイル", level: "レベル", uiLang: "表示言語",
    modes: { immersive: ["没入", "練習言語のみ"], translate: ["翻訳つき", "返答ごとに母語訳を表示"], rescue: ["詰まったらヒント", "詰まったときだけ母語でヒント"] },
    levels: { beginner: "初級", intermediate: "中級", advanced: "上級" },
    provider: "サービス", chatModel: "会話モデル", graderModel: "採点モデル", sameAsChat: "会話モデルと同じ",
    gradeWhen: "採点のタイミング", later: "終了後にまとめて採点",
    whens: { auto: ["自動", "ローカルは終了後、クラウドは会話中"], live: ["会話中に採点", "進み具合をその場で確認"], after: ["終了後に採点", "返答が最速。レポート作成は長め"] },
    graderNote: "採点は速さより正確さが大事です。7〜8Bのローカルモデルは見落としが多いので、14B以上かクラウドを推奨します。",
    noKey: "このサービスのキーはまだ保存されていません", keysNote: "キーはそれぞれ自分のサービスにだけ送られます。", customProvider: "カスタム", clearKey: "削除", fromEnv: "OPENSPEAK_API_KEY から", endpoints: "登録済みのサービス", otherEndpoint: "— 別のサービス —",
    refresh: "更新", test: "接続テスト", testing: "テスト中…", testOk: "接続OK ✓",
    stt: "音声認識", sttModel: "ローカルモデル", sttApiModel: "文字起こしモデル",
    sttEngines: { local: ["この端末で", "無料・オフライン（faster-whisper）"], api: ["API経由", "/audio/transcriptions を使用"] },
    sttMissing: 'ローカル認識が未インストールです。OpenSpeak のフォルダで uv tool install ".[local]"（または pip install ".[local]"）を実行して再起動してください。',
    pause: "話し終わりと判断する間", tts: "相手の声",
    ttsEngines: { browser: ["ブラウザの音声", "無料・オフライン"], api: ["API経由", "OpenAI互換 /audio/speech"], off: ["オフ", "テキストのみ"] },
    voice: "声", ttsApi: "モデル / 声", rate: "話す速さ", hear: "▶ 試聴",
    local: "ローカル", cloud: "クラウド",
    detected: (n, m) => `この端末で ${n} が動いています（${m} モデル）。`, use: "使う",
    noLocal: "ローカルのモデルサーバーが見つかりません。Ollama か LM Studio を起動してから、このタブを開き直してください。",
    noVoice: "この言語の音声がシステムにないため、返答はテキストのみになります。",
    pillTarget: "練習", pillReport: "フィードバック",
    pillTip: (t, n, r) => `${t}を練習中です。ヒントは${n}、添削とレポートは${r}で表示します。クリックで変更。`,
    customLang: "カスタム言語：会話と採点は使えます。音声認識は自動判定です。",
    smallModel: "この言語ではローカル認識モデルを small 以上にすると精度が上がります。",
    entries: { free: "フリートーク", scenes: "シーン", custom: "カスタム" },
    cats: { travel: "旅行", daily: "日常", business: "ビジネス" },
    freeTitle: "フリートーク", freeSub: "今日のこと、仕事、予定…なんでも。",
    customPh: "場面を説明してください。例：あなたは大家で、暖房が壊れています。まず私に何があったか聞いてください。",
    hard: "難しく", tryUse: "使ってみよう：",
    st: { idle: "マイクはオフ・タップかスペース長押し", listening: "聞いています…", hearing: "どうぞ続けて", transcribing: "受け取りました…", thinking: "考え中…", speaking: "話しています…", ptt: "スペースを離すと送信" },
    paused: "練習は一時停止中", typePh: "言いたいことを入力…", baseUrl: "ベース URL", apiKey: "API キー", auto: "自動", nModels: (n) => `${n} 件のモデル`,
    sendNow: "今すぐ送信", skip: "スキップ", mic: "マイクのオン/オフ", keyboard: "文字で入力", close: "閉じる", cantSave: "保存できませんでした：",
    graded: (a, b) => `採点 ${a}/${b}`, notHeard: "聞き取れませんでした。もう一度どうぞ。",
    micDenied: "マイクがブロックされています。ブラウザで許可するか、入力してください。",
    preparing: "場面を準備中…",
    helpHint: "ヒント", tapToHear: "タップで再生", saved: "保存しました",
    noHistory: "まだ練習がありません。", nTurns: (n) => `${n} 発話`, nMistakes: (n) => `${n} 件の間違い`, incomplete: "未完了", live: "進行中", current: "現在の練習",
    repair: "レポートを補完", del: "削除", confirmDel: "この練習とレポートを削除しますか？",
    needSetup: "先にAIサービスとモデルを選んでください。",
    online: "オンライン", onlineWarn: "オンライン音声です。相手の発言はすべて読み上げのためブラウザ提供元（Google または Microsoft）に送られます。使いますか？",
    noLocalVoice: "この言語のオフライン音声がないため、返答はテキストのみです。システム設定 → アクセシビリティ → 読み上げコンテンツ で追加するか、下でオンライン音声を選んでください。",
    resume: "続ける", lastUnfinished: "前回の練習が終わっていません。", writeReport: "レポートを作成", dismiss: "閉じる",
    takeOver: "この練習は別のタブで開いています。ここで続けますか？", elsewhere: "この練習は別のタブで続けられています。",
    working: "レポート作成中", notEnded: "未終了", backToTalk: "← 会話に戻る",
    job: { queued: "待機中…", grading: (a, b) => `採点中 ${a}/${b}`, writing: "まとめを作成中…", ready: "レポート完成", failed: "失敗", empty: "発話がなかったため、レポートはありません。" },
    view: "見る", nothingToAdd: "補完するものはありません。", stillMissing: (n) => `${n} 件はまだ採点できませんでした。`,
  },
};

let M = null; // /api/meta
let cfg = null; // current config (keys masked)
let T = I18N.en;
let ui = "en";

const uiCode = () => {
  const pref = cfg.ui_language;
  if (pref && pref !== "auto") return pref;
  const n = (navigator.language || "en").toLowerCase();
  return n.startsWith("zh") ? "zh" : n.startsWith("ja") ? "ja" : "en";
};

function applyI18n() {
  ui = uiCode();
  T = I18N[ui] || I18N.en;
  document.documentElement.lang = ui;
  $$("[data-i18n]").forEach((el) => (el.textContent = T[el.dataset.i18n] ?? el.textContent));
  $$("[data-i18n-ph]").forEach((el) => (el.placeholder = T[el.dataset.i18nPh] ?? ""));
  $$("[data-i18n-label]").forEach((el) => el.setAttribute("aria-label", T[el.dataset.i18nLabel] ?? ""));
  $("#customPrompt").placeholder = T.customPh;
}

/* ---------------------------------------------------------------- api */

// Each page is one tab. The server gives a live session to one tab at a time.
const TAB = crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2);

async function api(path, { body, raw, type, method } = {}) {
  const opts = { method: method || (body !== undefined ? "POST" : "GET"), headers: { "X-Tab": TAB } };
  if (raw) { opts.body = body; opts.headers["Content-Type"] = type; }
  else if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers["Content-Type"] = "application/json"; }
  const r = await fetch(path, opts);
  if (!r.ok) {
    let d = r.statusText;
    try { d = (await r.json()).detail ?? d; } catch {}
    const e = new Error(typeof d === "string" ? d : d.error || JSON.stringify(d));
    e.detail = d;
    e.code = d?.code;
    e.status = r.status;
    throw e;
  }
  return (r.headers.get("content-type") || "").includes("json") ? r.json() : r;
}

let toastTimer;
function toast(msg, ms = 3500) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), ms);
}
const busy = (text) => { $("#busyText").textContent = text || ""; $("#busy").classList.toggle("hidden", !text); };

/* ---------------------------------------------------------------- languages */

const langById = (id) => M.languages.find((l) => l.id === id) || { id, name: id, native: id, tts: null, stt: null, custom: true };
const langName = (id) => langById(id).native;

let voices = [];
function loadVoices() { voices = window.speechSynthesis ? speechSynthesis.getVoices() : []; }
const voicesFor = (tag) => {
  if (!tag) return [];
  const base = tag.split("-")[0].toLowerCase();
  const exact = voices.filter((v) => v.lang.toLowerCase().replace("_", "-") === tag.toLowerCase());
  return exact.length ? exact : voices.filter((v) => v.lang.toLowerCase().startsWith(base));
};
function bestVoice(tag) {
  const list = voicesFor(tag);
  const chosen = list.find((v) => v.voiceURI === cfg.tts.browser_voice);
  if (chosen) return chosen;
  // Automatic choice is offline voices only. Online ones (Chrome's "Google …",
  // Edge's "… Online (Natural)") send every line to Google or Microsoft; they're
  // used only when picked by hand.
  const offline = list.filter((v) => v.localService);
  // Prefer the higher-quality voices systems ship alongside the robotic defaults.
  return offline.find((v) => /premium|enhanced|siri/i.test(v.name)) || offline[0] || null;
}

/* ---------------------------------------------------------------- home */

// Three ways in: free talk, the built-in scenes, or a scene of your own.
// The scenes sit side by side, one category per panel, to swipe between.
let mode = "free";
const CAT = "openspeak.sceneCat"; // the category last looked at
let cat = localStorage.getItem(CAT) || "travel";

function renderHome() {
  $("#catTabs").replaceChildren(...Object.entries(T.entries).map(([k, v]) =>
    h("button", { class: k === mode ? "on" : "", onclick: () => { mode = k; renderHome(); } }, v)));
  $("#scenes").classList.toggle("hidden", mode !== "free");
  $("#scenesBox").classList.toggle("hidden", mode !== "scenes");
  $("#customBox").classList.toggle("hidden", mode !== "custom");
  $("#scenes").replaceChildren(
    h("button", { class: "card feature", onclick: () => startSession({}) },
      h("span", { class: "em" }, "💬"), h("div", {}, h("b", {}, T.freeTitle), h("div", { class: "small" }, T.freeSub))));
  renderScenes();
}

const cats = () => Object.keys(T.cats);

function renderScenes() {
  if (!cats().includes(cat)) cat = cats()[0];
  $("#subTabs").replaceChildren(...cats().map((k) =>
    h("button", { "data-cat": k, onclick: () => showCat(k, true) },
      T.cats[k], h("span", { class: "n" }, String(M.scenes.filter((s) => s.cat === k).length)))));
  $("#pager").replaceChildren(...cats().map((k) => h("div", { class: "grid" }, ...M.scenes.filter((s) => s.cat === k).map(sceneCard))));
  if (mode === "scenes") showCat(cat, false);
}

function sceneCard(s) {
  const card = h("button", { class: "card", onclick: () => startSession({ scene_id: s.id }) },
    h("span", { class: "em" }, s.icon), h("b", {}, s.title[ui] || s.title.en));
  // Its own button over the card's corner: a button can't hold another.
  const hard = s.hard && h("button", { class: "hard", title: s.hard, onclick: () => startSession({ scene_id: s.id, hard: true }) }, T.hard);
  return h("div", { class: "scene" }, card, hard || null);
}

// Scroll to a category's panel. Swiping there by hand lands in onPagerScroll instead.
function showCat(k, animate) {
  const pager = $("#pager");
  const still = !animate || matchMedia("(prefers-reduced-motion: reduce)").matches;
  pager.scrollTo({ left: cats().indexOf(k) * pager.clientWidth, behavior: still ? "instant" : "smooth" });
  markCat(k);
}

function onPagerScroll() {
  const pager = $("#pager");
  const k = cats()[Math.round(pager.scrollLeft / (pager.clientWidth || 1))];
  if (k && k !== cat) markCat(k);
}

function markCat(k) {
  cat = k;
  localStorage.setItem(CAT, k);
  for (const b of $("#subTabs").children) b.classList.toggle("on", b.dataset.cat === k);
  fitPager();
}

// The pager is as tall as the panel in view, not the longest one.
function fitPager() {
  const pager = $("#pager");
  const panel = pager.children[cats().indexOf(cat)];
  if (panel?.offsetHeight) pager.style.height = panel.offsetHeight + "px"; // 0: not on screen
}

function renderPill() {
  const l = cfg.languages;
  // "练习 日本語 | 反馈 简体中文": a label, then the language. Narrow screens keep only the first.
  $("#langPill").replaceChildren(
    h("span", { class: "k" }, T.pillTarget), h("b", {}, langName(l.target)),
    h("span", { class: "fb" }, h("span", { class: "k" }, T.pillReport), langName(l.report)));
  $("#langPill").title = T.pillTip(langName(l.target), langName(l.native), langName(l.report));
}

/* ---------------------------------------------------------------- views */

function show(view) {
  for (const id of ["home", "talk", "reportView"]) $("#" + id).classList.toggle("hidden", id !== view);
  updatePaused();
}

/* ---------------------------------------------------------------- session */

let S = null; // active session
let pollTimer = null;
const LAST = "openspeak.lastSession"; // the session this browser last had open, until it ends

const setTitle = (text) => { $("#sceneTitle").textContent = text; $("#sceneTitle").title = text; };
const titleText = (title) => (title ? title[ui] || title.en || "" : T.freeTitle);
const sceneLabel = (scene) =>
  !scene ? "💬 " + T.freeTitle
  : scene.id === "custom" ? "✍️ " + titleText(scene.title).slice(0, 40)
  : `${scene.icon || "🎭"} ${titleText(scene.title)}`;

// Start and resume both end up here; leaveSession() undoes all of it.
function enterSession(r, scene) {
  S = { id: r.id, scene, tts: r.tts_lang, turns: {} };
  localStorage.setItem(LAST, r.id);
  $("#lastBar").classList.add("hidden");
  setTitle(sceneLabel(scene));
  $("#chat").replaceChildren();
  $("#chat").dir = r.rtl ? "rtl" : "auto";
  clearInterval(pollTimer);
  pollTimer = setInterval(poll, 2500);
  show("talk");
  closeDrawers();
  refreshHistory();
}

// Everything a session holds in this page: the poll timer, the mic, the voice.
// beacon: tell the server this tab is done with it, so it's put away soon.
function leaveSession(beacon = false) {
  if (!S) return;
  if (beacon && !S.ending) navigator.sendBeacon(`/api/session/${S.id}/leave`, TAB);
  clearInterval(pollTimer);
  pollTimer = null;
  stopSpeaking(false);
  releaseMic();
  S = null;
  updatePaused();
  refreshHistory();
}

// The server no longer has this session for us: another tab took it, or it was put away.
function lost(e) {
  if (!S || !(e.code === "elsewhere" || e.status === 404)) return false;
  leaveSession();
  show("home");
  toast(e.code === "elsewhere" ? T.elsewhere : e.message, 6000);
  return true;
}

// Which start or resume is the latest: one clicked while another was on its way wins.
let entering = 0;

async function startSession(body) {
  if (!cfg.llm.chat_model) { toast(T.needSetup); openDrawer("settings", "ai"); return; }
  const gen = ++entering;
  busy(T.preparing);
  try {
    const r = await api("/api/session", { body });
    if (gen !== entering) return; // the server puts it away once it's left idle
    const scene = body.custom ? { id: "custom", title: { en: body.custom } } : M.scenes.find((s) => s.id === body.scene_id);
    leaveSession(true);
    enterSession(r, scene);
    if (scene && cfg.languages.target === "en" && scene.phrases_en?.length) {
      $("#chat").append(h("div", { class: "small" }, T.tryUse + " " + scene.phrases_en.join(" · ")));
    }
    busy();
    const s = S;
    addAI(r.text, r.aid);
    await speak(r.text);
    if (S === s) await micStart();
  } catch (e) {
    if (gen === entering) busy();
    toast(e.message, 6000);
  }
}

async function resumeSession(id, take = false) {
  if (S?.id === id) { backToTalk(S); return; }
  const gen = ++entering;
  busy(T.preparing);
  try {
    const r = await api(`/api/session/${id}/resume`, { body: { take } });
    if (gen !== entering) return;
    leaveSession(true);
    enterSession(r, r.scene);
    for (const line of r.transcript) {
      if (line.who === "ai") { addAI(line.said, line.aid); continue; }
      const mine = addMe(line.said);
      mine.dot.className = "dot " + (line.state || "skipped");
      S.turns[line.turn] = mine.dot;
    }
    busy();
    const s = S;
    if (r.reply) { addAI(r.reply.text, r.reply.aid); await speak(r.reply.text); }
    if (S === s) await micStart();
  } catch (e) {
    if (gen !== entering) return;
    busy();
    if (e.code === "elsewhere" && !take && confirm(T.takeOver)) return resumeSession(id, true);
    toast(e.message, 6000);
  }
}

function scrollChat() { const c = $("#chat"); c.scrollTop = c.scrollHeight; }

function addAI(text, aid) {
  const b = h("div", { class: "b" }, text);
  const m = h("div", { class: "msg ai" }, b);
  if (aid) m.append(h("div", { class: "aid" }, aid));
  b.addEventListener("click", () => speak(text));
  $("#chat").append(m);
  scrollChat();
}

function addMe(text) {
  const dot = h("span", { class: "dot pending" });
  const m = h("div", { class: "msg me" }, h("div", { class: "b" }, text), h("div", { class: "meta" }, dot));
  $("#chat").append(m);
  scrollChat();
  return { m, dot };
}

function typing(cls) {
  const m = h("div", { class: `msg ${cls} typing` }, h("div", { class: "b" }, "…"));
  $("#chat").append(m);
  scrollChat();
  return m;
}

async function handleReply(r, mine, s) {
  // The session may have ended (or another begun) while this reply was on its way.
  if (!S || S !== s || S.ending) { mine.m.remove(); return false; }
  if (!r.heard) { mine.m.remove(); toast(T.notHeard); return false; }
  $(".b", mine.m).textContent = r.heard;
  S.turns[r.turn] = mine.dot;
  mine.dot.className = "dot " + (r.graded ? "pending" : "skipped");
  addAI(r.text, r.aid);
  await speak(r.text);
  return true;
}

async function sendAudio(blob) {
  const s = S;
  if (!s || s.ending) return;
  const mine = addMe("…");
  setState("thinking");
  V.inflight = true;
  try {
    const r = await api(`/api/session/${s.id}/audio`, { body: blob, raw: true, type: blob.type || "audio/webm" });
    await handleReply(r, mine, s);
  } catch (e) {
    if (e.detail?.heard) $(".b", mine.m).textContent = e.detail.heard;
    else mine.m.remove();
    if (!lost(e)) toast(e.message, 6000);
  }
  V.inflight = false;
  if (V.active) listen(); else setState("idle");
}

async function sendText(text) {
  if (!S || S.ending || !text.trim()) return;
  const s = S;
  const mine = addMe(text.trim());
  const wait = typing("ai");
  setState("thinking");
  V.inflight = true;
  try {
    const r = await api(`/api/session/${s.id}/text`, { body: { text } });
    wait.remove();
    await handleReply(r, mine, s);
  } catch (e) { wait.remove(); if (!lost(e)) toast(e.message, 6000); }
  V.inflight = false;
  if (V.active) listen(); else setState("idle");
}

async function poll() {
  const s = S;
  if (!s) return;
  try {
    const st = await api(`/api/session/${s.id}/status`);
    if (S !== s) return;
    let done = 0, gradable = 0, later = 0;
    for (const [turn, state] of Object.entries(st.graded)) {
      if (S.turns[turn]) S.turns[turn].className = "dot " + state;
      if (state === "later") later++;
      else if (state !== "skipped") { gradable++; if (state === "ok") done++; }
    }
    gradable += st.pending;
    $("#gradeInfo").textContent = later ? T.later : gradable ? T.graded(done, gradable) : "";
  } catch (e) { if (S === s) lost(e); }
}

async function help() {
  const s = S;
  if (!s || s.ending) return;
  const wait = typing("helpcard");
  try {
    const r = await api(`/api/session/${s.id}/help`, { method: "POST" });
    wait.replaceChildren(h("div", {}, "💡 " + r.hint),
      ...r.say.map((s) => h("button", { title: T.tapToHear, onclick: () => speak(s) }, "🔊 " + s)));
    wait.classList.remove("typing");
  } catch (e) { wait.remove(); if (S === s && !lost(e)) toast(e.message); }
  scrollChat();
}

async function endSession() {
  if (!S || S.ending) return;
  // From here on no new turns: the server refuses them anyway.
  S.ending = true;
  stopSpeaking(false);
  releaseMic(); // the mic light goes off now, not once the server answers
  try {
    const job = await api(`/api/session/${S.id}/finish`, { method: "POST" });
    localStorage.removeItem(LAST);
    leaveSession();
    show("home");
    Jobs.track(job);
  } catch (e) {
    if (S) S.ending = false;
    if (!lost(e)) toast(e.message, 6000);
  }
}

function showReport(id) {
  pause(); // the session stays open; it waits while the report is up
  $("#reportFrame").src = `/report/${id}?t=${Date.now()}`;
  $("#mdLink").href = `/report/${id}.md`;
  show("reportView");
  labelBack();
  closeDrawers();
}
const labelBack = () => ($("#backHome").textContent = S ? T.backToTalk : T.newSession);

// Away from the conversation (to a report, or home): the partner stops talking and the mic listening.
function pause() {
  if (S && V.active) S.micWas = true;
  stopSpeaking(false);
  if (S) micStop();
}

// Back to a conversation that was paused, and only that one: if it is gone or another has begun, nothing happens.
function backToTalk(s) {
  if (S !== s || s.ending) { updatePaused(); return; }
  show("talk");
  closeDrawers();
  const mic = s.micWas;
  s.micWas = false;
  if (mic) micStart(); // as it was when we left
}

// On the home screen with a conversation still open: say so, and offer the way back. Worked out
// from the state each time, so it can't point at a session that is no longer the open one.
function updatePaused() {
  const bar = $("#pausedBar"), s = S;
  const paused = !!s && !s.ending && !$("#home").classList.contains("hidden");
  bar.classList.toggle("hidden", !paused);
  if (!paused) { bar.replaceChildren(); return; }
  bar.replaceChildren(h("span", {}, `${T.paused} · ${sceneLabel(s.scene)}`), h("span", { class: "grow" }),
    h("button", { class: "primary sm", onclick: () => backToTalk(s) }, T.resume));
}

/* ---------------------------------------------------------------- report jobs */

// Reports are written on the server in the background, so the page stays usable.
// Each job gets a card with its progress, then a link when it's ready. The page
// polls only while some card is still waiting.
const Jobs = {
  cards: new Map(), // job id -> { el, job, done }
  timer: null,

  track(job) {
    if (!this.cards.has(job.id)) {
      const el = h("div", { class: "job", role: "status" });
      $("#jobs").append(el);
      this.cards.set(job.id, { el, job, done: false });
    }
    this.render(job);
    this.timer ??= setInterval(() => this.poll(), 2000);
  },

  async poll() {
    let jobs;
    try { ({ jobs } = await api("/api/jobs")); } catch { return; }
    const byId = new Map(jobs.map((j) => [j.id, j]));
    for (const [id, card] of this.cards) {
      if (card.done) continue;
      // Gone from the server (it restarted): the log is safe; History can finish it.
      this.render(byId.get(id) || { id, stage: "failed", error: T.incomplete });
    }
    if ([...this.cards.values()].every((c) => c.done)) { clearInterval(this.timer); this.timer = null; }
  },

  render(job) {
    const card = this.cards.get(job.id);
    if (!card) return;
    card.job = job;
    const body = [h("button", { class: "x", "aria-label": T.dismiss, onclick: () => this.dismiss(job.id) }, "×"), h("b", {}, (job.scene ? "🎭 " : "💬 ") + titleText(job.scene))]; // the job carries just the title
    if (job.stage === "ready") body.push(...this.readyLines(job));
    else if (job.stage === "failed") body.push(h("div", { class: "small bad" }, `${T.job.failed}: ${job.error}`));
    else {
      const p = job.progress;
      const grading = job.stage === "grading" && p?.total;
      const pct = grading ? 10 + (75 * p.done) / p.total : job.stage === "writing" ? 90 : 5;
      body.push(h("div", { class: "small" }, grading ? T.job.grading(p.done, p.total) : T.job[job.stage] || T.job.queued),
        h("div", { class: "bar" }, h("i", { style: `width:${pct}%` })));
    }
    card.el.className = "job " + job.stage;
    card.el.replaceChildren(...body);
    if ((job.stage === "ready" || job.stage === "failed") && !card.done) {
      card.done = true;
      refreshHistory();
    }
  },

  readyLines(job) {
    if (job.empty) return [h("div", { class: "small" }, T.job.empty)];
    const notes = [];
    if (job.kind === "repair" && !job.regraded && !job.added?.length && job.complete) notes.push(T.nothingToAdd);
    if (job.ungraded) notes.push(T.stillMissing(job.ungraded) + (job.problem ? ` (${job.problem})` : ""));
    return [
      h("div", { class: "row" }, h("span", { class: "ok" }, "✓ " + T.job.ready), h("span", { class: "grow" }),
        h("button", { class: "primary sm", onclick: () => { this.dismiss(job.id); showReport(job.id); } }, T.view)),
      ...notes.map((n) => h("div", { class: "small" }, n)),
    ];
  },

  dismiss(id) {
    this.cards.get(id)?.el.remove();
    this.cards.delete(id);
  },

  // The interface language changed.
  relabel() { for (const c of this.cards.values()) this.render(c.job); },

  // After a reload: pick up reports still being written.
  async resume() {
    try {
      const { jobs } = await api("/api/jobs");
      for (const j of jobs) if (j.stage !== "ready" && j.stage !== "failed") this.track(j);
    } catch {}
  },
};

async function writeReport(id) {
  if (S?.id === id) return endSession();
  try {
    Jobs.track(await api(`/api/report/${id}/repair`, { method: "POST" }));
    refreshHistory();
  } catch (e) { toast(e.message, 6000); }
}

// Home: offer to continue the session this browser had open when it went away.
async function offerLast() {
  const id = localStorage.getItem(LAST);
  const bar = $("#lastBar");
  if (!id) return;
  let s;
  try { s = (await api("/api/history")).sessions.find((x) => x.id === id); } catch { return; }
  if (!s || s.ended || s.working || S) { localStorage.removeItem(LAST); return; }
  // Only this one: by the time a button is clicked another session may be the last.
  const forget = () => { bar.classList.add("hidden"); if (localStorage.getItem(LAST) === id) localStorage.removeItem(LAST); };
  bar.replaceChildren(
    h("span", {}, `${T.lastUnfinished} ${titleText(s.scene)} · ${T.nTurns(s.turns)}`), h("span", { class: "grow" }),
    h("button", { class: "primary sm", onclick: () => { bar.classList.add("hidden"); resumeSession(id); } }, T.resume),
    h("button", { class: "ghost", onclick: () => { forget(); writeReport(id); } }, T.writeReport),
    h("button", { class: "ghost", onclick: forget }, T.dismiss));
  bar.classList.remove("hidden");
}

/* ---------------------------------------------------------------- voice in */

// Recording and pause detection run in the browser: no audio drivers to install,
// and the server only ever receives finished utterances.
//
// Three controls, each always doing the same thing:
//   the mic button  turns the mic on or off (on: each pause sends what you said)
//   space           hold to talk, release to send, mic on or off
//   the status line names what's happening, with the one thing to do about it:
//                   "Send now" while you talk, "Skip" while the partner does
const V = { stream: null, opening: null, ctx: null, analyser: null, rec: null, state: "idle", active: false, heard: false, voiceMs: 0, last: 0, floor: 0.008 };
const RECORDING = ["listening", "hearing", "ptt"];

function setState(s) {
  V.state = s;
  paint();
}

function paint() {
  const s = V.state;
  $("#micBtn").className = "mic " + (RECORDING.includes(s) ? "" : !V.active ? "idle" : s === "speaking" ? "speaking" : s === "idle" ? "" : "busy");
  $("#micBtn").setAttribute("aria-pressed", String(V.active));
  $("#status").textContent = T.st[s] || "";
  const act = { hearing: [T.sendNow, finishUtterance], speaking: [T.skip, () => stopSpeaking()] }[s];
  $("#statusAct").classList.toggle("hidden", !act);
  if (act) { $("#statusAct").textContent = act[0]; $("#statusAct").onclick = act[1]; }
  if (!RECORDING.includes(s)) $("#ring").style.transform = "";
}

// The microphone, asked for once however many clicks and key presses ask at once.
function openMic() {
  if (V.stream) return Promise.resolve(true);
  V.opening ??= navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } })
    .then((stream) => {
      if (!S || S.ending) { stream.getTracks().forEach((t) => t.stop()); return false; } // left while the browser asked
      V.stream = stream;
      V.ctx = new AudioContext();
      V.analyser = V.ctx.createAnalyser();
      V.analyser.fftSize = 1024;
      V.ctx.createMediaStreamSource(stream).connect(V.analyser);
      return true;
    }, () => {
      toast(T.micDenied, 6000);
      $("#typeBox").classList.remove("hidden");
      return false;
    })
    .finally(() => { V.opening = null; });
  return V.opening;
}

// Mic on. Turned on while the partner talks, it's your turn now.
async function micStart() {
  if (!S || S.ending || !(await openMic()) || !S || S.ending) return;
  V.active = true;
  if (V.state === "speaking") stopSpeaking(false);
  if (V.inflight || V.state === "transcribing") paint(); // listens once the reply is in
  else listen();
}

// Mic off. A reply on its way still arrives and is spoken.
function micStop() {
  V.active = false;
  if (RECORDING.includes(V.state)) { dropRecording(); setState("idle"); }
  else paint();
}

// Hand the microphone back to the system (the menu-bar mic light goes off).
function releaseMic() {
  micStop();
  V.stream?.getTracks().forEach((t) => t.stop());
  V.ctx?.close().catch(() => {});
  V.stream = V.analyser = V.ctx = V.rec = null;
}

function startRecorder() {
  const mime = ["audio/webm;codecs=opus", "audio/mp4", "audio/webm"].find((m) => window.MediaRecorder?.isTypeSupported(m));
  const rec = new MediaRecorder(V.stream, mime ? { mimeType: mime } : {});
  // Each recorder keeps its own chunks: a stopped recorder still delivers its last
  // chunk, and it must not end up at the start of the next utterance.
  rec.chunks = [];
  rec.ondataavailable = (e) => e.data.size && rec.chunks.push(e.data);
  V.rec = rec;
  V.rec.start(250);
  V.recAt = performance.now();
}

function listen() {
  if (!V.stream || !S || S.ending) return;
  dropRecording();
  V.heard = false; V.voiceMs = 0;
  startRecorder();
  setState("listening");
  const buf = new Float32Array(V.analyser.fftSize);
  let prev = performance.now();
  const tick = () => {
    if (!RECORDING.includes(V.state)) return;
    const now = performance.now(), dt = now - prev; prev = now;
    V.analyser.getFloatTimeDomainData(buf);
    let sum = 0;
    for (const x of buf) sum += x * x;
    const rms = Math.sqrt(sum / buf.length);
    const thr = Math.max(0.012, V.floor * 3);
    $("#ring").style.transform = `scale(${1 + Math.min(rms * 9, 0.7)})`;
    if (rms > thr) {
      V.voiceMs += dt;
      if (!V.heard && V.voiceMs > 180) { V.heard = true; if (V.state !== "ptt") setState("hearing"); }
      V.last = now;
    } else {
      V.floor = V.floor * 0.97 + rms * 0.03; // track room noise
      if (!V.heard) V.voiceMs = Math.max(0, V.voiceMs - dt);
    }
    if (V.state !== "ptt" && V.heard && now - V.last > (cfg.stt.silence_ms || 1600)) return finishUtterance();
    // Nothing said for a while: drop the silent audio instead of growing it forever.
    if (!V.heard && V.state !== "ptt" && now - V.recAt > 20000) { V.rec.onstop = null; V.rec.stop(); startRecorder(); }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

function finishUtterance() {
  setState("transcribing");
  const rec = V.rec;
  rec.onstop = () => sendAudio(new Blob(rec.chunks, { type: rec.mimeType || "audio/webm" }));
  rec.stop();
}

const micClick = () => (V.active ? micStop() : micStart());

// Space held: record until it's let go, whatever the mic button says.
async function pttStart() {
  V.spaceDown = true;
  if (V.state === "speaking") stopSpeaking(false);
  if (!(await openMic()) || !V.spaceDown || !S || S.ending || V.inflight || V.state === "transcribing") return;
  if (!RECORDING.includes(V.state)) listen();
  V.heard = true;
  setState("ptt");
}

function pttEnd() {
  V.spaceDown = false;
  if (V.state === "ptt") finishUtterance();
}

/* ---------------------------------------------------------------- voice out */

let speakDone = null;
let speakGen = 0; // which speak() call is current; stale callbacks check it
function stopSpeaking(resume = true) {
  if (window.speechSynthesis) speechSynthesis.cancel();
  if (V.audio) { V.audio.pause(); URL.revokeObjectURL(V.audio.src); V.audio = null; }
  if (speakDone) { const d = speakDone; speakDone = null; d(resume); }
}

function dropRecording() {
  if (V.rec && V.rec.state !== "inactive") { V.rec.onstop = null; V.rec.stop(); }
}

function speak(text, lang) {
  stopSpeaking(false);
  const gen = ++speakGen;
  if (!text || cfg.tts.engine === "off") return Promise.resolve();
  // Don't record our own voice.
  dropRecording();
  if (S) setState("speaking");
  return new Promise((resolve) => {
    speakDone = (resume) => {
      // Mid-request the caller resumes listening itself once the reply is in.
      if (S && resume && V.active && !V.inflight) listen();
      else if (S && V.state === "speaking") setState(V.inflight ? "thinking" : "idle");
      resolve();
    };
    // cancel() fires the previous utterance's onerror late; it must not stop this one.
    const done = () => gen === speakGen && speakDone && stopSpeaking();
    if (cfg.tts.engine === "api") {
      api("/api/tts", { body: { text } }).then((r) => r.blob()).then((b) => {
        if (gen !== speakGen) return; // stopped or replaced while the audio downloaded
        const a = new Audio(URL.createObjectURL(b));
        V.audio = a;
        a.onended = a.onerror = done;
        a.play().catch(done);
      }).catch((e) => { toast(e.message); done(); });
      return;
    }
    const tag = lang || S?.tts || langById(cfg.languages.target).tts;
    const voice = bestVoice(tag);
    // No voice of our choosing (none for this language, or none named): text only.
    // The browser's own default could be an online one.
    if (!window.speechSynthesis || !voice) return done();
    const u = new SpeechSynthesisUtterance(text);
    u.voice = voice;
    u.lang = voice.lang;
    u.rate = cfg.tts.rate || 1;
    u.onend = u.onerror = done;
    V.utter = u; // Chrome drops onend if the utterance is garbage-collected
    speechSynthesis.speak(u);
  });
}

/* ---------------------------------------------------------------- drawers */

// A drawer is a dialog: focus moves into it, the page behind can't be reached, and
// closing it gives focus back to what opened it.
let opener = null;
function openDrawer(id, tab) {
  closeDrawers();
  const d = $("#" + id);
  opener = document.activeElement;
  $("#scrim").classList.remove("hidden");
  d.classList.add("open");
  d.inert = false;
  for (const v of $$(".view, .top, .side")) v.inert = true;
  if (id === "settings") { renderSettings(); setTab(tab || "lang"); }
  $("[data-close]", d).focus();
}
function closeDrawers() {
  $("#scrim").classList.add("hidden");
  const was = $(".drawer.open");
  $$(".drawer").forEach((d) => { d.classList.remove("open"); d.inert = true; });
  for (const v of $$(".view, .top")) v.inert = false;
  $("#side").inert = !sideOpen();
  if (narrow.matches) setSide(false); // on a phone the sidebar covers the page, so it goes too
  if (was && opener?.isConnected) opener.focus();
  if (was) opener = null;
}

/* ---------------------------------------------------------------- sidebar */

// Wide screens: the sidebar sits beside the page, open or closed as last left.
// Narrow ones: it slides over the page and closes once something is picked.
const SIDE = "openspeak.sidebar";
const narrow = matchMedia("(max-width: 900px)");
const sideOpen = () => document.body.classList.contains("side-open");

function setSide(open) {
  document.body.classList.toggle("side-open", open);
  $("#side").inert = !open;
  $("#sideBtn").setAttribute("aria-expanded", String(open));
  $("#brandBtn").setAttribute("aria-expanded", String(open));
  // The scrim belongs to the overlay layout (and not under an open drawer, which has its own).
  if (!$(".drawer.open")) $("#scrim").classList.toggle("hidden", !(open && narrow.matches));
  if (!narrow.matches) localStorage.setItem(SIDE, open ? "1" : "0");
  if (open) renderHistory();
}
const restoreSide = () => setSide(!narrow.matches && localStorage.getItem(SIDE) !== "0");

function newSession() {
  pause(); // the open session waits in the list, as it does behind a report
  show("home");
  closeDrawers();
}

/* ---------------------------------------------------------------- settings */

const TABS = ["lang", "ai", "voice"];
let tab = "lang";
const wizard = () => !cfg.setup_done;

function setTab(t) {
  tab = t;
  $$("#setTabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === t));
  $$("[data-pane]").forEach((p) => p.classList.toggle("hidden", p.dataset.pane !== t));
  $("#settings .drawer-body").scrollTop = 0;
  $("#welcome").classList.toggle("hidden", !wizard());
  $("#nextBtn").textContent = wizard() && t !== "voice" ? T.next : T.done;
  if (t === "ai") detectLocal();
}

let saveTimer;
// True once saved. A refused save says why and puts the settings back as they were.
async function save(patch, quiet) {
  // Merge locally for instant UI, persist in the background.
  const merge = (a, b) => { for (const [k, v] of Object.entries(b)) (v && typeof v === "object" && !Array.isArray(v)) ? merge(a[k] ??= {}, v) : (a[k] = v); };
  const before = cfg;
  cfg = structuredClone(cfg);
  merge(cfg, structuredClone(patch));
  try {
    cfg = (await api("/api/config", { body: patch })).config;
  } catch (e) {
    cfg = before;
    toast(`${T.cantSave} ${e.message}`, 6000);
    if ($("#settings").classList.contains("open")) renderSettings();
    renderPill();
    return false;
  }
  if (!quiet) { $("#saved").textContent = T.saved; clearTimeout(saveTimer); saveTimer = setTimeout(() => ($("#saved").textContent = ""), 1500); }
  renderPill();
  return true;
}

// Save, then show the settings as they now are; and, for a changed service, look up its models.
const saveRender = (patch) => save(patch).then(renderSettings);
async function saveAndLoad(patch) {
  await save(patch);
  renderSettings();
  loadModels(true);
}

function choices(el, options, current, onPick) {
  el.replaceChildren(...options.map(([value, title, sub, tag]) =>
    h("button", { class: "choice" + (value === current ? " on" : ""), type: "button", onclick: () => onPick(value) },
      h("span", {}, title, tag ? h("span", { class: "tag " + tag }, T[tag]) : null), sub ? h("small", {}, sub) : null)));
}

function langOptions(select, value, withVoice) {
  const known = M.languages.some((l) => l.id === value);
  select.replaceChildren(
    ...M.languages.map((l) => {
      const spk = withVoice && voicesFor(l.tts).some((v) => v.localService) ? "  🔊" : "";
      return h("option", { value: l.id, selected: l.id === value }, `${l.native}${l.native !== l.name ? " — " + l.name : ""}${spk}`);
    }),
    h("option", { value: "__other", selected: !known }, T.other));
}

function renderSettings() {
  // The choices are rebuilt; the one being used keeps keyboard focus.
  const box = document.activeElement?.closest?.(".choices");
  const at = box ? [...box.children].indexOf(document.activeElement) : -1;
  fillSettings();
  if (at >= 0) $("#" + box.id)?.children[at]?.focus();
}

function fillSettings() {
  const L = cfg.languages;
  langOptions($("#target"), L.target, true);
  langOptions($("#native"), L.native);
  langOptions($("#reportLang"), L.report);
  const known = M.languages.some((l) => l.id === L.target);
  $("#targetOther").classList.toggle("hidden", known);
  if (!known) $("#targetOther").value = L.target;
  for (const [id, key] of [["#native", "native"], ["#reportLang", "report"]]) {
    if (!M.languages.some((l) => l.id === L[key])) $(id).value = "en";
  }
  choices($("#replyMode"), Object.entries(T.modes).map(([k, [a, b]]) => [k, a, b]), cfg.reply_mode, (v) => saveRender({ reply_mode: v }));
  choices($("#level"), Object.entries(T.levels), cfg.level, (v) => saveRender({ level: v }));
  langNote();

  // AI
  choices($("#provider"), M.providers.map((p) => [p.id, p.id === "custom" ? T.customProvider : p.name, null, p.local ? "local" : "cloud"]), cfg.llm.provider, pickProvider);
  const prov = M.providers.find((p) => p.id === cfg.llm.provider) || M.providers.at(-1);
  $("#baseUrl").value = cfg.llm.base_url;
  $("#baseRow").classList.toggle("hidden", prov.id !== "custom" && !!prov.base_url);
  $("#keyRow").classList.toggle("hidden", !prov.needs_key);
  $("#apiKey").value = cfg.llm.api_key;  // the key for this URL's service, masked
  $("#apiKey").placeholder = T.noKey;
  renderKeys();
  $("#chatModel").value = cfg.llm.chat_model;
  $("#graderModel").value = cfg.llm.grader_model;
  choices($("#gradeWhen"), Object.entries(T.whens).map(([k, [a, b]]) => [k, a, b]), cfg.coach.when || "auto", (v) => saveRender({ coach: { when: v } }));

  // Voice
  choices($("#sttEngine"), Object.entries(T.sttEngines).map(([k, [a, b]]) => [k, a, b, k === "local" ? "local" : "cloud"]), cfg.stt.engine, (v) => saveRender({ stt: { engine: v } }));
  $("#sttLocal").value = cfg.stt.local_model;
  $("#sttLocalRow").classList.toggle("hidden", cfg.stt.engine !== "local");
  $("#sttMissing").textContent = T.sttMissing;
  $("#sttMissing").classList.toggle("hidden", cfg.stt.engine !== "local" || M.local_stt);
  $("#sttApiRow").classList.toggle("hidden", cfg.stt.engine !== "api");
  $("#sttModel").value = cfg.stt.model;
  $("#silence").value = cfg.stt.silence_ms;
  $("#silenceOut").textContent = (cfg.stt.silence_ms / 1000).toFixed(1) + " s";
  choices($("#ttsEngine"), Object.entries(T.ttsEngines).map(([k, [a, b]]) => [k, a, b, k === "api" ? "cloud" : k === "browser" ? "local" : null]), cfg.tts.engine, (v) => saveRender({ tts: { engine: v } }));
  const vs = voicesFor(langById(L.target).tts);
  const offlineFirst = [...vs.filter((v) => v.localService), ...vs.filter((v) => !v.localService)];
  $("#browserVoice").replaceChildren(h("option", { value: "" }, T.auto), ...offlineFirst.map((v) => h("option", { value: v.voiceURI, selected: v.voiceURI === cfg.tts.browser_voice },
    `${v.localService ? "" : "🌐 "}${v.name} (${v.lang})${v.localService ? "" : " · " + T.online}`)));
  $("#voiceRow").classList.toggle("hidden", cfg.tts.engine !== "browser");
  $("#ttsApiRow").classList.toggle("hidden", cfg.tts.engine !== "api");
  $("#ttsModel").value = cfg.tts.model;
  $("#ttsVoice").value = cfg.tts.voice;
  $("#rate").value = cfg.tts.rate;
  $("#rateOut").textContent = "×" + Number(cfg.tts.rate).toFixed(2);
}

// Same as the server's config.origin(): the service a URL belongs to.
const originOf = (url) => { try { return new URL(url).origin; } catch { return ""; } };

function renderKeys() {
  const here = originOf(cfg.llm.base_url);
  const known = cfg.keys.some((k) => k.origin === here);
  $("#endpointRow").classList.toggle("hidden", !cfg.keys.length);
  $("#endpoint").replaceChildren(h("option", { value: "", selected: !known }, T.otherEndpoint),
    ...cfg.keys.map((k) => h("option", { value: k.base_url, selected: k.origin === here }, `${k.base_url}  ${k.hint}`)));
  const k = cfg.keys.find((x) => x.origin === here);
  $("#endpointKey").replaceChildren(!k ? "" : k.env ? h("small", {}, T.fromEnv)
    : h("button", { class: "ghost", type: "button", onclick: () => clearKey(k.origin) }, T.clearKey));
}

// Back to a service used before: its URL, and with it its key.
async function pickEndpoint(url) {
  if (!url) return;
  const preset = M.providers.find((p) => p.base_url && originOf(p.base_url) === originOf(url));
  await saveAndLoad({ llm: { provider: preset ? preset.id : "custom", base_url: url } });
}

async function clearKey(origin) {
  try {
    cfg = (await api("/api/keys", { method: "DELETE", body: { base_url: origin } })).config;
    renderSettings();
    renderPill();
  } catch (e) { toast(e.message); }
}

function langNote() {
  const t = langById(cfg.languages.target);
  const notes = [];
  if (t.custom) notes.push(T.customLang);
  else if (cfg.tts.engine === "browser" && !voicesFor(t.tts).length) notes.push(T.noVoice);
  else if (cfg.tts.engine === "browser" && !bestVoice(t.tts)) notes.push(T.noLocalVoice);
  const strong = ["en", "zh-CN", "zh-TW", "ja", "es", "fr", "de", "it", "pt-BR", "pt-PT", "ru", "ko", "nl", "pl"];
  if (cfg.stt.engine === "local" && ["tiny", "base"].includes(cfg.stt.local_model) && !t.custom && !strong.includes(t.id)) notes.push(T.smallModel);
  $("#langNote").textContent = notes.join(" ");
}

async function pickProvider(id) {
  const p = M.providers.find((x) => x.id === id);
  const patch = { llm: { provider: id } };
  if (p.base_url) patch.llm.base_url = p.base_url;
  await saveAndLoad(patch);
}

async function loadModels(pickFirst, quiet) {
  const list = $("#modelList");
  try {
    const r = await api("/api/models", { body: { base_url: cfg.llm.base_url, api_key: $("#apiKey").value } });
    list.replaceChildren(...r.models.map((m) => h("option", { value: m })));
    if (pickFirst && r.models.length && !r.models.includes(cfg.llm.chat_model)) {
      await save({ llm: { chat_model: r.models[0] } }, true);
      $("#chatModel").value = r.models[0];
    }
    return r.models;
  } catch (e) { list.replaceChildren(); if (!pickFirst && !quiet) toast(e.message); return []; }
}

async function detectLocal() {
  const box = $("#detect");
  box.textContent = "…";
  try {
    const { found } = await api("/api/detect");
    if (!found.length) { box.textContent = T.noLocal; return; }
    box.replaceChildren(...found.map((f) => {
      const p = M.providers.find((x) => x.id === f.provider);
      return h("div", {}, T.detected(p.name, f.models.length), " ",
        cfg.llm.provider === f.provider ? null : h("button", { class: "ghost", onclick: () => pickProvider(f.provider) }, T.use));
    }));
  } catch { box.textContent = T.noLocal; }
  loadModels(false, true).catch(() => {});
}

async function testConnection() {
  const out = $("#testOut");
  const result = (state, text) => { out.className = "test " + state; out.textContent = text; };
  result("busy", T.testing);
  const models = [...new Set([cfg.llm.chat_model, cfg.llm.grader_model].filter(Boolean))];
  try {
    for (const model of models) await api("/api/test", { body: { base_url: cfg.llm.base_url, api_key: $("#apiKey").value, model } });
    result("ok", T.testOk);
  } catch (e) { result("bad", "✗ " + e.message.slice(0, 300)); }
}

function bindSettings() {
  $$("#setTabs button").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));
  const langPick = (sel, key) => $(sel).addEventListener("change", (e) => {
    if (e.target.value === "__other") { $("#targetOther").classList.remove("hidden"); $("#targetOther").focus(); return; }
    saveRender({ languages: { [key]: e.target.value } });
  });
  langPick("#target", "target");
  langPick("#native", "native");
  langPick("#reportLang", "report");
  $("#targetOther").addEventListener("change", (e) => e.target.value.trim() && saveRender({ languages: { target: e.target.value.trim() } }));
  $("#endpoint").addEventListener("change", (e) => pickEndpoint(e.target.value));
  $("#baseUrl").addEventListener("change", (e) => saveAndLoad({ llm: { base_url: e.target.value } }));
  $("#apiKey").addEventListener("change", (e) => saveAndLoad({ llm: { api_key: e.target.value } }));
  $("#chatModel").addEventListener("change", (e) => save({ llm: { chat_model: e.target.value.trim() } }));
  $("#graderModel").addEventListener("change", (e) => save({ llm: { grader_model: e.target.value.trim() } }));
  $("#refreshModels").addEventListener("click", (e) => { e.preventDefault(); loadModels(false).then((m) => m.length && toast(T.nModels(m.length))); });
  $("#testBtn").addEventListener("click", testConnection);
  $("#sttLocal").addEventListener("change", (e) => save({ stt: { local_model: e.target.value } }).then(langNote));
  $("#sttModel").addEventListener("change", (e) => save({ stt: { model: e.target.value } }));
  $("#silence").addEventListener("input", (e) => ($("#silenceOut").textContent = (e.target.value / 1000).toFixed(1) + " s"));
  $("#silence").addEventListener("change", (e) => save({ stt: { silence_ms: Number(e.target.value) } }));
  $("#browserVoice").addEventListener("change", (e) => {
    const v = voices.find((x) => x.voiceURI === e.target.value);
    if (v && !v.localService && !confirm(T.onlineWarn)) { e.target.value = cfg.tts.browser_voice || ""; return; }
    save({ tts: { browser_voice: e.target.value } }).then(langNote);
  });
  $("#ttsModel").addEventListener("change", (e) => save({ tts: { model: e.target.value } }));
  $("#ttsVoice").addEventListener("change", (e) => save({ tts: { voice: e.target.value } }));
  $("#rate").addEventListener("input", (e) => ($("#rateOut").textContent = "×" + Number(e.target.value).toFixed(2)));
  $("#rate").addEventListener("change", (e) => save({ tts: { rate: Number(e.target.value) } }));
  $("#voiceTest").addEventListener("click", () => {
    const samples = { en: "Hi! Nice to meet you. How's your day going?", ja: "こんにちは。今日はどんな一日でしたか？", "zh-CN": "你好！今天过得怎么样？", es: "¡Hola! ¿Qué tal tu día?", fr: "Bonjour ! Comment se passe ta journée ?", de: "Hallo! Wie war dein Tag?", ko: "안녕하세요! 오늘 하루 어땠어요?" };
    speak(samples[cfg.languages.target] || samples.en, langById(cfg.languages.target).tts);
  });
  $("#nextBtn").addEventListener("click", async () => {
    if (wizard() && tab !== "voice") { setTab(TABS[TABS.indexOf(tab) + 1]); return; }
    if (wizard()) await save({ setup_done: true }, true);
    closeDrawers();
  });
}

// Everything already on screen, again in the new interface language.
function relabel() {
  applyI18n();
  renderLangMenu();
  renderPill();
  renderHome();
  renderSettings();
  setTab(tab);
  paint();
  labelBack();
  if (S) setTitle(sceneLabel(S.scene));
  Jobs.relabel();
  updatePaused();
  refreshHistory();
}

/* ---------------------------------------------------------------- history */

// The latest request wins: sessions start and end faster than the list can load.
let historySeq = 0;
const refreshHistory = () => sideOpen() && renderHistory();

async function renderHistory() {
  const seq = ++historySeq;
  let sessions;
  try { ({ sessions } = await api("/api/history")); } catch { return; }
  if (seq !== historySeq) return;
  const box = $("#historyList");
  const withTalk = sessions.filter((s) => s.turns);
  if (!withTalk.length) { box.replaceChildren(h("p", { class: "small" }, T.noHistory)); return; }
  const groups = new Map();
  for (const s of withTalk) {
    const when = dayOf(s.at);
    if (!groups.has(when)) groups.set(when, []);
    groups.get(when).push(historyRow(s));
  }
  box.replaceChildren(...[...groups].flatMap(([when, rows]) => [h("h3", {}, T.when[when]), ...rows]));
}

const localDate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
function dayOf(at) {
  const day = (at || "").slice(0, 10), now = new Date();
  if (day === localDate(now)) return "today";
  now.setDate(now.getDate() - 1);
  return day === localDate(now) ? "yesterday" : "earlier";
}

// One session: click to go on talking, ended or not. Its report and the rest are in its ⋯ menu.
function historyRow(s) {
  const title = titleText(s.scene);
  const current = S?.id === s.id;
  const state = current ? T.current : s.working ? T.working : s.live ? T.live
    : !s.ended ? T.notEnded : !s.complete ? T.incomplete : "";
  const time = dayOf(s.at) === "earlier" ? (s.at || "").slice(5, 10) : (s.at || "").slice(11, 16);
  const meta = [time, langName(s.target), T.nTurns(s.turns), T.nMistakes(s.errors), state].filter(Boolean).join(" · ");
  const why = s.ended && !s.complete && s.ungraded ? h("div", { class: "small bad" }, T.stillMissing(s.ungraded) + (s.problem ? ` (${s.problem})` : "")) : null;

  // While a report is being written, nothing can touch the session.
  const open = s.working ? null : () => resumeSession(s.id);
  // The row's own button is the title and details; ⋯ is a second button beside it, not inside it.
  const main = h("div", { class: "main", role: "button", tabindex: open ? "0" : "-1", "aria-disabled": open ? null : "true",
    onclick: () => open?.(), onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open?.(); } } },
  h("div", { class: "t" }, title), h("div", { class: "small" }, meta), why);
  const row = h("div", { class: "hist" + (current ? " on" : "") + (open ? "" : " busy") }, main);

  const items = [];
  if (s.has_report && !s.working) items.push([T.viewReport, () => showReport(s.id)]);
  if (!current && !s.working) {
    if (!s.ended) items.push([T.writeReport, () => writeReport(s.id)]); // ends it
    else if (!s.complete) items.push([T.repair, () => writeReport(s.id)]); // fills the gaps
  }
  items.push([T.del, () => deleteSession(s.id)]);
  const menu = h("div", { class: "menu hidden" }, ...items.map(([label, fn]) =>
    h("button", { onclick: (e) => { e.stopPropagation(); closeMenus(); fn(); } }, label)));
  const more = h("button", { class: "icon more", "aria-label": T.more, "aria-haspopup": "menu", title: T.more,
    onclick: (e) => {
      e.stopPropagation();
      const was = !menu.classList.contains("hidden");
      closeMenus();
      if (!was) openMenu(menu, more);
    } }, "⋯");
  row.append(more, menu);
  return row;
}
// Any session can go; the server stops whatever it's doing first.
async function deleteSession(id) {
  if (!confirm(T.confirmDel)) return;
  if (S?.id === id) { leaveSession(); localStorage.removeItem(LAST); show("home"); }
  else if (!$("#reportView").classList.contains("hidden") && $("#reportFrame").src.includes(`/report/${id}?`)) show("home");
  Jobs.dismiss(id);
  try { await api(`/api/report/${id}`, { method: "DELETE" }); } catch (err) { toast(err.message); }
  renderHistory();
}
const closeMenus = () => {
  $$(".menu").forEach((m) => m.classList.add("hidden"));
  $("#langBtn").setAttribute("aria-expanded", "false");
};

// The interface language, from the header: a choice people look for at once, and in a menu that names each
// language in itself, so it can be found whichever one the page is in now.
const UI_LANGS = [["auto", null], ["zh", "中文"], ["en", "English"], ["ja", "日本語"]];

function renderLangMenu() {
  const now = cfg.ui_language || "auto";
  $("#langMenu").replaceChildren(...UI_LANGS.map(([code, name]) =>
    h("button", { role: "menuitemradio", "aria-checked": String(code === now), onclick: async (e) => {
      e.stopPropagation();
      closeMenus();
      if (await save({ ui_language: code })) relabel();
    } }, name ?? T.auto)));
}

function toggleLangMenu(e) {
  e.stopPropagation();
  const was = !$("#langMenu").classList.contains("hidden");
  closeMenus();
  if (was) return;
  renderLangMenu();
  openMenu($("#langMenu"), $("#langBtn"));
  $("#langBtn").setAttribute("aria-expanded", "true");
  $("#langMenu button[aria-checked=true]").focus();
}

// The menu floats over the sidebar (the list clips what sticks out of it), below its button, or above it near the bottom.
function openMenu(menu, button) {
  menu.classList.remove("hidden");
  const b = button.getBoundingClientRect(), m = menu.getBoundingClientRect();
  menu.style.top = `${b.bottom + m.height + 8 > innerHeight ? Math.max(8, b.top - m.height) : b.bottom}px`;
  menu.style.left = `${Math.max(8, Math.min(b.right - m.width, innerWidth - m.width - 8))}px`;
}

/* ---------------------------------------------------------------- boot */

async function boot() {
  M = await api("/api/meta");
  cfg = M.config;
  applyI18n();
  restoreSide();
  document.documentElement.classList.remove("side-open"); // the body carries it now
  requestAnimationFrame(() => requestAnimationFrame(() => document.body.classList.remove("booting")));
  renderHome();
  renderPill();
  bindSettings();
  loadVoices();
  if (window.speechSynthesis) speechSynthesis.onvoiceschanged = () => { loadVoices(); if ($("#settings").classList.contains("open")) renderSettings(); };

  $("#historyList").addEventListener("scroll", closeMenus, { passive: true });
  $("#sideBtn").addEventListener("click", () => setSide(!sideOpen()));
  $("#newBtn").addEventListener("click", newSession);
  $("#newTop").addEventListener("click", newSession);
  $("#langBtn").addEventListener("click", toggleLangMenu);
  $("#brandBtn").addEventListener("click", () => sideOpen() || setSide(true)); // open, never close: a stray click costs nothing
  narrow.addEventListener("change", restoreSide);
  document.addEventListener("click", closeMenus);
  // Keyboard users keep focus on a button (Space presses it); after a mouse click Space is for talking.
  document.addEventListener("click", (e) => { if (e.detail) e.target.closest?.("button")?.blur(); });
  $$("[data-open]").forEach((b) => b.addEventListener("click", () => openDrawer(b.dataset.open, b.dataset.tab)));
  $$("[data-close]").forEach((b) => b.addEventListener("click", closeDrawers));
  $("#scrim").addEventListener("click", closeDrawers);
  $("#micBtn").addEventListener("click", micClick);
  $("#helpBtn").addEventListener("click", help);
  $("#endBtn").addEventListener("click", endSession);
  $("#kbBtn").addEventListener("click", () => { $("#typeBox").classList.toggle("hidden"); $("#typeInput").focus(); });
  $("#typeBox").addEventListener("submit", (e) => { e.preventDefault(); const v = $("#typeInput").value; $("#typeInput").value = ""; sendText(v); });
  $("#pager").addEventListener("scroll", onPagerScroll, { passive: true });
  new ResizeObserver(fitPager).observe($("#pager")); // its width changes with the window and the sidebar
  $("#customStart").addEventListener("click", () => { const v = $("#customPrompt").value.trim(); if (v) startSession({ custom: v }); });
  $("#backHome").addEventListener("click", () => (S ? backToTalk(S) : show("home")));
  $("#printBtn").addEventListener("click", () => $("#reportFrame").contentWindow.print());

  // Hold space to talk, release to send — for noisy rooms or long pauses. Only in
  // the conversation itself: not in a field, a drawer, or behind a report.
  // Space on a focused control does that control's job, as it does everywhere else.
  const typing = () => !!document.activeElement?.closest?.("input, textarea, select, button, a, [role=button]");
  const talking = () => S && !S.ending && !$("#talk").classList.contains("hidden") && $("#scrim").classList.contains("hidden");
  document.addEventListener("keydown", (e) => {
    if (e.code !== "Space" || typing() || !talking()) return;
    e.preventDefault(); // nor scroll, nor press the focused button
    if (!e.repeat) pttStart();
  });
  document.addEventListener("keyup", (e) => {
    if (e.code !== "Space" || !V.spaceDown) return;
    e.preventDefault();
    pttEnd();
  });
  // Let go elsewhere (another window took the keys): what was said is sent.
  addEventListener("blur", () => V.spaceDown && pttEnd());
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeMenus(); closeDrawers(); } });
  window.addEventListener("beforeunload", (e) => { if (S && !S.ending) e.preventDefault(); });
  // Closing or reloading: release the mic and tell the server, so the session is
  // put away (and can be continued) instead of waiting out the idle timeout.
  window.addEventListener("pagehide", () => leaveSession(true));
  Jobs.resume();
  offerLast();

  if (wizard()) openDrawer("settings", "lang");
}

boot().catch((e) => { document.body.textContent = "Failed to start: " + e.message; });
