// scripts/tests/test_sr_engine.js
// 從 build_review.py 抽出 --SR_JS_START-- / --SR_JS_END-- 之間的純 JS（IIFE），eval 到本檔的 window。
const fs = require("fs");
const path = require("path");

const py = fs.readFileSync(path.join(__dirname, "..", "build_review.py"), "utf8");
// 抓兩個標記之間（含 IIFE），不含標記行本身
const m = py.match(/\/\/ *--SR_JS_START--\r?\n([\s\S]*?)\/\/ *--SR_JS_END--/);
if (!m) { console.error("SR_JS block not found"); process.exit(1); }
const window = {};
// m[1] 已是純 JS（IIFE 會把 SR 掛到上面這個 window），直接 eval
eval(m[1]);
const SR = window.SR;
if (!SR) { console.error("window.SR undefined after eval"); process.exit(1); }

const DAY = 86400000, NOW = 1700000000000;
let fails = 0;
function ok(c, msg) { if (!c) { console.error("FAIL: " + msg); fails++; } }

ok(SR.isDue(undefined, NOW) === true, "new card is due");
ok(SR.p(undefined, NOW) === 0, "new card p=0 (most urgent)");
ok(SR.isDue({ box: "soon", last: NOW - 8 * DAY }, NOW) === true, "soon 8d due");
ok(SR.isDue({ box: "soon", last: NOW - 6 * DAY }, NOW) === false, "soon 6d not due");
ok(SR.isDue({ box: "retired", last: NOW - 999 * DAY }, NOW) === false, "retired never due");
ok(SR.apply(undefined, true, NOW).box === "soon", "new+remember→soon");
ok(SR.apply({ box: "soon", last: 0 }, true, NOW).box === "later", "soon+remember→later");
ok(SR.apply({ box: "someday", last: 0 }, true, NOW).box === "retired", "someday+remember→retired");
ok(SR.apply({ box: "later", last: 0 }, false, NOW).box === "soon", "later+forget→soon");
ok(SR.apply({ box: "soon", last: 0 }, true, NOW).last === NOW, "apply resets last");

// due 排序＋cap
const cards = Array.from({ length: 25 }, (_, i) => ({ id: "c" + i }));
const states = {}; // 全 new
const due = SR.due(cards, states, NOW, 20);
ok(due.length === 20, "due caps at 20");

// 有 state 的排最後（new 先）
const cards2 = [{ id: "a" }, { id: "b" }];
const st2 = { a: { box: "soon", last: NOW - 8 * DAY } }; // a 到期但非 new；b 是 new
const due2 = SR.due(cards2, st2, NOW, 20);
ok(due2[0].id === "b", "new before due-but-seen");

// F3：壞/舊 localStorage state 韌性（box 不在 HALFLIFE、缺 last/hist）
ok(SR.isDue({ box: "legacy" }, NOW) === true, "bad-state {box:legacy}(no last) treated as due");
ok(SR.isDue({ box: "legacy", last: NOW - 8 * DAY }, NOW) === true, "unknown box normalized to soon: 8d old => due");
ok(SR.isDue({ box: "legacy", last: NOW - 3 * DAY }, NOW) === false, "unknown box normalized to soon: 3d old => not due");
ok(!Number.isNaN(SR.p({ box: "legacy", last: NOW - 3 * DAY }, NOW)), "p() never returns NaN on bad state");
const badAp = SR.apply({ box: "legacy" }, true, NOW);
ok(badAp.box === "soon", "apply(bad-state,remember) box => soon, not undefined");
ok(badAp.box !== undefined, "apply never writes box:undefined");
ok(Array.isArray(badAp.hist), "apply hist is array even from bad state");
const badForget = SR.apply({ box: "legacy", hist: "oops" }, false, NOW);
ok(badForget.box === "soon", "apply(bad-state,forget) box => soon");
ok(Array.isArray(badForget.hist), "apply coerces non-array hist to array");

console.log(fails ? (fails + " FAILED") : "ALL PASS");
process.exit(fails ? 1 : 0);
