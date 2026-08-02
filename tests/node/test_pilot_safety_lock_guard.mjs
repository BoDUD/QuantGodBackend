import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
const ROOT = process.cwd(); const files = [];
function walk(dir){ for(const name of readdirSync(dir)){ const path=join(dir,name); const stat=statSync(path); if(stat.isDirectory()) walk(path); else if(/\.(py|md|example)$/.test(name)) files.push(path); }}
walk(join(ROOT,'tools','pilot_safety_lock')); files.push(join(ROOT,'tools','run_pilot_safety_lock.py')); files.push(join(ROOT,'.env.pilot.local.example'));
const source = files.map((file)=>readFileSync(file,'utf8')).join('\n');
test('pilot safety lock remains non-executing',()=>{ assert.match(source,/pilotSafetyLockOnly/); assert.match(source,/humanApprovalRequired/); assert.doesNotMatch(source,/OrderSend\s*\(|OrderSendAsync\s*\(|PositionClose\s*\(|OrderModify\s*\(|TRADE_ACTION_DEAL|CTrade\b/); });
test('tool cannot write MT5 order requests or presets',()=>{ assert.doesNotMatch(source,/writesMt5OrderRequest["']?\s*[:=]\s*True|writesMt5Preset["']?\s*[:=]\s*True|livePresetMutationAllowed["']?\s*[:=]\s*True/); });
test('telegram text is a compact Shadow gate observation without pilot hints',()=>{ const text=readFileSync(join(ROOT,'tools','pilot_safety_lock','telegram_text.py'),'utf8'); assert.match(text,/安全门禁观察/); assert.match(text,/Shadow/); assert.doesNotMatch(text,/实盘试点安全锁|最大手数：|建议仓位：|入场区间：|防守位置：/); });
test('example env defaults to blocked',()=>{ const env=readFileSync(join(ROOT,'.env.pilot.local.example'),'utf8'); assert.match(env,/QG_PILOT_EXECUTION_ALLOWED=0/); assert.match(env,/QG_TELEGRAM_COMMANDS_ALLOWED=0/); assert.doesNotMatch(env,/(password|token|secret|private_key)\s*=/i); });
