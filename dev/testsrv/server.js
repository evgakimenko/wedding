// Test double of the Supabase HTTP API (PostgREST subset + Auth subset) backed by real Postgres + the real setup.sql RLS.
// Only for local testing of the wedding planner.
const http = require("http"), fs = require("fs"), path = require("path"), crypto = require("crypto");
const {Pool} = require("pg");
const SITE = process.argv[2], PORT = +process.argv[3] || 8000;
const SECRET = "test-secret-test-secret-test-secret-123";
const pool = new Pool({host: "/tmp/pg", port: 5544, user: "postgres", database: "sbt", max: 8});
let OFFLINE = false; // simulate network loss for tests

const b64 = b => Buffer.from(b).toString("base64url");
const sign = p => { const h = b64(JSON.stringify({alg: "HS256", typ: "JWT"})), b = b64(JSON.stringify(p)); return h + "." + b + "." + crypto.createHmac("sha256", SECRET).update(h + "." + b).digest("base64url"); };
const verify = t => { try { const [h, b, s] = t.split("."); if (crypto.createHmac("sha256", SECRET).update(h + "." + b).digest("base64url") !== s) return null; const p = JSON.parse(Buffer.from(b, "base64url")); return p.exp * 1000 > Date.now() ? p : null; } catch (e) { return null; } };
const ANON = sign({role: "anon", exp: 4e9});
const hash = pw => crypto.createHash("sha256").update("salt:" + pw).digest("hex");
const userObj = u => ({id: u.id, aud: "authenticated", role: "authenticated", email: u.email, email_confirmed_at: new Date().toISOString(), app_metadata: {provider: "email"}, user_metadata: {}, created_at: new Date().toISOString()});
const sessionFor = u => { const now = Math.floor(Date.now() / 1000); return {access_token: sign({sub: u.id, email: u.email, role: "authenticated", aud: "authenticated", exp: now + 3600}), token_type: "bearer", expires_in: 3600, expires_at: now + 3600, refresh_token: sign({sub: u.id, typ: "refresh", exp: now + 86400 * 30}), user: userObj(u)}; };

