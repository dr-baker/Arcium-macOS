#!/usr/bin/env node
// Offline by default. Run only during a separately authorized, owned runtime.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const OUTER = '468b32abe6e950116158652b05b256a4f55d73df';
const CORE = '845368ed6045b80fa2bd3ff99d9db4c3c103a576';
const PORT = 65086;
const APP = '/Volumes/ArciumBuild-20260930-a4a62591/ArciumBuild/publication-full-20260930/.arcium/standalone/automatic-picture-in-picture-native-468b32ab/browser/Helium Dev - automatic-picture-in-picture.app';
const PROFILE = '/Users/daniel/Library/Application Support/Helium Development/profiles/isolated/automatic-picture-in-picture';
const EXE = `${APP}/Contents/MacOS/Helium`;
const SNAPSHOT = path.resolve(APP, '../../snapshot.json');
const MS = 1500;
const HELP = `Read-only candidate-specific CDP probe. Does not launch anything.
Usage: node ${process.argv[1]} --launch /absolute/fresh-launch.json --owned-pid PID --target TARGET_ID
Optional: --control-target TARGET_ID (only an existing https://example.com/ page)
Requires current ownership authorization, a live matching profile lock/process/listener,
and matching candidate metadata. Historical launch records are not authorization.
Each HTTP/connect/command has a 1500 ms client deadline; network-phase deadline 45 seconds.
Stops video probes on the first failed scalar, then attempts browser metadata.
No Runtime.enable, Page.enable, lifecycle changes, navigation, input, or playback calls.
Prints JSONL to stdout. Run --help without contacting a browser.`;