function send(res, code, body, headers = {}) {
  res.writeHead(code, {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*", ...headers});
  res.end(body === undefined ? "" : JSON.stringify(body));
}
const readBody = req => new Promise(r => { let d = ""; req.on("data", c => d += c); req.on("end", () => { try { r(d ? JSON.parse(d) : {}); } catch (e) { r({}); } }); });
const IDENT = /^[a-z_][a-z0-9_]*$/;

async function asUser(sub, fn) {
  const c = await pool.connect();
  try {
    await c.query("begin");
    await c.query(sub ? "set local role authenticated" : "set local role anon");
    await c.query("select set_config('request.jwt.claim.sub', $1, true)", [sub || ""]);
    const r = await fn(c);
    await c.query("commit");
    return r;
  } catch (e) { await c.query("rollback").catch(() => {}); throw e; }
  finally { c.release(); }
}
function pgErr(res, e) {
  const status = e.code === "42501" ? 403 : e.code === "P0001" ? 400 : 400;
  send(res, status, {code: e.code, message: e.message, details: null, hint: null});
}
function filters(q) {
  const where = [], vals = [];
  for (const [k, v] of q) {
    if (["select", "offset", "limit", "order", "on_conflict", "columns"].includes(k)) continue;
    if (!IDENT.test(k)) throw new Error("bad column");
    let m = /^(not\.)?in\.\((.*)\)$/.exec(v);
    if (m) { const list = m[2].split(",").map(x => x.trim().replace(/^"(.*)"$/, "$1")); vals.push(list); where.push(`${m[1] ? "not " : ""}${k} = any($${vals.length})`); continue; }
    m = /^(eq|neq)\.(.*)$/.exec(v); if (!m) throw new Error("unsupported filter " + v);
    vals.push(m[2]); where.push(`${k} ${m[1] === "eq" ? "=" : "<>"} $${vals.length}`);
  }
  return {where: where.length ? " where " + where.join(" and ") : "", vals};
}

async function rest(req, res, url, tablePath) {
  const auth = (req.headers.authorization || "").replace(/^Bearer /, "");
  const claims = verify(auth); const sub = claims && claims.role === "authenticated" ? claims.sub : null;
  try {
    if (tablePath.startsWith("rpc/")) {
      const fn = tablePath.slice(4); if (!IDENT.test(fn)) return send(res, 404, {message: "no fn"});
      const args = await readBody(req); const keys = Object.keys(args).filter(k => IDENT.test(k));
      const r = await asUser(sub, c => c.query(`select * from public.${fn}(${keys.map((k, i) => `${k} => $${i + 1}`).join(", ")})`, keys.map(k => args[k])));
      const scalar = r.fields.length === 1 && r.fields[0].name === fn;
      return send(res, 200, scalar ? r.rows[0][fn] : r.rows);
    }
    const table = tablePath; if (!IDENT.test(table)) return send(res, 404, {message: "no table"});
    const q = url.searchParams;
    if (req.method === "GET") {
      const cols = (q.get("select") || "*").split(",").map(s => s.trim()).filter(s => s === "*" || IDENT.test(s));
      const {where, vals} = filters(q);
      let sql = `select ${cols.join(",")} from public.${table}${where}`;
      if (q.get("limit")) sql += ` limit ${parseInt(q.get("limit"))}`;
      if (q.get("offset")) sql += ` offset ${parseInt(q.get("offset"))}`;
      const r = await asUser(sub, c => c.query(sql, vals));
      return send(res, 200, r.rows);
    }
    if (req.method === "POST") {
      if (table !== "docs") return send(res, 403, {code: "42501", message: "not allowed in test server"});
      let rows = await readBody(req); if (!Array.isArray(rows)) rows = [rows];
      const merge = /merge-duplicates/.test(req.headers.prefer || "");
      await asUser(sub, async c => {
        for (const r of rows) {
          await c.query(`insert into public.docs (wedding_id, coll, id, data) values ($1,$2,$3,$4)` + (merge ? ` on conflict (wedding_id, coll, id) do update set data = excluded.data, updated_at = now(), updated_by = auth.uid()` : ""), [r.wedding_id, r.coll, r.id, JSON.stringify(r.data)]);
        }
      });
      return send(res, 201);
    }
    if (req.method === "DELETE") {
      const {where, vals} = filters(q); if (!where) return send(res, 400, {message: "delete needs filter"});
      await asUser(sub, c => c.query(`delete from public.${table}${where}`, vals));
      return send(res, 204);
    }
    send(res, 405, {message: "method"});
  } catch (e) { pgErr(res, e); }
}

async function authApi(req, res, url, p) {
  const body = req.method === "POST" ? await readBody(req) : {};
  if (p === "signup") {
    if (!body.email || !/@/.test(body.email)) return send(res, 400, {code: 400, error_code: "validation_failed", msg: "Unable to validate email address: invalid format"});
    if (!body.password || body.password.length < 6) return send(res, 422, {code: 422, error_code: "weak_password", msg: "Password should be at least 6 characters."});
    const ex = await pool.query("select * from authx.users where email = $1", [body.email.toLowerCase()]);
    if (ex.rows.length) return send(res, 422, {code: 422, error_code: "user_already_exists", msg: "User already registered"});
    const u = (await pool.query("insert into authx.users (email, pw) values ($1,$2) returning *", [body.email.toLowerCase(), hash(body.password)])).rows[0];
    return send(res, 200, sessionFor(u));
  }
  if (p === "token") {
    const gt = url.searchParams.get("grant_type");
    if (gt === "password") {
      const r = await pool.query("select * from authx.users where email = $1", [(body.email || "").toLowerCase()]);
      if (!r.rows.length || r.rows[0].pw !== hash(body.password || "")) return send(res, 400, {code: 400, error_code: "invalid_credentials", msg: "Invalid login credentials"});
      return send(res, 200, sessionFor(r.rows[0]));
    }
    if (gt === "refresh_token") {
      const c = verify(body.refresh_token || ""); if (!c || c.typ !== "refresh") return send(res, 400, {code: 400, error_code: "refresh_token_not_found", msg: "Invalid Refresh Token"});
      const r = await pool.query("select * from authx.users where id = $1", [c.sub]); return send(res, 200, sessionFor(r.rows[0]));
    }
  }
  if (p === "user") {
    const c = verify((req.headers.authorization || "").replace(/^Bearer /, ""));
    if (!c || !c.sub) return send(res, 401, {code: 401, msg: "invalid JWT"});
    const r = await pool.query("select * from authx.users where id = $1", [c.sub]); return send(res, 200, userObj(r.rows[0]));
  }
  if (p === "logout") return send(res, 204);
  if (p === "recover") return send(res, 200, {});
  send(res, 404, {msg: "not found"});
}

const MIME = {".html": "text/html; charset=utf-8", ".js": "application/javascript", ".json": "application/json", ".webmanifest": "application/manifest+json", ".png": "image/png", ".sql": "text/plain"};
http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  if (req.method === "OPTIONS") return send(res, 204, undefined, {"Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "*"});
  if (url.pathname === "/__offline") { OFFLINE = url.searchParams.get("on") === "1"; return send(res, 200, {OFFLINE}); }
  if (url.pathname === "/__reset") { await pool.query("truncate public.docs, public.members, public.weddings, authx.users cascade"); return send(res, 200, {ok: 1}); }
  if (url.pathname.startsWith("/rest/v1/") || url.pathname.startsWith("/auth/v1/")) {
    if (OFFLINE) { req.socket.destroy(); return; }
    if (url.pathname.startsWith("/rest/v1/")) return rest(req, res, url, url.pathname.slice(9));
    return authApi(req, res, url, url.pathname.slice(9));
  }
  if (url.pathname === "/config.js") { res.writeHead(200, {"Content-Type": "application/javascript"}); return res.end(`window.WEDDING_CONFIG={url:"http://localhost:${PORT}",key:"${ANON}"};`); }
  let f = path.join(SITE, decodeURIComponent(url.pathname)); if (url.pathname.endsWith("/")) f = path.join(f, "index.html");
  if (!f.startsWith(SITE) || !fs.existsSync(f)) { res.writeHead(404); return res.end("nf"); }
  res.writeHead(200, {"Content-Type": MIME[path.extname(f)] || "application/octet-stream"}); fs.createReadStream(f).pipe(res);
}).listen(PORT, () => console.log("test server on " + PORT));