function requireThat(value, message) { if (!value) throw new Error(message); }
export function validateLaunch(launch, pid) {
  requireThat(Number.isSafeInteger(pid) && pid > 1 && launch.pid === pid, 'owned PID mismatch');
  requireThat(launch.built_outer === OUTER && launch.core === CORE, 'candidate commits mismatch');
  requireThat(launch.app === APP && launch.profile === PROFILE, 'candidate app/profile mismatch');
  requireThat(launch.debugging_port === PORT && launch.argv?.[0] === EXE, 'candidate executable/port mismatch');
  requireThat(launch.argv.every(x => typeof x === 'string'), 'invalid argv');
  for (const [prefix, exact] of [
    ['--remote-debugging-port', `--remote-debugging-port=${PORT}`],
    ['--user-data-dir', `--user-data-dir=${PROFILE}`],
  ]) requireThat(launch.argv.filter(x => x.startsWith(prefix)).join() === exact, `${prefix} mismatch`);
  requireThat(!launch.argv.some(x => /^--(headless|enable-automation|remote-debugging-pipe)(=|$)/.test(x)), 'automation launch refused');
  requireThat(Number.isFinite(launch.launched_at), 'missing launch time');
}
export function safeSocket(raw, kind, id) {
  const u = new URL(raw);
  requireThat(u.protocol === 'ws:' && u.hostname === '127.0.0.1' && u.port === String(PORT)
    && !u.username && !u.password && !u.search && !u.hash, 'non-owned websocket endpoint');
  requireThat(kind === 'page' ? u.pathname === `/devtools/page/${id}`
    : /^\/devtools\/browser\/[a-zA-Z0-9-]+$/.test(u.pathname), 'unexpected websocket path');
  return u.href;
}
function command(file, args) {
  return execFileSync(file, args, { encoding: 'utf8', timeout: MS, maxBuffer: 1024 * 1024,
    env: { ...process.env, LC_ALL: 'C', TZ: 'UTC' }, stdio: ['ignore', 'pipe', 'pipe'] }).trim();
}
function assertOwnership(launch, pid) {
  validateLaunch(launch, pid);
  const snapshot = JSON.parse(fs.readFileSync(SNAPSHOT, 'utf8'));
  requireThat(snapshot.macos === OUTER && snapshot.core === CORE && snapshot.app === APP
    && snapshot.executable === EXE, 'standalone snapshot mismatch');
  requireThat(fs.readlinkSync(`${PROFILE}/SingletonLock`) === `${os.hostname()}-${pid}`, 'profile unowned or foreign owner');
  requireThat(Number(command('/bin/ps', ['-p', String(pid), '-o', 'uid='])) === process.getuid(), 'foreign process UID');
  requireThat(command('/bin/ps', ['-ww', '-p', String(pid), '-o', 'command=']) === launch.argv.join(' '), 'live argv mismatch');
  const start = Date.parse(`${command('/bin/ps', ['-p', String(pid), '-o', 'lstart='])} UTC`);
  requireThat(Number.isFinite(start) && Math.abs(start / 1000 - launch.launched_at) < 10, 'stale launch record or reused PID');
  const listeners = command('/usr/sbin/lsof', ['-nP', `-iTCP:${PORT}`, '-sTCP:LISTEN', '-Fpn']);
  const pids = [...listeners.matchAll(/^p(\d+)$/gm)].map(m => Number(m[1]));
  const addresses = [...listeners.matchAll(/^n(.+)$/gm)].map(m => m[1]);
  requireThat(pids.length > 0 && pids.every(p => p === pid), 'port unowned or shared with another PID');
  requireThat(addresses.includes(`127.0.0.1:${PORT}`) && addresses.every(a =>
    a === `127.0.0.1:${PORT}` || a === `[::1]:${PORT}`), 'listener is not loopback-only');
}
const emit = value => console.log(JSON.stringify({ at: new Date().toISOString(), ...value }));
async function measured(label, operation) {
  const started_at = new Date().toISOString();
  const started = performance.now();
  try {
    const result = await operation();
    emit({ label, started_at, elapsed_ms: Math.round(performance.now() - started), status: 'ok', result });
    return { ok: true, result };
  } catch (error) {
    emit({ label, started_at, elapsed_ms: Math.round(performance.now() - started), status: 'error', error: error.message });
    return { ok: false };
  }
}
async function metadata(endpoint) {
  const response = await fetch(`http://127.0.0.1:${PORT}${endpoint}`, {
    signal: AbortSignal.timeout(MS), redirect: 'error',
  });
  requireThat(response.ok, `HTTP ${response.status}`);
  return response.json();
}
async function connect(url) {
  const socket = new WebSocket(url);
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => { reject(new Error('connect timeout')); socket.close(); }, MS);
    socket.onopen = () => { clearTimeout(timer); resolve(); };
    socket.onerror = () => { clearTimeout(timer); reject(new Error('websocket connect error')); };
    socket.onclose = () => { clearTimeout(timer); reject(new Error('websocket closed before open')); };
  });
  let nextId = 1;
  return {
    close: () => socket.close(),
    call(method, params = {}) {
      requireThat(['Runtime.evaluate', 'Page.getFrameTree', 'Browser.getVersion', 'Target.getTargetInfo'].includes(method), 'method refused');
      return new Promise((resolve, reject) => {
        const id = nextId++;
        const timer = setTimeout(() => finish(new Error('command timeout; remote completion unknown')), MS);
        function finish(error, result) {
          clearTimeout(timer); socket.onmessage = null; socket.onerror = null; socket.onclose = null;
          error ? reject(error) : resolve(result);
        }
        socket.onerror = () => finish(new Error('websocket error'));
        socket.onclose = () => finish(new Error('websocket closed'));
        socket.onmessage = event => {
          let reply;
          try { reply = JSON.parse(event.data); } catch { finish(new Error('invalid CDP JSON')); return; }
          if (reply.id !== id) return;
          if (reply.error) { finish(new Error(JSON.stringify(reply.error))); return; }
          if (reply.result?.exceptionDetails) { finish(new Error(JSON.stringify(reply.result.exceptionDetails))); return; }
          finish(null, reply.result);
        };
        try { socket.send(JSON.stringify({ id, method, params })); } catch (error) { finish(error); }
      });
    },
  };
}
const evaluate = (client, expression) => client.call('Runtime.evaluate', {
  expression, returnByValue: true, awaitPromise: false, userGesture: false,
  silent: true, throwOnSideEffect: true,
});
export const SCALARS = [
  ['constant', '1'],
  ['visibility', 'document.visibilityState'],
  ['webdriver', 'navigator.webdriver'],
  ['activated', 'navigator.userActivation.hasBeenActive'],
  ['pip', '!!document.pictureInPictureElement'],
  ['video-count', 'document.querySelectorAll("video").length'],
  ['pip-is-first-video', 'document.pictureInPictureElement === document.querySelector("video")'],
  ...['paused', 'currentTime', 'muted', 'duration', 'readyState', 'networkState', 'ended', 'seeking', 'playbackRate'].map(name =>
    [name, `document.querySelector("video")?.${name}`]),
  ['error-code', 'document.querySelector("video")?.error?.code'],
  ['constant-after', '1'],
];
async function main() {
  const args = process.argv.slice(2);
  if (!args.length || args.includes('--help')) { console.log(HELP); return; }
  const options = {};
  for (let i = 0; i < args.length; i += 2) {
    requireThat(['--launch', '--owned-pid', '--target', '--control-target'].includes(args[i])
      && args[i + 1] && !options[args[i]], 'unknown, duplicate, or missing argument');
    options[args[i]] = args[i + 1];
  }
  requireThat(path.isAbsolute(options['--launch'] ?? ''), 'absolute launch file required');
  requireThat(/^[A-Fa-f0-9]+$/.test(options['--target'] ?? ''), 'exact target ID required');
  const launch = JSON.parse(fs.readFileSync(options['--launch'], 'utf8'));
  const pid = Number(options['--owned-pid']);
  assertOwnership(launch, pid);
  const hardStop = setTimeout(() => { emit({ status: 'error', error: '45-second total deadline' }); process.exit(2); }, 45000);
  try {
    emit({ label: 'identity', pid, port: PORT, outer: OUTER, core: CORE, target: options['--target'],
      note: 'Snapshot/argv/profile/listener identity checked; no full binary rehash. CDP attachment can affect timing.' });
    const version = await measured('http-version-before', () => metadata('/json/version'));
    const listing = await measured('http-list-before', () => metadata('/json/list'));
    requireThat(version.ok && listing.ok, 'metadata unavailable');
    requireThat(version.result.Browser === 'Chrome/151.0.7922.71', 'browser version mismatch');
    const target = listing.result.find(t => t.id === options['--target']);
    const targetURL = new URL(target?.url ?? 'about:blank');
    requireThat(target?.type === 'page' && targetURL.origin === 'https://www.youtube.com'
      && targetURL.pathname === '/watch', 'target is not the expected YouTube page');
    assertOwnership(launch, pid);
    const connected = await measured('page-connect', () => connect(safeSocket(target.webSocketDebuggerUrl, 'page', target.id)));
    if (connected.ok) {
      const client = connected.result;
      try {
        for (const [name, expression] of SCALARS) {
          assertOwnership(launch, pid);
          const result = await measured(`page-${name}`, () => evaluate(client, expression));
          if (!result.ok) break;
        }
        await measured('page-frame-tree', () => client.call('Page.getFrameTree'));
      } finally { client.close(); }
    }
    if (options['--control-target']) {
      const control = listing.result.find(t => t.id === options['--control-target']);
      requireThat(control?.type === 'page' && control.url === 'https://example.com/', 'control must be the existing Example page');
      assertOwnership(launch, pid);
      const c = await measured('control-connect', () => connect(safeSocket(control.webSocketDebuggerUrl, 'page', control.id)));
      if (c.ok) { try { await measured('control-constant', () => evaluate(c.result, '1')); } finally { c.result.close(); } }
    }
    assertOwnership(launch, pid);
    const browser = await measured('browser-connect', () => connect(safeSocket(version.result.webSocketDebuggerUrl, 'browser')));
    if (browser.ok) {
      try {
        await measured('browser-version', () => browser.result.call('Browser.getVersion'));
        await measured('browser-target-info', () => browser.result.call('Target.getTargetInfo', { targetId: target.id }));
      } finally { browser.result.close(); }
    }
    assertOwnership(launch, pid);
    await measured('http-version-after', () => metadata('/json/version'));
    await measured('http-list-after', () => metadata('/json/list'));
  } finally { clearTimeout(hardStop); }
}
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().then(() => process.exit(0)).catch(error => { emit({ status: 'refused-or-aborted', error: error.message }); process.exit(1); });
}
