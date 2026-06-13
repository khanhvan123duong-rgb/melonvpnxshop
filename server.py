from flask import Flask, render_template_string, request, session, redirect, jsonify, send_file, make_response
import json, os, random, string, time, hashlib, threading, shutil, urllib.request as _ureq, urllib.parse, math, mimetypes
from datetime import datetime, timezone, timedelta
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
try:
    import requests as _req
    _REQ_OK = True
except ImportError:
    _req = None
    _REQ_OK = False

app = Flask(__name__)
# ProxyFix: bắt buộc cho Render/Heroku/Nginx (chạy sau HTTPS proxy)
# Không có cái này -> Flask không biết request qua HTTPS -> session cookie bị drop
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = os.environ.get('SECRET_KEY', 'shopvkhanh_2026_secret_key_xin_cam_on_ban_da_su_dung')
app.permanent_session_lifetime = timedelta(days=30)
# Session cookie config: an toàn trên HTTPS (Render), vẫn hoạt động local HTTP
_IS_PROD = bool(os.environ.get('RENDER') or os.environ.get('RENDER_EXTERNAL_URL'))
app.config['SESSION_COOKIE_SECURE'] = _IS_PROD
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_NAME'] = 'vkhanh_sess'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = '/data' if os.path.isdir('/data') else BASE_DIR
DB_FILE = os.path.join(DATA_DIR, 'database.json')
os.makedirs(DATA_DIR, exist_ok=True)

VN_TZ = timezone(timedelta(hours=7))
ADMIN_TG_USERNAME = os.environ.get('ADMIN_TG_USERNAME', 'anhnhoem002')
ADMIN_USER = os.environ.get('ADMIN_USER', 'vkhanh')
ADMIN_PASS = os.environ.get('ADMIN_PASS', '2011')
TIKTOK_URL = 'https://www.tiktok.com/@midu.c2'
ZALO_URL = 'https://zalo.me/84383253073'

BANK_NAME = os.environ.get('BANK_NAME', 'Momo')
BANK_ACCOUNT = os.environ.get('BANK_ACCOUNT', 'PSP2611214800000134')
BANK_HOLDER = os.environ.get('BANK_HOLDER', 'TA THI PHUC')

# ── ANTI-DDOS ─────────────────────────────────────────────────────────────────
_RATE = {}
_ACTION_RATE = {}
_BANNED = {}
_RLOCK = threading.Lock()

def get_real_ip():
    for h in ['CF-Connecting-IP', 'X-Real-IP', 'X-Forwarded-For']:
        v = request.headers.get(h)
        if v:
            return v.split(',')[0].strip()
    return request.remote_addr or '0.0.0.0'

def check_ddos(ip):
    now = time.time()
    with _RLOCK:
        ban_until = _BANNED.get(ip, 0)
        if ban_until > now:
            return False, int(ban_until - now)
        ts = [t for t in _RATE.get(ip, []) if now - t < 60]
        ts.append(now)
        _RATE[ip] = ts
        count = len(ts)
        if count > 200:
            _BANNED[ip] = now + 600
            _RATE[ip] = []
            return False, 600
        if count > 150:
            _BANNED[ip] = now + 120
            _RATE[ip] = []
            return False, 120
        return True, 0

def check_rate(ip, mx=30, win=60):
    now = time.time()
    with _RLOCK:
        ts = [t for t in _ACTION_RATE.get(ip, []) if now - t < win]
        if len(ts) >= mx:
            _ACTION_RATE[ip] = ts
            return False
        ts.append(now)
        _ACTION_RATE[ip] = ts
        return True

def cleanup_rate():
    while True:
        time.sleep(120)
        now = time.time()
        with _RLOCK:
            for ip in list(_RATE.keys()):
                _RATE[ip] = [t for t in _RATE[ip] if now - t < 120]
                if not _RATE[ip]:
                    del _RATE[ip]
            for ip in list(_ACTION_RATE.keys()):
                _ACTION_RATE[ip] = [t for t in _ACTION_RATE[ip] if now - t < 120]
                if not _ACTION_RATE[ip]:
                    del _ACTION_RATE[ip]
            for ip in list(_BANNED.keys()):
                if _BANNED[ip] < now:
                    del _BANNED[ip]
threading.Thread(target=cleanup_rate, daemon=True).start()

# ── DB + CACHE ─────────────────────────────────────────────────────────────────
_DB_CACHE = {'data': None, 'ts': 0.0}
_DB_CACHE_TTL = 2.0  # seconds

def _default_db():
    return {
        'users': {}, 'accounts': {'kim_cuong': [], 'bach_kim': [], 'lv5': []},
        'orders': [], 'carry_orders': [], 'keys': {}, 'daily_keys': {}, 'admin_notice': '',
        'notice_tg_link': '', 'notice_zalo_link': '', 'notice_btn_desc': '',
        'logs': [], 'revenue': {}, 'topup_requests': {}, 'feedback_posts': [],
        'custom_accs': [], 'discount_codes': {}
    }

def load_db():
    global _DB_CACHE
    now = time.time()
    if _DB_CACHE['data'] is not None and (now - _DB_CACHE['ts']) < _DB_CACHE_TTL:
        try:
            return json.loads(json.dumps(_DB_CACHE['data']))
        except Exception:
            pass
    if not os.path.exists(DB_FILE):
        d = _default_db()
        _DB_CACHE['data'] = d
        _DB_CACHE['ts'] = now
        return _default_db()
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            d = json.load(f)
        for k, v in _default_db().items():
            if k not in d:
                d[k] = v
        _DB_CACHE['data'] = d
        _DB_CACHE['ts'] = now
        return d
    except Exception:
        return _default_db()

def save_db(d):
    global _DB_CACHE
    _DB_CACHE['data'] = None
    _DB_CACHE['ts'] = 0.0
    tmp = DB_FILE + '.tmp'
    bak = DB_FILE + '.bak'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
        if os.path.exists(DB_FILE):
            shutil.copy2(DB_FILE, bak)
        os.replace(tmp, DB_FILE)
    except Exception:
        pass

def add_log(db, event, detail, user='system'):
    ts = datetime.now(VN_TZ).strftime('%d/%m/%Y %H:%M:%S')
    db['logs'].insert(0, {'time': ts, 'event': event, 'detail': detail, 'user': user})
    if len(db['logs']) > 1000:
        db['logs'] = db['logs'][:1000]

# ── HELPERS ────────────────────────────────────────────────────────────────────
def tg_send(chat_id, text, reply_markup=None): pass
def tg_edit_message(chat_id, message_id, text, reply_markup=None): pass
def tg_answer_callback(callback_id, text=""): pass
def tg_admin(text, reply_markup=None): pass
def now_vn():
    return datetime.now(VN_TZ).strftime('%d/%m/%Y %H:%M:%S')

def rand_id(n=8):
    return ''.join(random.choices(string.digits, k=n))

def rand_content():
    chars = string.ascii_uppercase + string.digits
    return 'NAPTIEN' + ''.join(random.choices(chars, k=8))

def _find_user(db, query):
    q = query.strip().lower()
    for uid, u in db['users'].items():
        if u.get('username', '').lower() == q or u.get('display', '').lower() == q or uid == q:
            return uid
    return None

import re as _re
BANNED_WORDS = ['dit','fuck','sex','rape','lon','cu','buoi','lol','ngu','dai','troll','hack','scam','cheat','bot','admin','mod','staff','support','system','root','superuser','owner']
def validate_uname(s):
    if not _re.match(r'^[a-zA-Z0-9_]{3,20}$', s):
        return '⚠️ Tên đăng nhập chỉ dùng chữ không dấu, số, dấu _ (3-20 ký tự, không dấu cách)'
    sl = s.lower()
    for w in BANNED_WORDS:
        if w in sl:
            return '⛔ Tên đăng nhập chứa từ không được phép'
    return None
def validate_pw(s):
    if ' ' in s:
        return '⚠️ Mật khẩu không được chứa dấu cách'
    if not _re.match(r'^[a-zA-Z0-9_!@#$%^&*()\-+=.]{4,}$', s):
        return '⚠️ Mật khẩu chỉ dùng ký tự không dấu, không dấu cách (ít nhất 4 ký tự)'
    return None

def calc_carry_price(rank, stars):
    high_ranks = ['Cao Thủ', 'Thách Đấu']
    price_per_star = 1500 if rank in high_ranks else 1000
    total = stars * price_per_star
    total = math.ceil(total / 1000) * 1000
    if stars >= 10:
        discount = int(total * 0.10)
        total = total - discount
        total = math.ceil(total / 1000) * 1000
    return total, price_per_star

# ── STATIC FILES ───────────────────────────────────────────────────────────────
STATIC_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.mp3', '.mp4', '.webm', '.webp', '.svg', '.ico', '.css', '.js'}
SKIP_PATHS = {'/healthz', '/tg-webhook', '/favicon.ico'}
SKIP_EXTS = ('.jpg', '.jpeg', '.png', '.gif', '.mp3', '.mp4', '.webm', '.webp', '.ico', '.css', '.js', '.svg')

@app.route('/favicon.ico')
def favicon():
    return '', 204

@app.route('/<path:fname>')
def static_flat(fname):
    if '..' in fname or fname.count('/') > 0:
        return 'Forbidden', 403
    ext = os.path.splitext(fname)[1].lower()
    if ext not in STATIC_EXTS:
        return page_not_found(None)
    fpath = os.path.join(BASE_DIR, fname)
    if os.path.isfile(fpath):
        mime = mimetypes.guess_type(fname)[0] or 'application/octet-stream'
        resp = make_response(send_file(fpath, mimetype=mime))
        resp.headers['Cache-Control'] = 'public, max-age=86400'
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp
    return page_not_found(None)

# ── MIDDLEWARE ─────────────────────────────────────────────────────────────────
@app.before_request
def before():
    if request.method == 'OPTIONS':
        return
    path = request.path
    # Skip static files entirely
    if path.endswith(SKIP_EXTS):
        return
    if path in SKIP_PATHS:
        return
    ip = get_real_ip()
    ok, wait = check_ddos(ip)
    if not ok:
        if path.startswith('/api/') or path.startswith('/admin/api/'):
            return jsonify({'ok': False, 'msg': f'Quá nhiều yêu cầu. Thử lại sau {wait}s.'}), 429
        return make_response(
            f'<h1>429 Too Many Requests</h1><p>IP bị tạm khóa {wait}s. Vui lòng thử lại sau.</p>', 429)

@app.after_request
def after(resp):
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['X-Frame-Options'] = 'SAMEORIGIN'
    resp.headers['X-XSS-Protection'] = '1; mode=block'
    return resp

def _ping():
    time.sleep(60)
    while True:
        time.sleep(12 * 60)
        try:
            host = os.environ.get('RENDER_EXTERNAL_URL', '')
            if host:
                _ureq.urlopen(host.rstrip('/') + '/healthz', timeout=8)
        except Exception:
            pass
threading.Thread(target=_ping, daemon=True).start()

def _ping2():
    time.sleep(420)
    while True:
        time.sleep(14 * 60)
        try:
            host = os.environ.get('RENDER_EXTERNAL_URL', '')
            if host:
                _ureq.urlopen(host.rstrip('/') + '/healthz', timeout=8)
        except Exception:
            pass
threading.Thread(target=_ping2, daemon=True).start()

@app.route('/healthz')
def healthz():
    return jsonify({'status': 'ok'})

@app.errorhandler(404)
def page_not_found(e):
    return """<!DOCTYPE html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Không tìm thấy - Shop VKhanh</title>
<style>*{margin:0;padding:0;box-sizing:border-box;}body{font-family:system-ui,sans-serif;background:linear-gradient(135deg,#4f46e5,#7c3aed);min-height:100vh;display:flex;align-items:center;justify-content:center;}
.box{background:#fff;border-radius:24px;padding:2.5rem 2rem;text-align:center;max-width:340px;width:90%;box-shadow:0 20px 60px rgba(0,0,0,.2);}
.emoji{font-size:3.5rem;margin-bottom:1rem;}h1{font-size:1.3rem;color:#1e1b4b;margin-bottom:.5rem;}
p{font-size:.85rem;color:#6b7280;margin-bottom:1.5rem;}
a{display:inline-block;background:linear-gradient(135deg,#4f46e5,#7c3aed);color:#fff;text-decoration:none;padding:.75rem 1.75rem;border-radius:50px;font-weight:700;font-size:.9rem;}</style>
<script>setTimeout(()=>location.href='/',3000);</script></head>
<body><div class="box"><div class="emoji">🎮</div><h1>Trang không tồn tại</h1>
<p>Đang chuyển về trang chính sau 3 giây...</p><a href="/">Về Trang Chính</a></div></body></html>""", 404

@app.errorhandler(500)
def server_error(e):
    return """<!DOCTYPE html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lỗi Server - Shop VKhanh</title>
<style>*{margin:0;padding:0;box-sizing:border-box;}body{font-family:system-ui,sans-serif;background:linear-gradient(135deg,#dc2626,#b91c1c);min-height:100vh;display:flex;align-items:center;justify-content:center;}
.box{background:#fff;border-radius:24px;padding:2.5rem 2rem;text-align:center;max-width:340px;width:90%;box-shadow:0 20px 60px rgba(0,0,0,.2);}
.emoji{font-size:3.5rem;margin-bottom:1rem;}h1{font-size:1.3rem;color:#1e1b4b;margin-bottom:.5rem;}
p{font-size:.85rem;color:#6b7280;margin-bottom:1.5rem;}
a{display:inline-block;background:linear-gradient(135deg,#4f46e5,#7c3aed);color:#fff;text-decoration:none;padding:.75rem 1.75rem;border-radius:50px;font-weight:700;font-size:.9rem;}</style>
<script>setTimeout(()=>location.href='/',5000);</script></head>
<body><div class="box"><div class="emoji">⚠️</div><h1>Lỗi server tạm thời</h1>
<p>Đang tự chuyển về trang chính sau 5 giây...</p><a href="/">Về Trang Chính</a></div></body></html>""", 500

# ── TELEGRAM BOT (webhook stub – notifications disabled) ──────────────────────
@app.route('/tg-webhook', methods=['POST'])
def tg_webhook():
    return 'ok'

def _do_approve_topup(db, content_key, amount=None):
    req = db.get('topup_requests', {}).get(content_key)
    if not req:
        return
    if req.get('status') != 'pending':
        return
    if amount is None:
        amount = req.get('amount', 0)
    uid = req.get('uid')
    if not uid or uid not in db['users']:
        return
    db['users'][uid]['balance'] = db['users'][uid].get('balance', 0) + amount
    db['users'][uid].setdefault('notifs', []).insert(0, {
        'type': 'balance', 'msg': f'✅ Nạp tiền thành công! <b>{amount:,}đ</b> đã được cộng vào tài khoản.', 'time': now_vn()
    })
    req['status'] = 'approved'
    req['approved_at'] = now_vn()
    add_log(db, 'Duyệt nạp tiền', f'+{amount:,}đ cho {req.get("username","?")} | mã: {content_key}', 'admin')
    save_db(db)

  # ══════════════════════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if session.get('uid'):
        return redirect('/')
    error = ''
    prefill_user = request.args.get('u', '')
    need_captcha = not session.get('captcha_verified', False)
    if request.method == 'POST':
        uname = request.form.get('username', '').strip()
        pw = request.form.get('password', '').strip()
        if need_captcha:
            cap_ans = request.form.get('captcha_answer', '')
            cap_q = session.get('captcha_q')
            if str(cap_q) != str(cap_ans):
                error = '❌ Sai mã xác minh!'
                a, b = random.randint(1, 9), random.randint(1, 9)
                session['captcha_q'] = a + b
                return render_template_string(AUTH_TEMPLATE, mode='login', error=error, cap_a=a, cap_b=b, prefill_user=uname, need_captcha=need_captcha)
            session['captcha_verified'] = True
        if not uname or not pw:
            error = '⚠️ Vui lòng nhập đầy đủ!'
        else:
            db = load_db()
            found = None
            for uid, u in db['users'].items():
                if u.get('username', '').lower() == uname.lower():
                    found = (uid, u)
                    break
            if not found:
                error = '❌ Tài khoản không tồn tại!'
            elif hashlib.sha256(pw.encode()).hexdigest() != found[1].get('pw'):
                error = '❌ Sai mật khẩu!'
            else:
                uid, u = found
                session.permanent = True
                session['uid'] = uid
                session['spw'] = u['pw']
                db['users'][uid]['last_login'] = now_vn()
                db['users'][uid]['last_ip'] = get_real_ip()
                add_log(db, 'Đăng nhập', f'{uname} từ {get_real_ip()}', uname)
                save_db(db)
                return redirect('/')
    a, b = random.randint(1, 9), random.randint(1, 9)
    session['captcha_q'] = a + b
    return render_template_string(AUTH_TEMPLATE, mode='login', error=error, cap_a=a, cap_b=b, prefill_user=prefill_user, need_captcha=need_captcha)

@app.route('/register', methods=['GET', 'POST'])
def register_page():
    if session.get('uid'):
        return redirect('/')
    error = ''
    need_captcha = not session.get('captcha_verified', False)
    if request.method == 'POST':
        uname = request.form.get('username', '').strip()
        pw = request.form.get('password', '').strip()
        display = request.form.get('display', '').strip() or uname
        if need_captcha:
            cap_ans = request.form.get('captcha_answer', '')
            cap_q = session.get('captcha_q')
            if str(cap_q) != str(cap_ans):
                error = '❌ Sai mã xác minh!'
                a, b = random.randint(1, 9), random.randint(1, 9)
                session['captcha_q'] = a + b
                return render_template_string(AUTH_TEMPLATE, mode='register', error=error, cap_a=a, cap_b=b, prefill_user='', need_captcha=need_captcha)
            session['captcha_verified'] = True
        if not uname or not pw:
            error = '⚠️ Vui lòng nhập đầy đủ!'
        else:
            err_u = validate_uname(uname)
            err_p = validate_pw(pw)
            if err_u:
                error = err_u
            elif err_p:
                error = err_p
        if not error:
            db = load_db()
            duplicate = any(u.get('username', '').lower() == uname.lower() for u in db['users'].values())
            if duplicate:
                error = '⛔ Tên đăng nhập đã tồn tại!'
            else:
                uid = 'u' + rand_id(10)
                pw_hash = hashlib.sha256(pw.encode()).hexdigest()
                ip = get_real_ip()
                ua = request.headers.get('User-Agent', '')[:100]
                db['users'][uid] = {
                    'uid': uid, 'username': uname, 'display': display,
                    'pw': pw_hash, 'balance': 0, 'created': now_vn(),
                    'last_ip': ip, 'ua': ua, 'notifs': [], 'role': 'user', 'random_id': rand_id(8)
                }
                add_log(db, 'Đăng ký', f'User mới: {uname} | IP: {ip}', uname)
                save_db(db)

                return redirect(f'/login?u={urllib.parse.quote(uname)}&registered=1')
    a, b = random.randint(1, 9), random.randint(1, 9)
    session['captcha_q'] = a + b
    return render_template_string(AUTH_TEMPLATE, mode='register', error=error, cap_a=a, cap_b=b, prefill_user='', need_captcha=need_captcha)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/change-password', methods=['POST'])
def change_password():
    uid = session.get('uid')
    if not uid:
        return jsonify({'ok': False, 'msg': 'Chưa đăng nhập'})
    old_pw = request.form.get('old_pw', '')
    new_pw = request.form.get('new_pw', '')
    err_p = validate_pw(new_pw)
    if err_p:
        return jsonify({'ok': False, 'msg': err_p})
    db = load_db()
    u = db['users'].get(uid)
    if not u:
        return jsonify({'ok': False, 'msg': 'Không tìm thấy tài khoản'})
    if hashlib.sha256(old_pw.encode()).hexdigest() != u['pw']:
        return jsonify({'ok': False, 'msg': 'Sai mật khẩu hiện tại'})
    new_hash = hashlib.sha256(new_pw.encode()).hexdigest()
    db['users'][uid]['pw'] = new_hash
    add_log(db, 'Đổi mật khẩu', f'{u["username"]} đổi mật khẩu', u['username'])
    save_db(db)
    session.clear()
    return jsonify({'ok': True, 'msg': 'Đổi thành công! Đang chuyển về đăng nhập...'})

# ══════════════════════════════════════════════════════════════════════════════
# MAIN ROUTES
# ══════════════════════════════════════════════════════════════════════════════
def require_login():
    if not session.get('uid'):
        return redirect('/login')
    return None

@app.route('/')
def home():
    r = require_login()
    if r: return r
    db = load_db()
    notice = db.get('admin_notice', '')
    acc_counts = {k: len([a for a in v if not a.get('sold')]) for k, v in db['accounts'].items()}
    return render_template_string(MAIN_TEMPLATE, notice=notice, acc_counts=acc_counts)

@app.route('/profile-data')
def profile_data():
    uid = session.get('uid')
    if not uid: return jsonify({'ok': False, 'msg': 'Chưa đăng nhập'})
    db = load_db()
    u = db['users'].get(uid, {})
    return jsonify({
        'ok': True, 'display': u.get('display', u.get('username')),
        'username': u.get('username'), 'balance': u.get('balance', 0),
        'random_id': u.get('random_id', '00000000'),
        'created': u.get('created', ''), 'last_ip': u.get('last_ip', '')
    })

@app.route('/api/notice')
def api_notice():
    db = load_db()
    return jsonify({
        'notice': db.get('admin_notice', ''),
        'tg_link': db.get('notice_tg_link', ''),
        'zalo_link': db.get('notice_zalo_link', ''),
        'btn_desc': db.get('notice_btn_desc', '')
    })

@app.route('/api/balance')
def api_balance():
    uid = session.get('uid')
    if not uid: return jsonify({'ok': False, 'msg': 'Chưa đăng nhập'})
    db = load_db()
    u = db['users'].get(uid, {})
    new_notifs = len([n for n in u.get('notifs', []) if not n.get('read')])
    return jsonify({'ok': True, 'balance': u.get('balance', 0), 'new_notifs': new_notifs})

@app.route('/api/notifs')
def api_notifs():
    uid = session.get('uid')
    if not uid: return jsonify({'ok': False, 'msg': 'Chưa đăng nhập'})
    db = load_db()
    notifs = db['users'].get(uid, {}).get('notifs', [])[:20]
    for n in db['users'].get(uid, {}).get('notifs', []):
        n['read'] = True
    save_db(db)
    return jsonify({'ok': True, 'notifs': notifs})

@app.route('/api/acc-count')
def api_acc_count():
    db = load_db()
    return jsonify({k: len([a for a in v if not a.get('sold')]) for k, v in db['accounts'].items()})

@app.route('/api/feedbacks')
def api_feedbacks():
    uid = session.get('uid')
    if not uid: return jsonify({'ok': False, 'msg': 'Chưa đăng nhập'})
    db = load_db()
    posts = db.get('feedback_posts', [])
    return jsonify({'ok': True, 'posts': posts[:20]})

# ── TOPUP API ──────────────────────────────────────────────────────────────────
@app.route('/api/topup-request', methods=['POST'])
def api_topup_request():
    uid = session.get('uid')
    if not uid: return jsonify({'ok': False, 'msg': 'Chưa đăng nhập'})
    ip = get_real_ip()
    if not check_rate(ip, 10, 60):
        return jsonify({'ok': False, 'msg': 'Quá nhiều yêu cầu! Vui lòng thử lại sau.'})
    try:
        amount = int(request.form.get('amount', 0))
    except:
        return jsonify({'ok': False, 'msg': 'Số tiền không hợp lệ'})
    if amount < 1000:
        return jsonify({'ok': False, 'msg': 'Số tiền tối thiểu 1.000đ'})
    db = load_db()
    u = db['users'].get(uid)
    if not u: return jsonify({'ok': False, 'msg': 'Không tìm thấy tài khoản'})
    content = rand_content()
    expires = time.time() + 3600
    db.setdefault('topup_requests', {})[content] = {
        'uid': uid, 'username': u['username'], 'amount': amount,
        'content': content, 'created': now_vn(), 'expires': expires, 'status': 'pending',
        'bank_name': BANK_NAME, 'bank_account': BANK_ACCOUNT, 'bank_holder': BANK_HOLDER
    }
    add_log(db, 'Yêu cầu nạp tiền', f'{u["username"]} yêu cầu nạp {amount:,}đ | mã: {content}', u['username'])
    save_db(db)
    kb = {'inline_keyboard': [[
        {'text': f'✅ Duyệt {amount:,}đ', 'callback_data': f'approve_{content}'},
        {'text': '❌ Từ chối', 'callback_data': f'reject_{content}'}
    ]]}
    return jsonify({
        'ok': True, 'content': content,
        'expires': int(expires),
        'tg_link': f'https://t.me/{ADMIN_TG_USERNAME}',
        'bank_name': BANK_NAME,
        'bank_account': BANK_ACCOUNT,
        'bank_holder': BANK_HOLDER
    })

@app.route('/api/my-topups')
def api_my_topups():
    uid = session.get('uid')
    if not uid: return jsonify({'ok': False, 'msg': 'Chưa đăng nhập'})
    db = load_db()
    topups = [r for r in db.get('topup_requests', {}).values() if r.get('uid') == uid]
    topups.sort(key=lambda x: x.get('created', ''), reverse=True)
    return jsonify({'ok': True, 'topups': topups[:20]})

@app.route('/api/my-orders')
def api_my_orders():
    uid = session.get('uid')
    if not uid: return jsonify({'ok': False, 'msg': 'Chưa đăng nhập'})
    db = load_db()
    orders = [o for o in db.get('orders', []) if o.get('uid') == uid]
    orders.reverse()
    return jsonify({'ok': True, 'orders': orders[:20]})

@app.route('/api/my-carries')
def api_my_carries():
    uid = session.get('uid')
    if not uid: return jsonify({'ok': False, 'msg': 'Chưa đăng nhập'})
    db = load_db()
    carries = [o for o in db.get('carry_orders', []) if o.get('uid') == uid]
    carries.reverse()
    return jsonify({'ok': True, 'carries': carries[:20]})

# ── SHOP API ──────────────────────────────────────────────────────────────────
PRICES = {'kim_cuong': 20000, 'bach_kim': 15000, 'lv5': 2500}
CAT_NAMES = {'kim_cuong': 'Clon Rank Kim Cương', 'bach_kim': 'Clon Bạch Kim', 'lv5': 'Clon Lv5 Google'}

@app.route('/api/buy', methods=['POST'])
def api_buy():
    uid = session.get('uid')
    if not uid: return jsonify({'ok': False, 'msg': 'Chưa đăng nhập'})
    ip = get_real_ip()
    if not check_rate(ip, 20, 60):
        return jsonify({'ok': False, 'msg': 'Quá nhiều yêu cầu! Vui lòng thử lại sau.'})
    cat = request.form.get('cat', '')
    try:
        qty = int(request.form.get('qty', 1))
    except:
        return jsonify({'ok': False, 'msg': 'Số lượng không hợp lệ'})
    if cat not in PRICES: return jsonify({'ok': False, 'msg': 'Loại acc không hợp lệ'})
    if qty < 1 or qty > 10: return jsonify({'ok': False, 'msg': 'Số lượng từ 1–10'})
    db = load_db()
    u = db['users'].get(uid)
    if not u: return jsonify({'ok': False, 'msg': 'Không tìm thấy tài khoản'})
    total = PRICES[cat] * qty
    avail = [a for a in db['accounts'].get(cat, []) if not a.get('sold')]
    if len(avail) < qty:
        return jsonify({'ok': False, 'msg': f'Chỉ còn {len(avail)} acc, không đủ {qty}!'})
    if u.get('balance', 0) < total:
        short = total - u.get('balance', 0)
        return jsonify({
            'ok': False,
            'msg': f'Số dư không đủ! Cần {total:,}đ, bạn có {u.get("balance",0):,}đ',
            'need_topup': True,
            'short': short,
            'needed': total,
            'have': u.get('balance', 0)
        })
    bought = avail[:qty]
    result_accs = []
    for a in bought:
        for i, acc in enumerate(db['accounts'][cat]):
            if acc.get('id') == a.get('id') and not acc.get('sold'):
                db['accounts'][cat][i].update({'sold': True, 'sold_to': uid, 'sold_to_name': u['username'], 'sold_time': now_vn()})
                result_accs.append(acc)
                break
    db['users'][uid]['balance'] = u.get('balance', 0) - total
    order_id = 'OD' + rand_id(8)
    db['orders'].append({
        'id': order_id, 'uid': uid, 'username': u['username'],
        'cat': cat, 'cat_name': CAT_NAMES[cat], 'qty': qty, 'total': total,
        'accs': result_accs, 'time': now_vn()
    })
    month_key = datetime.now(VN_TZ).strftime('%Y-%m')
    db['revenue'][month_key] = db['revenue'].get(month_key, 0) + total
    add_log(db, 'Mua acc', f'{u["username"]} mua {qty} {CAT_NAMES[cat]} | {total:,}đ', u['username'])
    db['users'][uid].setdefault('notifs', []).insert(0, {
        'type': 'purchase',
        'msg': f'✅ Mua {qty} acc {CAT_NAMES[cat]} thành công! Trừ {total:,}đ', 'time': now_vn()
    })
    save_db(db)
    acc_lines = '\n'.join([f"  • {a.get('user','?')} | {a.get('pass','?')}" for a in result_accs]) or '  (xem panel)'

    return jsonify({'ok': True, 'accs': result_accs, 'total': total, 'new_balance': db['users'][uid]['balance']})

# ── CARRY API ─────────────────────────────────────────────────────────────────
VALID_RANKS = ['Đồng', 'Bạc', 'Vàng', 'Bạch Kim', 'Kim Cương', 'Cao Thủ', 'Thách Đấu']

@app.route('/api/carry-order', methods=['POST'])
def api_carry_order():
    uid = session.get('uid')
    if not uid: return jsonify({'ok': False, 'msg': 'Chưa đăng nhập'})
    ip = get_real_ip()
    if not check_rate(ip, 20, 60):
        return jsonify({'ok': False, 'msg': 'Quá nhiều yêu cầu!'})
    try:
        stars = int(request.form.get('stars', 0))
    except:
        return jsonify({'ok': False, 'msg': 'Số sao không hợp lệ'})
    rank = request.form.get('rank', '').strip()
    note = request.form.get('note', '').strip()
    discount_code = request.form.get('code', '').strip().upper()
    if stars < 5:
        return jsonify({'ok': False, 'msg': 'Tối thiểu 5 sao mới nhận kéo!'})
    if stars > 200:
        return jsonify({'ok': False, 'msg': 'Số sao tối đa 200'})
    if not rank or rank not in VALID_RANKS:
        return jsonify({'ok': False, 'msg': 'Vui lòng chọn rank hiện tại hợp lệ'})
    total, price_per_star = calc_carry_price(rank, stars)
    db = load_db()
    u = db['users'].get(uid)
    if not u: return jsonify({'ok': False, 'msg': 'Không tìm thấy tài khoản'})
    discount_pct = 0
    if discount_code:
        cdata = db.get('discount_codes', {}).get(discount_code)
        if not cdata:
            return jsonify({'ok': False, 'msg': '❌ Mã giảm giá không tồn tại'})
        if cdata.get('expires_at', 0) != 0 and time.time() > cdata['expires_at']:
            return jsonify({'ok': False, 'msg': '❌ Mã giảm giá đã hết hạn'})
        if uid in cdata.get('used_by', []):
            return jsonify({'ok': False, 'msg': '❌ Bạn đã dùng mã này rồi'})
        discount_pct = cdata.get('discount_pct', 0)
    original_total = total
    if discount_pct:
        total = int(total * (1 - discount_pct / 100))
    if u.get('balance', 0) < total:
        short = total - u.get('balance', 0)
        return jsonify({
            'ok': False,
            'msg': f'Số dư không đủ! Cần {total:,}đ, bạn có {u.get("balance",0):,}đ',
            'need_topup': True,
            'needed': total,
            'short': short
        })
    db['users'][uid]['balance'] = u.get('balance', 0) - total
    if discount_code and discount_code in db.get('discount_codes', {}):
        db['discount_codes'][discount_code].setdefault('used_by', []).append(uid)
    order_id = 'CR' + rand_id(8)
    db.setdefault('carry_orders', []).append({
        'id': order_id, 'uid': uid, 'username': u['username'],
        'stars': stars, 'rank': rank, 'note': note,
        'total': total, 'price_per_star': price_per_star, 'time': now_vn(), 'status': 'pending',
        'discount_code': discount_code, 'original_total': original_total, 'discount_pct': discount_pct
    })
    month_key = datetime.now(VN_TZ).strftime('%Y-%m')
    db['revenue'][month_key] = db['revenue'].get(month_key, 0) + total
    add_log(db, 'Kéo thuê FF', f'{u["username"]} kéo {stars} sao rank {rank} ({price_per_star:,}đ/sao) | {total:,}đ', u['username'])
    db['users'][uid].setdefault('notifs', []).insert(0, {
        'type': 'carry',
        'msg': f'✅ Đặt kéo thuê {stars} sao (rank {rank}) thành công! Trừ {total:,}đ. Liên hệ admin để kéo.',
        'time': now_vn()
    })
    save_db(db)

    return jsonify({
        'ok': True, 'total': total,
        'new_balance': db['users'][uid]['balance'],
        'order_id': order_id,
        'tg_link': f'https://t.me/{ADMIN_TG_USERNAME}',
        'tiktok_url': TIKTOK_URL
    })

# ── ADMIN ─────────────────────────────────────────────────────────────────────
@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if session.get('is_admin'): return redirect('/admin/panel')
    error = ''
    if request.method == 'POST':
        if request.form.get('username') == ADMIN_USER and request.form.get('password') == ADMIN_PASS:
            session['is_admin'] = True
            session.permanent = True
            return redirect('/admin/panel')
        error = '❌ Sai tài khoản hoặc mật khẩu!'
    return render_template_string(ADMIN_LOGIN_TMPL, error=error)

@app.route('/admin/panel')
def admin_panel():
    if not session.get('is_admin'): return redirect('/admin')
    db = load_db()
    stats = {
        'users': len(db['users']), 'orders': len(db['orders']),
        'revenue': sum(db['revenue'].values()),
        'carry_orders': len(db.get('carry_orders', [])),
        'acc_kim': len([a for a in db['accounts'].get('kim_cuong', []) if not a.get('sold')]),
        'acc_bach': len([a for a in db['accounts'].get('bach_kim', []) if not a.get('sold')]),
        'acc_lv5': len([a for a in db['accounts'].get('lv5', []) if not a.get('sold')]),
        'acc_kim_total': len(db['accounts'].get('kim_cuong', [])),
        'acc_bach_total': len(db['accounts'].get('bach_kim', [])),
        'acc_lv5_total': len(db['accounts'].get('lv5', [])),
        'pending_topup': len([r for r in db.get('topup_requests', {}).values() if r.get('status') == 'pending']),
        'feedback_count': len(db.get('feedback_posts', []))
    }
    return render_template_string(ADMIN_PANEL_TMPL, db=db, stats=stats, ADMIN_TG_USERNAME=ADMIN_TG_USERNAME, TIKTOK_URL=TIKTOK_URL)

@app.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect('/admin')

@app.route('/admin/api/add-acc', methods=['POST'])
def admin_add_acc():
    if not session.get('is_admin'): return jsonify({'ok': False})
    db = load_db()
    cat = request.form.get('cat', '')
    bulk = request.form.get('bulk_accs', '').strip()
    added = 0
    if bulk:
        for line in bulk.split('\n'):
            line = line.strip()
            if not line: continue
            pp = [x.strip() for x in line.split(':')]
            if len(pp) < 2: continue
            acc = {
                'id': rand_id(10), 'user': pp[0], 'pass': pp[1],
                'platform': pp[2] if len(pp) > 2 else 'Facebook',
                'desc': pp[3] if len(pp) > 3 else '', 'added': now_vn(), 'sold': False
            }
            db['accounts'].setdefault(cat, []).append(acc)
            added += 1
    else:
        u = request.form.get('acc_user', '').strip()
        p = request.form.get('acc_pass', '').strip()
        platform = request.form.get('acc_platform', 'Facebook').strip()
        desc = request.form.get('acc_desc', '').strip()
        if u and p:
            acc = {'id': rand_id(10), 'user': u, 'pass': p, 'platform': platform, 'desc': desc, 'added': now_vn(), 'sold': False}
            db['accounts'].setdefault(cat, []).append(acc)
            added = 1
    add_log(db, 'Admin thêm acc', f'+{added} acc {cat}', 'admin')
    save_db(db)
    return jsonify({'ok': True, 'added': added})

@app.route('/admin/api/del-acc', methods=['POST'])
def admin_del_acc():
    if not session.get('is_admin'): return jsonify({'ok': False})
    db = load_db()
    cat = request.form.get('cat')
    acc_id = request.form.get('id')
    before = len(db['accounts'].get(cat, []))
    db['accounts'][cat] = [a for a in db['accounts'].get(cat, []) if a.get('id') != acc_id]
    save_db(db)
    return jsonify({'ok': True, 'removed': before - len(db['accounts'][cat])})

@app.route('/admin/api/balance', methods=['POST'])
def admin_balance():
    if not session.get('is_admin'): return jsonify({'ok': False})
    db = load_db()
    query = request.form.get('user', '').strip()
    action = request.form.get('action', 'add')
    try:
        amount = int(request.form.get('amount', 0))
    except:
        return jsonify({'ok': False, 'msg': 'Số tiền không hợp lệ'})
    if not query: return jsonify({'ok': False, 'msg': 'Vui lòng nhập tên user'})
    uid = _find_user(db, query)
    if not uid: return jsonify({'ok': False, 'msg': f'❌ Không tìm thấy user "{query}"'})
    old = db['users'][uid].get('balance', 0)
    if action == 'add':
        db['users'][uid]['balance'] = old + amount
        notif_msg = f'✅ Bạn được cộng {amount:,}đ vào tài khoản!'
    else:
        db['users'][uid]['balance'] = max(0, old - amount)
        notif_msg = f'⚠️ Tài khoản bị trừ {amount:,}đ.'
    db['users'][uid].setdefault('notifs', []).insert(0, {'type': 'balance', 'msg': notif_msg, 'time': now_vn()})
    add_log(db, f'Admin {action} tiền', f'{action} {amount:,}đ cho {db["users"][uid]["username"]}', 'admin')
    save_db(db)
    return jsonify({'ok': True, 'new_balance': db['users'][uid]['balance'], 'username': db['users'][uid]['username']})

@app.route('/admin/api/approve-topup', methods=['POST'])
def admin_approve_topup():
    if not session.get('is_admin'): return jsonify({'ok': False})
    content = request.form.get('content', '').strip()
    try:
        amount = int(request.form.get('amount', 0))
    except:
        amount = 0
    db = load_db()
    _do_approve_topup(db, content, amount if amount > 0 else None)
    return jsonify({'ok': True})

@app.route('/admin/api/reject-topup', methods=['POST'])
def admin_reject_topup():
    if not session.get('is_admin'): return jsonify({'ok': False})
    content = request.form.get('content', '').strip()
    db = load_db()
    req = db.get('topup_requests', {}).get(content)
    if req:
        req['status'] = 'rejected'
        uid = req.get('uid')
        if uid and uid in db['users']:
            db['users'][uid].setdefault('notifs', []).insert(0, {
                'type': 'admin', 'msg': f'❌ Yêu cầu nạp {req["amount"]:,}đ bị từ chối. Liên hệ admin.', 'time': now_vn()
            })
        save_db(db)
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'msg': 'Không tìm thấy'})

@app.route('/admin/api/notice', methods=['POST'])
def admin_notice():
    if not session.get('is_admin'): return jsonify({'ok': False})
    db = load_db()
    db['admin_notice'] = request.form.get('notice', '')
    db['notice_tg_link'] = request.form.get('tg_link', '').strip()
    db['notice_zalo_link'] = request.form.get('zalo_link', '').strip()
    db['notice_btn_desc'] = request.form.get('btn_desc', '').strip()
    save_db(db)
    return jsonify({'ok': True})

@app.route('/admin/api/approve-carry', methods=['POST'])
def admin_approve_carry():
    if not session.get('is_admin'): return jsonify({'ok': False})
    order_id = request.form.get('order_id', '').strip()
    db = load_db()
    for i, o in enumerate(db.get('carry_orders', [])):
        if o.get('id') == order_id:
            db['carry_orders'][i]['status'] = 'done'
            uid = o.get('uid')
            if uid and uid in db['users']:
                db['users'][uid].setdefault('notifs', []).insert(0, {
                    'type': 'carry',
                    'msg': f'✅ Đơn kéo thuê {o["stars"]} sao (rank {o["rank"]}) đã hoàn thành! Liên hệ admin để nhận kết quả.',
                    'time': now_vn()
                })
            add_log(db, 'Admin duyệt kéo thuê', f'{o["username"]} - {o["stars"]} sao rank {o["rank"]}', 'admin')
            save_db(db)
            return jsonify({'ok': True})
    return jsonify({'ok': False, 'msg': 'Không tìm thấy đơn'})

@app.route('/admin/api/send-msg', methods=['POST'])
def admin_send_msg():
    if not session.get('is_admin'): return jsonify({'ok': False})
    db = load_db()
    query = request.form.get('user', '').strip()
    msg_text = request.form.get('msg', '').strip()
    if not query: return jsonify({'ok': False, 'msg': 'Nhập tên user'})
    uid = _find_user(db, query)
    if not uid: return jsonify({'ok': False, 'msg': f'❌ Không tìm thấy user "{query}"'})
    db['users'][uid].setdefault('notifs', []).insert(0, {'type': 'admin', 'msg': msg_text, 'time': now_vn()})
    save_db(db)
    return jsonify({'ok': True})

@app.route('/admin/api/del-user', methods=['POST'])
def admin_del_user():
    if not session.get('is_admin'): return jsonify({'ok': False})
    db = load_db()
    uid = request.form.get('uid', '')
    if uid in db['users']:
        uname = db['users'][uid].get('username', uid)
        del db['users'][uid]
        add_log(db, 'Admin xóa user', uname, 'admin')
        save_db(db)
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'msg': 'Không tìm thấy'})

@app.route('/admin/api/logs')
def admin_logs_api():
    if not session.get('is_admin'): return jsonify({'ok': False})
    db = load_db()
    page = int(request.args.get('page', 1))
    per = 50
    logs = db.get('logs', [])
    total = len(logs)
    start = (page - 1) * per
    return jsonify({'ok': True, 'logs': logs[start:start+per], 'total': total, 'pages': (total + per - 1) // per})

@app.route('/admin/api/add-feedback', methods=['POST'])
def admin_add_feedback():
    if not session.get('is_admin'): return jsonify({'ok': False})
    desc = request.form.get('desc', '').strip()
    customer = request.form.get('customer', '').strip()
    media_url = request.form.get('media_url', '').strip()
    media_type = 'image'
    allowed_img = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
    allowed_vid = {'.mp4', '.webm', '.mov'}
    file = request.files.get('media_file')
    if file and file.filename:
        fname_raw = secure_filename(file.filename)
        ext = os.path.splitext(fname_raw)[1].lower()
        if ext in allowed_img or ext in allowed_vid:
            unique_name = 'fb_' + rand_id(12) + ext
            save_path = os.path.join(BASE_DIR, unique_name)
            file.save(save_path)
            media_url = '/' + unique_name
            media_type = 'video' if ext in allowed_vid else 'image'
    elif media_url:
        ext = os.path.splitext(media_url.split('?')[0])[1].lower()
        media_type = 'video' if ext in allowed_vid else 'image'
    if not media_url and not desc:
        return jsonify({'ok': False, 'msg': 'Cần nhập mô tả hoặc đính kèm ảnh/video'})
    db = load_db()
    post = {
        'id': 'FB' + rand_id(10),
        'media_url': media_url,
        'media_type': media_type,
        'desc': desc,
        'customer': customer,
        'time': now_vn()
    }
    db.setdefault('feedback_posts', []).insert(0, post)
    if len(db['feedback_posts']) > 50:
        db['feedback_posts'] = db['feedback_posts'][:50]
    add_log(db, 'Admin thêm feedback', f'{desc[:30] if desc else media_url[:30]}', 'admin')
    save_db(db)
    return jsonify({'ok': True, 'id': post['id']})

@app.route('/admin/api/del-feedback', methods=['POST'])
def admin_del_feedback():
    if not session.get('is_admin'): return jsonify({'ok': False})
    post_id = request.form.get('id', '')
    db = load_db()
    posts = db.get('feedback_posts', [])
    post_to_del = next((p for p in posts if p.get('id') == post_id), None)
    if post_to_del:
        media_url = post_to_del.get('media_url', '')
        if media_url and media_url.startswith('/fb_'):
            fpath = os.path.join(BASE_DIR, media_url.lstrip('/'))
            if os.path.isfile(fpath):
                try:
                    os.remove(fpath)
                except:
                    pass
    db['feedback_posts'] = [p for p in posts if p.get('id') != post_id]
    add_log(db, 'Admin xóa feedback', post_id, 'admin')
    save_db(db)
    return jsonify({'ok': True})

# ── CUSTOM ACC API ─────────────────────────────────────────────────────────────
@app.route('/api/custom-accs')
def api_custom_accs():
    db = load_db()
    accs = db.get('custom_accs', [])
    try:
        page = max(1, int(request.args.get('page', 1)))
    except Exception:
        page = 1
    per_page = 5
    total = len(accs)
    total_pages = max(1, math.ceil(total / per_page))
    start = (page - 1) * per_page
    page_accs = accs[start:start + per_page]
    safe = []
    for a in page_accs:
        safe.append({
            'id': a.get('id', ''),
            'image_url': a.get('image_url', ''),
            'platform': a.get('platform', ''),
            'desc': a.get('desc', ''),
            'price': a.get('price', 0),
            'added': a.get('added', '')
        })
    return jsonify({'ok': True, 'accs': safe, 'total': total, 'page': page, 'total_pages': total_pages})

@app.route('/admin/api/add-custom-acc', methods=['POST'])
def admin_add_custom_acc():
    if not session.get('is_admin'):
        return jsonify({'ok': False})
    allowed_img = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
    image_url = request.form.get('image_url', '').strip()
    file = request.files.get('image_file')
    if file and file.filename:
        fname_raw = secure_filename(file.filename)
        ext = os.path.splitext(fname_raw)[1].lower()
        if ext in allowed_img:
            unique_name = 'ca_' + rand_id(12) + ext
            save_path = os.path.join(BASE_DIR, unique_name)
            file.save(save_path)
            image_url = '/' + unique_name
    acc_user = request.form.get('acc_user', '').strip()
    acc_pass = request.form.get('acc_pass', '').strip()
    platform = request.form.get('platform', '').strip()
    desc = request.form.get('desc', '').strip()
    try:
        price = int(request.form.get('price', 0))
    except Exception:
        price = 0
    if not platform and not desc:
        return jsonify({'ok': False, 'msg': 'Cần nhập platform hoặc mô tả'})
    acc = {
        'id': 'CA' + rand_id(10),
        'image_url': image_url,
        'acc_user': acc_user,
        'acc_pass': acc_pass,
        'platform': platform,
        'desc': desc,
        'price': price,
        'added': now_vn()
    }
    db = load_db()
    db.setdefault('custom_accs', []).insert(0, acc)
    add_log(db, 'Admin thêm acc tự chọn', f'{platform} | {price:,}đ', 'admin')
    save_db(db)
    return jsonify({'ok': True, 'id': acc['id']})

@app.route('/admin/api/del-custom-acc', methods=['POST'])
def admin_del_custom_acc():
    if not session.get('is_admin'):
        return jsonify({'ok': False})
    acc_id = request.form.get('id', '')
    db = load_db()
    accs = db.get('custom_accs', [])
    acc_to_del = next((a for a in accs if a.get('id') == acc_id), None)
    if acc_to_del:
        iu = acc_to_del.get('image_url', '')
        if iu and iu.startswith('/ca_'):
            fpath = os.path.join(BASE_DIR, iu.lstrip('/'))
            if os.path.isfile(fpath):
                try:
                    os.remove(fpath)
                except Exception:
                    pass
    db['custom_accs'] = [a for a in accs if a.get('id') != acc_id]
    add_log(db, 'Admin xóa acc tự chọn', acc_id, 'admin')
    save_db(db)
    return jsonify({'ok': True})

@app.route('/api/check-code', methods=['POST'])
def api_check_code():
    uid = session.get('uid')
    if not uid:
        return jsonify({'ok': False, 'msg': 'Chưa đăng nhập'})
    code = request.form.get('code', '').strip().upper()
    if not code:
        return jsonify({'ok': False, 'msg': 'Nhập mã giảm giá'})
    db = load_db()
    code_data = db.get('discount_codes', {}).get(code)
    if not code_data:
        return jsonify({'ok': False, 'msg': '❌ Mã không tồn tại'})
    if code_data.get('expires_at', 0) != 0 and time.time() > code_data['expires_at']:
        return jsonify({'ok': False, 'msg': '❌ Mã đã hết hạn'})
    if uid in code_data.get('used_by', []):
        return jsonify({'ok': False, 'msg': '❌ Bạn đã dùng mã này rồi'})
    pct = code_data['discount_pct']
    return jsonify({'ok': True, 'discount_pct': pct, 'msg': f'✅ Mã hợp lệ! Giảm {pct}%'})

@app.route('/api/buy-custom-acc', methods=['POST'])
def api_buy_custom_acc():
    uid = session.get('uid')
    if not uid:
        return jsonify({'ok': False, 'msg': 'Chưa đăng nhập'})
    acc_id = request.form.get('acc_id', '').strip()
    discount_code = request.form.get('code', '').strip().upper()
    db = load_db()
    u = db['users'].get(uid)
    if not u:
        return jsonify({'ok': False, 'msg': 'Không tìm thấy tài khoản'})
    acc = next((a for a in db.get('custom_accs', []) if a.get('id') == acc_id), None)
    if not acc:
        return jsonify({'ok': False, 'msg': 'Acc không tồn tại'})
    price = acc.get('price', 0)
    if price <= 0:
        return jsonify({'ok': False, 'msg': 'Acc chưa có giá. Liên hệ admin!'})
    discount_pct = 0
    if discount_code:
        cdata = db.get('discount_codes', {}).get(discount_code)
        if not cdata:
            return jsonify({'ok': False, 'msg': '❌ Mã giảm giá không tồn tại'})
        if cdata.get('expires_at', 0) != 0 and time.time() > cdata['expires_at']:
            return jsonify({'ok': False, 'msg': '❌ Mã giảm giá đã hết hạn'})
        if uid in cdata.get('used_by', []):
            return jsonify({'ok': False, 'msg': '❌ Bạn đã dùng mã này rồi'})
        discount_pct = cdata.get('discount_pct', 0)
    final_price = int(price * (1 - discount_pct / 100))
    if u.get('balance', 0) < final_price:
        short = final_price - u.get('balance', 0)
        return jsonify({'ok': False, 'msg': f'Số dư không đủ! Cần {final_price:,}đ', 'need_topup': True, 'short': short, 'needed': final_price})
    db['users'][uid]['balance'] = u.get('balance', 0) - final_price
    if discount_code and discount_code in db.get('discount_codes', {}):
        db['discount_codes'][discount_code].setdefault('used_by', []).append(uid)
    order_id = 'TC' + rand_id(8)
    db.setdefault('orders', []).append({
        'id': order_id, 'uid': uid, 'username': u['username'],
        'cat': 'custom', 'cat_name': f"Acc Tự Chọn ({acc.get('platform','')})",
        'qty': 1, 'total': final_price,
        'accs': [{'id': acc_id, 'user': acc.get('acc_user', '?'), 'pass': acc.get('acc_pass', '?'),
                  'platform': acc.get('platform', ''), 'desc': acc.get('desc', '')}],
        'time': now_vn(), 'custom_acc_id': acc_id,
        'discount_code': discount_code, 'original_price': price, 'discount_pct': discount_pct
    })
    month_key = datetime.now(VN_TZ).strftime('%Y-%m')
    db['revenue'][month_key] = db['revenue'].get(month_key, 0) + final_price
    add_log(db, 'Mua acc tự chọn', f"{u['username']} | {acc.get('platform','')} | {final_price:,}đ", u['username'])
    db['users'][uid].setdefault('notifs', []).insert(0, {
        'type': 'purchase',
        'msg': f"✅ Mua acc tự chọn {acc.get('platform','')} thành công! Trừ {final_price:,}đ. Liên hệ admin để nhận acc.",
        'time': now_vn()
    })
    save_db(db)
    dis_note = f'\n🎟️ Mã GG: {discount_code} (giảm {discount_pct}% từ {price:,}đ)' if discount_pct else ''

    return jsonify({'ok': True, 'total': final_price, 'new_balance': db['users'][uid]['balance'],
                    'order_id': order_id, 'tg_link': f'https://t.me/{ADMIN_TG_USERNAME}',
                    'zalo_url': ZALO_URL, 'tiktok_url': TIKTOK_URL,
                    'discount_pct': discount_pct, 'original_price': price})

@app.route('/admin/api/add-discount-code', methods=['POST'])
def admin_add_discount_code():
    if not session.get('is_admin'):
        return jsonify({'ok': False})
    code = request.form.get('code', '').strip().upper()
    if not code:
        code = 'SALE' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    try:
        discount_pct = int(request.form.get('discount_pct', 0))
    except Exception:
        discount_pct = 0
    if discount_pct <= 0 or discount_pct > 100:
        return jsonify({'ok': False, 'msg': 'Phần trăm giảm phải từ 1–100'})
    duration = request.form.get('duration', 'forever').strip()
    expires_at = 0
    duration_label = 'Vĩnh viễn'
    now_ts = time.time()
    if duration == '24h':
        expires_at, duration_label = now_ts + 86400, '24 Giờ'
    elif duration == '5d':
        expires_at, duration_label = now_ts + 5 * 86400, '5 Ngày'
    elif duration == '10d':
        expires_at, duration_label = now_ts + 10 * 86400, '10 Ngày'
    elif duration == '30d':
        expires_at, duration_label = now_ts + 30 * 86400, '30 Ngày'
    elif duration == 'custom':
        try:
            h = int(request.form.get('custom_hours', 0))
        except Exception:
            h = 0
        if h > 0:
            expires_at, duration_label = now_ts + h * 3600, f'{h} Giờ'
    db = load_db()
    db.setdefault('discount_codes', {})
    if code in db['discount_codes']:
        return jsonify({'ok': False, 'msg': 'Mã này đã tồn tại!'})
    expires_at_str = datetime.fromtimestamp(expires_at, tz=VN_TZ).strftime('%d/%m/%Y %H:%M') if expires_at else ''
    db['discount_codes'][code] = {
        'code': code, 'discount_pct': discount_pct, 'expires_at': expires_at,
        'expires_at_str': expires_at_str,
        'duration_label': duration_label, 'used_by': [], 'created': now_vn()
    }
    add_log(db, 'Admin tạo mã giảm giá', f'{code} | {discount_pct}% | {duration_label}', 'admin')
    save_db(db)
    return jsonify({'ok': True, 'code': code})

@app.route('/admin/api/del-discount-code', methods=['POST'])
def admin_del_discount_code():
    if not session.get('is_admin'):
        return jsonify({'ok': False})
    code = request.form.get('code', '').strip().upper()
    db = load_db()
    if code in db.get('discount_codes', {}):
        del db['discount_codes'][code]
        add_log(db, 'Admin xóa mã giảm giá', code, 'admin')
        save_db(db)
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'msg': 'Không tìm thấy mã'})

# ══════════════════════════════════════════════════════════════════════════════
# TEMPLATES
# ══════════════════════════════════════════════════════════════════════════════
BASE_CSS = """
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:'Be Vietnam Pro',sans-serif;-webkit-tap-highlight-color:transparent;}
:root{--bg:#f8f9fb;--white:#fff;--primary:#1a1a2e;--accent:#4f46e5;--accent2:#7c3aed;--green:#10b981;--red:#ef4444;--orange:#f59e0b;--text:#1f2937;--muted:#6b7280;--border:#e5e7eb;--sh:0 4px 24px rgba(0,0,0,.08);}
html{scroll-behavior:smooth;}
body{background:var(--bg);color:var(--text);min-height:100vh;overflow-x:hidden;-webkit-font-smoothing:antialiased;}
a{text-decoration:none;color:inherit;}

/* LOADING */
#ls{position:fixed;inset:0;background:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:9999;transition:opacity .4s ease;}
.ls-logo{font-size:2rem;font-weight:800;color:var(--primary);margin-bottom:1rem;}
.ls-logo span{color:var(--accent);}
.ls-bar{width:200px;height:3px;background:#e5e7eb;border-radius:9px;overflow:hidden;margin-bottom:1.5rem;}
.ls-fill{height:100%;width:0;background:linear-gradient(90deg,var(--accent),var(--accent2));border-radius:9px;animation:lsfill .8s ease forwards;}
@keyframes lsfill{0%{width:0}60%{width:75%}100%{width:100%}}
.ls-text{color:var(--muted);font-size:.85rem;font-weight:500;}

/* NAVBAR */
.navbar{position:fixed;top:0;left:0;right:0;background:rgba(255,255,255,.95);backdrop-filter:blur(12px);border-bottom:1px solid var(--border);height:58px;display:flex;align-items:center;padding:0 1.1rem;z-index:1000;gap:.75rem;}
.nav-logo{font-size:1.1rem;font-weight:800;color:var(--primary);flex:1;}
.nav-logo span{color:var(--accent);}
.nav-bal{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;padding:.28rem .85rem;border-radius:20px;font-size:.78rem;font-weight:700;cursor:pointer;white-space:nowrap;transition:transform .15s ease,box-shadow .15s ease;}
.nav-bal:active{transform:scale(.94);}
.nav-bell{cursor:pointer;width:36px;height:36px;display:flex;align-items:center;justify-content:center;border-radius:10px;background:#f3f4f6;position:relative;flex-shrink:0;transition:transform .15s ease;}
.nav-bell:active{transform:scale(.9);}
.notif-dot{position:absolute;top:4px;right:4px;width:7px;height:7px;background:var(--red);border-radius:50%;display:none;}
.hamburger{cursor:pointer;padding:.35rem;display:flex;flex-direction:column;gap:5px;transition:transform .15s ease;}
.hamburger span{display:block;width:21px;height:2px;background:var(--primary);border-radius:2px;transition:.3s;}
.hamburger:active{transform:scale(.9);}

/* DRAWER — slides from LEFT */
.doverlay{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:2000;opacity:0;pointer-events:none;transition:opacity .28s ease;backdrop-filter:blur(3px);}
.doverlay.open{opacity:1;pointer-events:all;}
.drawer{position:fixed;top:0;left:-270px;bottom:0;width:258px;background:#fff;z-index:2001;transition:left .28s cubic-bezier(.4,0,.2,1);display:flex;flex-direction:column;box-shadow:4px 0 40px rgba(0,0,0,.14);will-change:transform;}
.drawer.open{left:0;}
.dhead{padding:1.4rem 1.2rem 1rem;border-bottom:1px solid var(--border);}
.dhead h3{font-size:1.05rem;font-weight:800;color:var(--primary);}
.dhead p{font-size:.75rem;color:var(--muted);margin-top:.15rem;}
.dmenu{flex:1;padding:.75rem 0;overflow-y:auto;}
.ditem{display:flex;align-items:center;gap:.85rem;padding:.8rem 1.2rem;cursor:pointer;transition:background .15s ease,border-left-color .15s ease;border-left:3px solid transparent;}
.ditem:active,.ditem.active{background:#f3f4f6;border-left-color:var(--accent);}
.ditem svg{width:19px;height:19px;color:var(--accent);flex-shrink:0;}
.ditem span{font-weight:600;font-size:.88rem;color:var(--text);}
.dfooter{padding:.9rem 1.2rem;border-top:1px solid var(--border);}
.tg-btn{display:flex;align-items:center;gap:.55rem;background:linear-gradient(135deg,#0088cc,#006699);color:#fff;padding:.7rem .9rem;border-radius:12px;font-weight:600;font-size:.82rem;cursor:pointer;border:none;width:100%;justify-content:center;transition:transform .15s ease;}
.tg-btn:active{transform:scale(.97);}
.tg-btn svg{width:18px;height:18px;fill:#fff;}

/* CONTENT */
.content{padding-top:58px;min-height:100vh;}
.page{display:none;padding:1.1rem;opacity:0;transform:translateY(10px);transition:opacity .25s ease,transform .25s ease;}
.page.active{display:block;}
.page.visible{opacity:1;transform:translateY(0);}

/* CARDS */
.card{background:#fff;border-radius:16px;padding:1.1rem;box-shadow:var(--sh);border:1px solid var(--border);}
.card-title{font-size:.95rem;font-weight:700;color:var(--primary);margin-bottom:.9rem;}

/* BUTTONS */
.btn{display:inline-flex;align-items:center;justify-content:center;gap:.4rem;padding:.65rem 1.3rem;border-radius:12px;font-weight:600;font-size:.85rem;cursor:pointer;border:none;transition:transform .15s ease,box-shadow .15s ease;line-height:1;will-change:transform;}
.btn:active{transform:scale(.95);}
.btn-primary{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;box-shadow:0 4px 15px rgba(79,70,229,.3);}
.btn-primary:active{box-shadow:0 2px 8px rgba(79,70,229,.2);}
.btn-green{background:var(--green);color:#fff;}
.btn-red{background:var(--red);color:#fff;}
.btn-outline{background:transparent;border:1.5px solid var(--border);color:var(--text);}
.btn-tg{background:linear-gradient(135deg,#0088cc,#006699);color:#fff;}
.btn-tt{background:linear-gradient(135deg,#010101,#333);color:#fff;}
.btn-zalo{background:linear-gradient(135deg,#006af5,#0043a0);color:#fff;}
.btn-sm{padding:.4rem .85rem;font-size:.78rem;border-radius:9px;}
.btn-full{width:100%;}

/* FLOAT NOTICE */
#fn{position:fixed;bottom:72px;left:50%;transform:translateX(-50%);background:#fff;border:1px solid var(--border);border-radius:16px;padding:.9rem 1.1rem;max-width:340px;width:92%;box-shadow:0 8px 40px rgba(0,0,0,.14);z-index:500;display:none;}
#fn.show{display:block;animation:slideUp .4s cubic-bezier(.34,1.56,.64,1);}
@keyframes slideUp{from{opacity:0;transform:translateX(-50%) translateY(24px)}to{opacity:1;transform:translateX(-50%) translateY(0)}}
.fn-top{display:flex;justify-content:space-between;align-items:flex-start;gap:.5rem;margin-bottom:.4rem;}
.fn-admin{display:flex;align-items:center;gap:.5rem;}
.fn-admin-img{width:30px;height:30px;border-radius:50%;object-fit:cover;border:2px solid var(--accent);}
.fn-title{font-weight:700;font-size:.88rem;color:var(--primary);}
.fn-close{cursor:pointer;color:var(--muted);font-size:1.2rem;line-height:1;padding:.1rem;transition:.15s;}
.fn-body{font-size:.8rem;color:var(--text);line-height:1.5;}
.fn-actions{display:flex;gap:.5rem;margin-top:.65rem;}

/* SUCCESS TOAST */
#st-overlay{position:fixed;inset:0;background:rgba(0,0,0,.35);z-index:9998;display:none;}
#st{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%) scale(.8);background:#fff;border-radius:20px;padding:1.75rem 2.25rem;text-align:center;z-index:9999;display:none;box-shadow:0 20px 60px rgba(0,0,0,.15);min-width:190px;}
#st.show{display:flex;flex-direction:column;align-items:center;animation:stIn .3s cubic-bezier(.34,1.56,.64,1) forwards;}
@keyframes stIn{from{transform:translate(-50%,-50%) scale(.8);opacity:0}to{transform:translate(-50%,-50%) scale(1);opacity:1}}
.st-check{width:52px;height:52px;border-radius:50%;background:var(--green);display:flex;align-items:center;justify-content:center;margin-bottom:.7rem;animation:checkPop .35s .1s cubic-bezier(.34,1.56,.64,1) both;}
@keyframes checkPop{from{transform:scale(0)}to{transform:scale(1)}}
.st-check svg{width:26px;height:26px;color:#fff;}
.st-msg{font-weight:700;font-size:.92rem;color:var(--primary);}
.st-sub{font-size:.76rem;color:var(--muted);margin-top:.2rem;}

/* ERROR TOAST */
#et{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%) scale(.8);background:#fff;border-radius:20px;padding:1.75rem 2.25rem;text-align:center;z-index:9999;display:none;box-shadow:0 20px 60px rgba(0,0,0,.15);min-width:190px;}
#et.show{display:flex;flex-direction:column;align-items:center;animation:stIn .3s cubic-bezier(.34,1.56,.64,1) forwards;}
.et-x{width:52px;height:52px;border-radius:50%;background:var(--red);display:flex;align-items:center;justify-content:center;margin-bottom:.7rem;animation:checkPop .35s .1s cubic-bezier(.34,1.56,.64,1) both;}
.et-x svg{width:26px;height:26px;color:#fff;}
.et-msg{font-weight:700;font-size:.92rem;color:var(--primary);}
.et-sub{font-size:.76rem;color:var(--muted);margin-top:.2rem;}

/* ADMIN AVATAR */
.av-wrap{display:inline-block;position:relative;width:80px;height:80px;}
.av-img{width:80px;height:80px;border-radius:50%;object-fit:cover;border:3px solid var(--accent);display:block;}

/* RAINBOW BORDER ANIMATION */
@keyframes rainbowBg{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
.rainbow-wrap{padding:3px;border-radius:14px;background:linear-gradient(270deg,#ff0000,#ff7700,#ffff00,#00ff00,#00cfff,#7c3aed,#ff00ff,#ff0000);background-size:400% 400%;animation:rainbowBg 3s ease infinite;}
.rainbow-wrap img,.rainbow-wrap video{border-radius:11px;display:block;width:100%;}

/* ACC CARD */
.acc-card{background:#fff;border-radius:14px;overflow:hidden;box-shadow:var(--sh);border:1px solid var(--border);transition:transform .2s ease,box-shadow .2s ease;}
.acc-card:active{transform:scale(.99);}
.acc-body{padding:.9rem;}
.acc-badge{display:inline-block;padding:.18rem .55rem;border-radius:20px;font-size:.68rem;font-weight:700;margin-bottom:.4rem;background:linear-gradient(135deg,var(--green),#059669);color:#fff;}
.acc-title{font-weight:700;font-size:.9rem;color:var(--primary);margin-bottom:.2rem;}
.acc-desc{font-size:.73rem;color:var(--muted);margin-bottom:.45rem;line-height:1.4;}
.acc-price{font-size:1.05rem;font-weight:800;color:var(--accent);}
.acc-stock{font-size:.73rem;margin-top:.2rem;}
.acc-stock.s-ok{color:var(--green);}
.acc-stock.s-low{color:var(--orange);}
.acc-stock.s-empty{color:var(--red);font-weight:700;}

/* MUSIC */
.music-disc{width:185px;height:185px;border-radius:50%;margin:0 auto 1.25rem;}
.music-disc.playing{animation:discSpin 7s linear infinite;}
@keyframes discSpin{to{transform:rotate(360deg)}}
.disc-bg{width:100%;height:100%;border-radius:50%;background:conic-gradient(from 0deg,#1a1a2e,#4f46e5,#7c3aed,#1a1a2e);display:flex;align-items:center;justify-content:center;box-shadow:0 8px 40px rgba(79,70,229,.3);}
.disc-center{width:55px;height:55px;border-radius:50%;background:#fff;border:3px solid var(--border);}
.music-seek{width:100%;-webkit-appearance:none;height:4px;border-radius:9px;background:var(--border);outline:none;cursor:pointer;}
.music-seek::-webkit-slider-thumb{-webkit-appearance:none;width:14px;height:14px;border-radius:50%;background:var(--accent);}
.mc-btn{width:42px;height:42px;border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer;border:none;background:#f3f4f6;transition:transform .15s ease;}
.mc-btn:active{transform:scale(.9);}
.mc-play{width:54px;height:54px;background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;box-shadow:0 4px 20px rgba(79,70,229,.3);}
.mc-btn svg{width:19px;height:19px;}
.mc-play svg{width:22px;height:22px;}
.pl-item{display:flex;align-items:center;gap:.7rem;padding:.65rem .7rem;border-radius:11px;cursor:pointer;transition:background .15s ease;margin-bottom:.2rem;}
.pl-item:active,.pl-item.active{background:#f3f4f6;}
.pl-item.active{border-left:3px solid var(--accent);padding-left:.5rem;}

/* FORM */
.fg{margin-bottom:.85rem;}
.fl{display:block;font-size:.75rem;font-weight:700;color:var(--muted);margin-bottom:.35rem;text-transform:uppercase;letter-spacing:.04em;}
.fi{width:100%;padding:.7rem .9rem;border:1.5px solid var(--border);border-radius:11px;font-size:.88rem;background:#fff;outline:none;transition:border-color .15s ease,box-shadow .15s ease;}
.fi:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(79,70,229,.1);}
.fsel{width:100%;padding:.7rem .9rem;border:1.5px solid var(--border);border-radius:11px;font-size:.88rem;background:#fff;outline:none;cursor:pointer;transition:border-color .15s ease;}
.fsel:focus{border-color:var(--accent);}
textarea.fi{min-height:75px;resize:vertical;font-family:monospace;}

/* TABS */
.tabs{display:flex;gap:.2rem;background:#f3f4f6;padding:.28rem;border-radius:11px;margin-bottom:1.1rem;}
.tab{flex:1;padding:.5rem;border-radius:8px;text-align:center;font-size:.78rem;font-weight:600;cursor:pointer;transition:all .2s ease;color:var(--muted);}
.tab.active{background:#fff;color:var(--accent);box-shadow:0 2px 8px rgba(0,0,0,.07);}

/* PROFILE */
.info-row{display:flex;justify-content:space-between;align-items:center;padding:.48rem 0;border-bottom:1px solid var(--border);}
.info-row:last-child{border-bottom:none;}
.ik{font-size:.8rem;color:var(--muted);font-weight:500;}
.iv{font-size:.82rem;font-weight:600;color:var(--text);}

/* MODAL */
.modal-ov{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:3000;display:none;align-items:center;justify-content:center;padding:1rem;backdrop-filter:blur(4px);}
.modal-ov.show{display:flex;animation:fadeIn .2s ease;}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
.modal{background:#fff;border-radius:20px;padding:1.4rem;width:100%;max-width:380px;box-shadow:0 20px 60px rgba(0,0,0,.18);animation:mIn .25s cubic-bezier(.34,1.56,.64,1);}
@keyframes mIn{from{transform:scale(.88);opacity:0}to{transform:scale(1);opacity:1}}
.modal-title{font-size:1rem;font-weight:700;margin-bottom:.9rem;color:var(--primary);}

/* CAPTCHA */
.cap-box{background:#f3f4f6;border:1.5px solid var(--border);border-radius:11px;padding:.65rem .9rem;display:flex;align-items:center;gap:.75rem;margin-bottom:.9rem;}
.cap-q{font-size:1.05rem;font-weight:700;color:var(--primary);flex:1;}
.cap-input{width:65px;padding:.45rem;border:1.5px solid var(--border);border-radius:8px;font-size:.95rem;text-align:center;font-weight:700;outline:none;}
.cap-input:focus{border-color:var(--accent);}

/* SUPPORT */
.support-card{background:linear-gradient(135deg,#0088cc15,#00669910);border:1.5px solid #0088cc30;border-radius:16px;padding:1.2rem;text-align:center;}

/* NOTIF PANEL */
.notif-item{display:flex;gap:.7rem;padding:.75rem 0;border-bottom:1px solid var(--border);}
.notif-item:last-child{border:none;}
.notif-avatar{width:36px;height:36px;border-radius:50%;object-fit:cover;flex-shrink:0;}
.notif-body{flex:1;}
.notif-msg{font-size:.83rem;color:var(--text);font-weight:500;line-height:1.4;}
.notif-time{font-size:.7rem;color:var(--muted);margin-top:.2rem;}

/* TOPUP QR */
.qr-box{background:#f8f9fb;border-radius:14px;padding:1rem;text-align:center;border:1px solid var(--border);}
.qr-box img{width:180px;height:180px;object-fit:contain;border-radius:10px;}
.content-box{background:linear-gradient(135deg,#eef2ff,#f5f3ff);border:2px dashed var(--accent);border-radius:12px;padding:.9rem;text-align:center;margin:.9rem 0;}
.content-code{font-family:monospace;font-size:1.1rem;font-weight:800;color:var(--accent);letter-spacing:.05em;}
.timer-box{display:flex;align-items:center;gap:.5rem;justify-content:center;font-size:.8rem;color:var(--orange);font-weight:600;}

/* HISTORY TABLE */
.hist-table{width:100%;border-collapse:collapse;font-size:.78rem;}
.hist-table th{background:#f3f4f6;padding:.45rem .6rem;text-align:left;font-weight:600;color:var(--muted);font-size:.7rem;}
.hist-table td{padding:.5rem .6rem;border-bottom:1px solid var(--border);vertical-align:top;}
.hist-table tr:last-child td{border:none;}
.badge-ok{display:inline-block;background:#d1fae5;color:#065f46;padding:.1rem .45rem;border-radius:20px;font-size:.66rem;font-weight:700;}
.badge-pend{display:inline-block;background:#fef3c7;color:#92400e;padding:.1rem .45rem;border-radius:20px;font-size:.66rem;font-weight:700;}
.badge-rej{display:inline-block;background:#fee2e2;color:#991b1b;padding:.1rem .45rem;border-radius:20px;font-size:.66rem;font-weight:700;}

/* CARRY PRICE DISPLAY */
.carry-price-box{background:linear-gradient(135deg,#eef2ff,#f5f3ff);border:2px solid var(--accent);border-radius:12px;padding:1rem;text-align:center;margin:.9rem 0;}
.carry-price-total{font-size:1.4rem;font-weight:800;color:var(--accent);}
.carry-price-note{font-size:.75rem;color:var(--muted);margin-top:.2rem;}

/* HOME HERO */
.hero-section{background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);border-radius:20px;padding:1.4rem;margin-bottom:1rem;color:#fff;position:relative;overflow:hidden;}
.hero-section::before{content:'';position:absolute;inset:0;background:url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23ffffff' fill-opacity='0.03'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E");}

/* QUICK ACTION CARDS */
.quick-card{background:#fff;border-radius:14px;padding:.85rem .5rem;text-align:center;box-shadow:var(--sh);border:1px solid var(--border);cursor:pointer;transition:transform .15s ease,box-shadow .15s ease;}
.quick-card:active{transform:scale(.94);box-shadow:none;}

/* SERVICE CARDS */
.service-card{border-radius:14px;padding:1rem;border:1px solid var(--border);display:flex;align-items:center;gap:.9rem;cursor:pointer;transition:transform .15s ease;}
.service-card:active{transform:scale(.97);}

/* FEEDBACK CARD */
.feedback-post{margin-bottom:.9rem;padding-bottom:.9rem;border-bottom:1px solid var(--border);}
.feedback-post:last-child{margin-bottom:0;padding-bottom:0;border-bottom:none;}

/* SCROLLBAR */
::-webkit-scrollbar{width:3px;}
::-webkit-scrollbar-thumb{background:#d1d5db;border-radius:9px;}
</style>
"""

BASE_JS = """
<script>
function showToast(msg,sub){
  const t=document.getElementById('st'),o=document.getElementById('st-overlay');
  if(!t)return;
  t.querySelector('.st-msg').textContent=msg||'Thành công!';
  t.querySelector('.st-sub').textContent=sub||'';
  t.classList.add('show');o.style.display='block';
  setTimeout(()=>{t.classList.remove('show');o.style.display='none';},2200);
}
function showError(msg,sub){
  const t=document.getElementById('et'),o=document.getElementById('st-overlay');
  if(!t){alert(msg);return;}
  t.querySelector('.et-msg').textContent=msg||'Có lỗi xảy ra!';
  t.querySelector('.et-sub').textContent=sub||'';
  t.classList.add('show');o.style.display='block';
  setTimeout(()=>{t.classList.remove('show');o.style.display='none';},2500);
}
function copyText(txt,label){
  navigator.clipboard.writeText(txt).then(()=>showToast('Đã sao chép!',label||'')).catch(()=>{
    const ta=document.createElement('textarea');ta.value=txt;document.body.appendChild(ta);ta.select();document.execCommand('copy');document.body.removeChild(ta);showToast('Đã sao chép!',label||'');
  });
}
function openDrawer(){
  document.getElementById('drawer').classList.add('open');
  document.getElementById('doverlay').classList.add('open');
}
function closeDrawer(){
  document.getElementById('drawer').classList.remove('open');
  document.getElementById('doverlay').classList.remove('open');
}
let _curPage='home';
function showPage(id,el){
  if(_curPage===id){closeDrawer();return;}
  const prev=document.getElementById('pg-'+_curPage);
  if(prev){prev.classList.remove('visible');setTimeout(()=>{prev.classList.remove('active');prev.style.display='';},250);}
  document.querySelectorAll('.ditem').forEach(i=>i.classList.remove('active'));
  const pg=document.getElementById('pg-'+id);
  if(pg){
    pg.style.display='block';
    requestAnimationFrame(()=>{
      pg.classList.add('active');
      requestAnimationFrame(()=>pg.classList.add('visible'));
    });
  }
  if(el)el.classList.add('active');
  _curPage=id;
  closeDrawer();
  if(id==='music')initDisc();
  if(id==='profile')loadProfile();
  if(id==='notifs')loadNotifs();
  if(id==='topup')loadMyTopups();
  if(id==='carry')loadMyCarries();
  if(id==='tuchon')loadTuchon(1);
}
function updateBalance(){
  fetch('/api/balance').then(r=>r.json()).then(d=>{
    if(!d.ok)return;
    const b=document.getElementById('nav-bal');
    if(b)b.textContent=d.balance.toLocaleString('vi-VN')+'đ';
    if(d.new_notifs>0){const dot=document.getElementById('notif-dot');if(dot)dot.style.display='block';}
  }).catch(()=>{});
}
function loadNotifs(){
  fetch('/api/notifs').then(r=>r.json()).then(d=>{
    const dot=document.getElementById('notif-dot');if(dot)dot.style.display='none';
    const box=document.getElementById('notif-list');if(!box)return;
    if(!d.ok||!d.notifs||!d.notifs.length){
      box.innerHTML='<div style="text-align:center;color:var(--muted);padding:2rem;font-size:.85rem;">📭 Chưa có thông báo nào</div>';return;
    }
    box.innerHTML=d.notifs.map(n=>`
      <div class="notif-item">
        <img src="/anh_admin.jpg" class="notif-avatar" onerror="this.style.display='none'">
        <div class="notif-body">
          <div class="notif-msg">${n.msg}</div>
          <div class="notif-time">${n.time}</div>
        </div>
      </div>`).join('');
  }).catch(()=>{});
}
function loadMyTopups(){
  fetch('/api/my-topups').then(r=>r.json()).then(d=>{
    const box=document.getElementById('topup-hist');if(!box)return;
    if(!d.ok||!d.topups||!d.topups.length){box.innerHTML='<div style="text-align:center;color:var(--muted);padding:1.5rem;font-size:.82rem;">Chưa có lịch sử nạp tiền</div>';return;}
    box.innerHTML='<table class="hist-table"><tr><th>Thời gian</th><th>Số tiền</th><th>Mã CK</th><th>Trạng thái</th></tr>'+
      d.topups.map(r=>{
        const st=r.status==='approved'?'<span class="badge-ok">✅ Đã duyệt</span>':r.status==='rejected'?'<span class="badge-rej">❌ Từ chối</span>':'<span class="badge-pend">⏳ Chờ duyệt</span>';
        return `<tr><td style="font-size:.7rem;color:var(--muted);">${r.created}</td><td style="font-weight:700;color:var(--accent);">${(r.amount||0).toLocaleString('vi-VN')}đ</td><td style="font-family:monospace;font-size:.72rem;">${r.content}</td><td>${st}</td></tr>`;
      }).join('')+'</table>';
  }).catch(()=>{});
}
function loadMyCarries(){
  fetch('/api/my-carries').then(r=>r.json()).then(d=>{
    const box=document.getElementById('carry-hist');if(!box)return;
    if(!d.ok||!d.carries||!d.carries.length){box.innerHTML='<div style="text-align:center;color:var(--muted);padding:1.5rem;font-size:.82rem;">Chưa có lịch sử kéo thuê</div>';return;}
    box.innerHTML='<table class="hist-table"><tr><th>Thời gian</th><th>Sao</th><th>Rank</th><th>Đơn giá</th><th>Tổng tiền</th></tr>'+
      d.carries.map(o=>`<tr><td style="font-size:.7rem;color:var(--muted);">${o.time}</td><td style="font-weight:700;">⭐ ${o.stars}</td><td>${o.rank||''}</td><td style="font-size:.72rem;">${(o.price_per_star||1000).toLocaleString('vi-VN')}đ/sao</td><td style="color:var(--accent);font-weight:700;">${(o.total||0).toLocaleString('vi-VN')}đ</td></tr>`).join('')+'</table>';
  }).catch(()=>{});
}
let _fbPosts=[],_fbPage=1,_fbPerPage=3;
function loadFeedbacks(){
  fetch('/api/feedbacks').then(r=>r.json()).then(d=>{
    if(!d.ok||!d.posts||!d.posts.length)return;
    const sec=document.getElementById('feedback-section');
    if(!sec)return;
    sec.style.display='block';
    _fbPosts=d.posts;
    _fbPage=1;
    renderFeedbacks();
  }).catch(()=>{});
}
function renderFeedbacks(){
  const list=document.getElementById('feedback-list');
  if(!list)return;
  const total=_fbPosts.length;
  const totalPages=Math.ceil(total/_fbPerPage);
  const start=(_fbPage-1)*_fbPerPage;
  const page=_fbPosts.slice(start,start+_fbPerPage);
  let html=page.map(p=>`
    <div class="feedback-post">
      ${p.media_url?(p.media_type==='video'?
        `<video src="${p.media_url}" style="width:100%;border-radius:10px;margin-bottom:.5rem;" controls playsinline preload="metadata"></video>`:
        `<div class="rainbow-wrap" style="margin-bottom:.5rem;"><img src="${p.media_url}" alt="Feedback" style="width:100%;border-radius:11px;display:block;" loading="lazy" onerror="this.parentNode.style.display='none'"></div>`
      ):''}
      ${p.desc?`<div style="font-size:.83rem;color:var(--text);line-height:1.55;font-weight:500;">${p.desc}</div>`:''}
      <div style="font-size:.7rem;color:var(--muted);margin-top:.3rem;">${p.customer?'👤 '+p.customer+' • ':''}⏰ ${p.time}</div>
    </div>`).join('');
  if(totalPages>1){
    let pg='<div style="display:flex;gap:.4rem;margin-top:.8rem;justify-content:center;flex-wrap:wrap;">';
    for(let i=1;i<=totalPages;i++){
      pg+=`<button onclick="fbGoPage(${i})" style="padding:.3rem .75rem;border-radius:8px;font-size:.75rem;font-weight:600;border:1.5px solid ${i===_fbPage?'var(--accent)':'var(--border)'};background:${i===_fbPage?'var(--accent)':'#fff'};color:${i===_fbPage?'#fff':'var(--text)'};cursor:pointer;">${i}</button>`;
    }
    pg+='</div>';
    html+=pg;
  }
  list.innerHTML=html;
}
function fbGoPage(p){_fbPage=p;renderFeedbacks();}
function loadTuchon(page){
  const box=document.getElementById('tuchon-list');
  if(!box)return;
  box.innerHTML='<div style="text-align:center;color:var(--muted);padding:2rem;font-size:.85rem;">Đang tải...</div>';
  fetch('/api/custom-accs?page='+(page||1)).then(r=>r.json()).then(d=>{
    if(!d.ok){box.innerHTML='<div style="text-align:center;color:var(--muted);padding:2rem;font-size:.85rem;">Không tải được danh sách</div>';return;}
    if(!d.accs||!d.accs.length){
      box.innerHTML='<div style="text-align:center;color:var(--muted);padding:2.5rem 1rem;"><div style="font-size:2rem;margin-bottom:.5rem;">📭</div><div style="font-weight:600;margin-bottom:.3rem;">Chưa có acc nào</div><div style="font-size:.82rem;">Admin sẽ cập nhật sớm. Liên hệ để đặt hàng!</div></div>';
      return;
    }
    let html=d.accs.map(a=>`
      <div style="background:#fff;border-radius:16px;border:1px solid var(--border);box-shadow:0 2px 8px rgba(0,0,0,.06);overflow:hidden;margin-bottom:.9rem;">
        ${a.image_url?`<div class="rainbow-wrap" style="margin:0;border-radius:0;"><img src="${a.image_url}" alt="Acc" style="width:100%;max-height:200px;object-fit:cover;display:block;" loading="lazy" onerror="this.parentNode.style.display='none'"></div>`:''}
        <div style="padding:.9rem;">
          ${a.platform?`<div style="font-size:.7rem;font-weight:700;color:var(--accent);text-transform:uppercase;margin-bottom:.3rem;">📱 ${a.platform}</div>`:''}
          ${a.desc?`<div style="font-size:.83rem;color:var(--text);line-height:1.55;margin-bottom:.5rem;">${a.desc}</div>`:''}
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.5rem;">
            <div style="font-size:1.1rem;font-weight:800;color:var(--accent);">${a.price>0?a.price.toLocaleString('vi-VN')+'đ':'Liên hệ'}</div>
            ${a.price>0?`<button class="btn btn-primary btn-sm" onclick="buyCustomAcc('${a.id}',${a.price},'${(a.platform||'').replace(/'/g,'&#39;').replace(/`/g,'&#96;').replace(/\n/g,' ')}','${(a.desc||'').replace(/'/g,'&#39;').replace(/`/g,'&#96;').replace(/\n/g,' ').substring(0,100)}')">🛒 Mua Ngay</button>`:`<a href="https://t.me/""" + ADMIN_TG_USERNAME + """" target="_blank"><button class="btn btn-tg btn-sm">✈️ Liên Hệ</button></a>`}
          </div>
          <div style="font-size:.68rem;color:var(--muted);margin-top:.4rem;">⏰ ${a.added}</div>
        </div>
      </div>`).join('');
    if(d.total_pages>1){
      html+='<div style="display:flex;gap:.4rem;justify-content:center;flex-wrap:wrap;margin-top:.5rem;">';
      for(let i=1;i<=d.total_pages;i++){
        html+=`<button onclick="loadTuchon(${i})" style="padding:.35rem .8rem;border-radius:8px;font-size:.76rem;font-weight:600;border:1.5px solid ${i===d.page?'var(--accent)':'var(--border)'};background:${i===d.page?'var(--accent)':'#fff'};color:${i===d.page?'#fff':'var(--text)'};cursor:pointer;">${i}</button>`;
      }
      html+='</div>';
    }
    box.innerHTML=html;
  }).catch(()=>{box.innerHTML='<div style="text-align:center;color:var(--muted);padding:2rem;font-size:.85rem;">Lỗi kết nối!</div>';});
}
function calcThuAcc(){
  const rank=document.getElementById('ta-rank').value;
  const lv=parseInt(document.getElementById('ta-lv').value)||0;
  const res=document.getElementById('ta-result');
  if(!rank||lv<5){res.style.display='none';return;}
  const cfg={
    'Bạch Kim':{base:12000,step:1000,min:5,max:13},
    'Kim Cương':{base:15000,step:1500,min:5,max:13},
    'Huyền Thoại':{base:30000,step:2000,min:5,max:25},
    'Cao Thủ':{base:38000,step:3000,min:5,max:20},
    'Thách Đấu':{base:45000,step:3000,min:5,max:35}
  };
  const c=cfg[rank];if(!c){res.style.display='none';return;}
  const useLv=Math.min(lv,c.max);
  const price=c.base+(useLv-c.min)*c.step;
  res.style.display='block';
  document.getElementById('ta-price').textContent=price.toLocaleString('vi-VN')+'đ';
  document.getElementById('ta-note').textContent=lv>c.max?`(Lv${lv} > Lv${c.max}, tính theo Lv${c.max})`:' ';
}
function initFloatNotice(){
  const hidden=localStorage.getItem('fn_hidden_until');
  if(hidden&&Date.now()<parseInt(hidden))return;
  fetch('/api/notice').then(r=>r.json()).then(d=>{
    const el=document.getElementById('fn');
    const body=document.getElementById('fn-body');
    if(!el||!body)return;
    body.textContent=d.notice||'🎮 Chào mừng đến Shop VKhanh! Mua acc Free Fire uy tín, kéo rank chuyên nghiệp.';
    const tgBtn=document.getElementById('fn-tg-btn');
    const zaloBtn=document.getElementById('fn-zalo-btn');
    const descEl=document.getElementById('fn-btn-desc');
    if(tgBtn){if(d.tg_link){tgBtn.href=d.tg_link;tgBtn.style.display='inline';}else{tgBtn.style.display='none';}}
    if(zaloBtn){if(d.zalo_link){zaloBtn.href=d.zalo_link;zaloBtn.style.display='inline';}else{zaloBtn.style.display='none';}}
    if(descEl){if(d.btn_desc){descEl.textContent=d.btn_desc;descEl.style.display='block';}else{descEl.style.display='none';}}
    el.classList.add('show');
  }).catch(()=>{});
}
function closeFN(){const el=document.getElementById('fn');if(el)el.classList.remove('show');}
function hideFN2h(){localStorage.setItem('fn_hidden_until',(Date.now()+7200000).toString());closeFN();}

// MUSIC — autoplay on user interaction
const TRACKS=[{name:'Nhạc FF 1',src:'/music1.mp3'},{name:'Nhạc FF 2',src:'/music2.mp3'},{name:'Nhạc FF 3',src:'/music3.mp3'}];
let aud=null,curT=0,isPlaying=false,_autoPlayTried=false;
function initAudio(){
  if(aud)return;
  aud=new Audio();
  aud.preload='none';
  aud.addEventListener('timeupdate',updSeek);
  aud.addEventListener('ended',()=>nextT());
  aud.addEventListener('error',()=>{});
  loadT(0);
}
function initDisc(){initAudio();}
function loadT(idx){
  curT=(idx+TRACKS.length)%TRACKS.length;
  const t=TRACKS[curT];
  if(aud){aud.src=t.src;aud.load();}
  const tn=document.getElementById('music-title');if(tn)tn.textContent=t.name;
  document.querySelectorAll('.pl-item').forEach((p,i)=>p.classList.toggle('active',i===curT));
}
function playM(){
  if(!aud)initAudio();
  const p=aud.play();
  if(p!==undefined){p.then(()=>{isPlaying=true;updatePlayBtn();const d=document.getElementById('mdisc');if(d)d.classList.add('playing');}).catch(()=>{isPlaying=false;updatePlayBtn();});}
  else{isPlaying=true;updatePlayBtn();}
}
function pauseM(){if(aud)aud.pause();isPlaying=false;updatePlayBtn();const d=document.getElementById('mdisc');if(d)d.classList.remove('playing');}
function togglePlay(){isPlaying?pauseM():playM();}
function nextT(){loadT(curT+1);if(isPlaying)setTimeout(playM,80);}
function prevT(){loadT(curT-1);if(isPlaying)setTimeout(playM,80);}
function updatePlayBtn(){
  const btn=document.getElementById('play-btn');if(!btn)return;
  btn.innerHTML=isPlaying
    ?'<svg fill="currentColor" viewBox="0 0 24 24"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>'
    :'<svg fill="currentColor" viewBox="0 0 24 24"><polygon points="5,3 19,12 5,21"/></svg>';
}
function updSeek(){
  if(!aud||!aud.duration)return;
  const pct=(aud.currentTime/aud.duration)*100;
  const s=document.getElementById('music-seek');if(s)s.value=pct;
  const c=document.getElementById('cur-t');const d2=document.getElementById('dur-t');
  if(c)c.textContent=fmtT(aud.currentTime);if(d2)d2.textContent=fmtT(aud.duration);
}
function seekTo(v){if(aud&&aud.duration)aud.currentTime=(v/100)*aud.duration;}
function fmtT(s){if(!s||isNaN(s))return'0:00';const m=Math.floor(s/60),sc=Math.floor(s%60);return m+':'+(sc<10?'0':'')+sc;}
function loadTPlay(idx){loadT(idx);setTimeout(playM,80);}
function tryAutoPlay(){
  if(window.NO_MUSIC)return;
  initAudio();
  aud.play().then(()=>{isPlaying=true;updatePlayBtn();const d=document.getElementById('mdisc');if(d)d.classList.add('playing');}).catch(()=>{
    // Auto-play blocked — attach once listener for user interaction
    if(!_autoPlayTried){
      _autoPlayTried=true;
      const tryPlay=()=>{
        if(!isPlaying){playM();}
        document.removeEventListener('touchstart',tryPlay);
        document.removeEventListener('click',tryPlay);
      };
      document.addEventListener('touchstart',tryPlay,{once:true,passive:true});
      document.addEventListener('click',tryPlay,{once:true});
    }
  });
}

function loadProfile(){
  fetch('/profile-data').then(r=>r.json()).then(d=>{
    if(!d.ok)return;
    const set=(id,v)=>{const el=document.getElementById(id);if(el)el.textContent=v;};
    set('pd-display',d.display||d.username);
    set('pd-user','@'+d.username);
    set('pd-bal',d.balance.toLocaleString('vi-VN')+'đ');
    set('pd-id','#'+d.random_id);
    set('pd-created',d.created);
    set('pd-ip',d.last_ip);
  }).catch(()=>{});
}
document.addEventListener('DOMContentLoaded',()=>{
  fetch('/api/acc-count').then(r=>r.json()).then(d=>{stockMap=d;renderStock();}).catch(()=>{});
  updateBalance();
  setInterval(updateBalance,30000);
  setTimeout(tryAutoPlay,1500);
  loadFeedbacks();
});
window.addEventListener('load',()=>{
  const ls=document.getElementById('ls');
  if(!ls)return;
  setTimeout(()=>{ls.style.opacity='0';setTimeout(()=>{ls.remove();initFloatNotice();},420);},900);
});
</script>
"""

LAYOUT = lambda body: f"""<!DOCTYPE html>
<html lang="vi">
<head>{BASE_CSS}<title>Shop VKhanh - Cày Thuê & Bán Acc Free Fire</title></head>
<body>
<div id="ls"><div class="ls-logo">Shop <span>VKhanh</span></div><div class="ls-bar"><div class="ls-fill"></div></div><div class="ls-text">Đang tải...</div></div>
<div id="st-overlay"></div>
<div id="st"><div class="st-check"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg></div><div class="st-msg"></div><div class="st-sub"></div></div>
<div id="et"><div class="et-x"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></div><div class="et-msg"></div><div class="et-sub"></div></div>
<div id="fn">
  <div class="fn-top">
    <div class="fn-admin"><img src="/anh_admin.jpg" class="fn-admin-img" onerror="this.style.display='none'"><div class="fn-title">📢 Thông báo Admin</div></div>
    <span class="fn-close" onclick="closeFN()" style="font-size:1.3rem;cursor:pointer;color:var(--muted);padding:.1rem .3rem;border-radius:50%;border:1px solid var(--border);line-height:1;width:22px;height:22px;display:flex;align-items:center;justify-content:center;">×</span>
  </div>
  <div class="fn-body" id="fn-body"></div>
  <div id="fn-btn-desc" style="font-size:.72rem;color:var(--muted);margin:.4rem 0 0;display:none;"></div>
  <div class="fn-actions" style="flex-wrap:wrap;">
    <button class="btn btn-outline btn-sm" onclick="closeFN()">Đóng</button>
    <button class="btn btn-outline btn-sm" onclick="hideFN2h()">Ẩn 2 giờ</button>
    <a id="fn-tg-btn" href="#" target="_blank" style="display:none;">
      <button class="btn btn-tg btn-sm" style="display:flex;align-items:center;gap:.3rem;border-radius:50px;padding:.35rem .85rem;">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="#fff"><path d="M20.665 3.717l-17.73 6.837c-1.21.486-1.203 1.161-.222 1.462l4.552 1.42 10.532-6.645c.498-.303.953-.14.579.192L7.679 16.244l-.388 4.554c.568 0 .82-.26 1.132-.559l2.717-2.643 5.645 4.166c1.04.574 1.79.278 2.05-.966l3.707-17.471c.38-1.521-.58-2.209-1.877-1.608z"/></svg>
        Telegram
      </button>
    </a>
    <a id="fn-zalo-btn" href="#" target="_blank" style="display:none;">
      <button class="btn btn-sm" style="background:linear-gradient(135deg,#0068ff,#0050cc);color:#fff;display:flex;align-items:center;gap:.3rem;border-radius:50px;padding:.35rem .85rem;">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="#fff"><circle cx="12" cy="12" r="10"/><text x="12" y="16" text-anchor="middle" font-size="9" font-weight="bold" fill="#0068ff" font-family="Arial">Z</text></svg>
        Zalo
      </button>
    </a>
  </div>
</div>
<nav class="navbar">
  <div class="hamburger" onclick="openDrawer()"><span></span><span></span><span></span></div>
  <div class="nav-logo">Shop <span>VKhanh</span></div>
  <div class="nav-bell" onclick="showPage('notifs',null)">
    <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
    <div class="notif-dot" id="notif-dot"></div>
  </div>
  <div class="nav-bal" id="nav-bal" onclick="showPage('profile',null)">---đ</div>
</nav>
<div class="doverlay" id="doverlay" onclick="closeDrawer()"></div>
<div class="drawer" id="drawer">
  <div class="dhead"><h3>Shop VKhanh 🎮</h3><p>Cày Thuê & Bán Acc Free Fire</p></div>
  <div class="dmenu">
    <div class="ditem active" id="mi-home" onclick="showPage('home',this)"><svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg><span>🏠 Trang Chủ</span></div>
    <div class="ditem" id="mi-shop" onclick="showPage('shop',this)"><svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M6 2L3 6v14a2 2 0 002 2h14a2 2 0 002-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 01-8 0"/></svg><span>🛒 Mua Acc Clone</span></div>
    <div class="ditem" id="mi-topup" onclick="showPage('topup',this)"><svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/></svg><span>💰 Nạp Tiền</span></div>
    <div class="ditem" id="mi-carry" onclick="showPage('carry',this)"><svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg><span>🏆 Kéo Thuê FF</span></div>
    <div class="ditem" id="mi-music" onclick="showPage('music',this)"><svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg><span>🎵 Nhạc Nền</span></div>
    <div class="ditem" id="mi-notifs" onclick="showPage('notifs',this)"><svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg><span>🔔 Thông Báo</span></div>
    <div class="ditem" id="mi-support" onclick="showPage('support',this)"><svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg><span>💬 Hỗ Trợ Admin</span></div>
    <div class="ditem" id="mi-profile" onclick="showPage('profile',this)"><svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg><span>👤 Tài Khoản</span></div>
    <div class="ditem" id="mi-thuacc" onclick="showPage('thuacc',this)"><svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M12 2a10 10 0 100 20A10 10 0 0012 2z"/><path d="M8 12l2 2 4-4"/></svg><span>💰 Thu Acc</span></div>
    <div class="ditem" id="mi-tuchon" onclick="showPage('tuchon',this)"><svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/></svg><span>🎮 Acc Tự Chọn</span></div>
  </div>
  <div class="dfooter">
    <a href="https://t.me/{ADMIN_TG_USERNAME}" target="_blank">
      <button class="tg-btn"><svg viewBox="0 0 24 24"><path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.894 8.221-1.97 9.28c-.145.658-.537.818-1.084.508l-3-2.21-1.447 1.394c-.16.16-.295.295-.605.295l.213-3.053 5.56-5.023c.242-.213-.054-.333-.373-.12L7.19 13.75l-2.968-.924c-.643-.204-.657-.643.136-.953l11.57-4.461c.537-.194 1.006.131.966.809z"/></svg>Liên Hệ Admin</button>
    </a>
  </div>
</div>
<div class="content">
{body}
</div>
{BASE_JS}
</body></html>"""

MAIN_BODY = """
<!-- HOME -->
<div class="page active visible" id="pg-home">
  <div class="hero-section" style="margin-bottom:1rem;">
    <div style="position:absolute;right:-30px;top:-30px;width:120px;height:120px;background:rgba(255,255,255,.05);border-radius:50%;"></div>
    <div style="position:absolute;left:-20px;bottom:-40px;width:90px;height:90px;background:rgba(255,255,255,.04);border-radius:50%;"></div>
    <div style="position:relative;z-index:1;">
      <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.5rem;">
        <span style="background:rgba(255,220,0,.2);color:#ffd700;font-size:.68rem;font-weight:700;padding:.2rem .6rem;border-radius:20px;border:1px solid rgba(255,220,0,.3);">🔥 HOT</span>
        <span style="background:rgba(255,255,255,.1);color:rgba(255,255,255,.8);font-size:.68rem;font-weight:600;padding:.2rem .6rem;border-radius:20px;">FREE FIRE</span>
      </div>
      <div style="font-size:1.55rem;font-weight:800;margin-bottom:.3rem;line-height:1.2;">Shop <span style="color:#a78bfa;">VKhanh</span> 🎮</div>
      <div style="font-size:.82rem;opacity:.85;margin-bottom:1rem;line-height:1.55;">
        ⭐ <b>Kéo Thuê Rank</b> chuyên nghiệp — Bao thắng<br>
        💜 <b>Bán Acc Clone</b> Kim Cương, Bạch Kim, Lv5 Google<br>
        ✅ Uy tín • Nhanh chóng • Giá rẻ nhất thị trường
      </div>
      <div style="display:flex;gap:.5rem;flex-wrap:wrap;">
        <button onclick="showPage('carry',document.getElementById('mi-carry'))" style="background:linear-gradient(135deg,#f59e0b,#d97706);color:#fff;border:none;padding:.5rem 1rem;border-radius:20px;font-size:.78rem;font-weight:700;cursor:pointer;transition:transform .15s ease;" ontouchstart="" onmousedown="this.style.transform='scale(.95)'" onmouseup="this.style.transform='scale(1)'" onmouseleave="this.style.transform='scale(1)'">⭐ Kéo Thuê Ngay</button>
        <button onclick="showPage('shop',document.getElementById('mi-shop'))" style="background:rgba(255,255,255,.15);backdrop-filter:blur(4px);color:#fff;border:1px solid rgba(255,255,255,.3);padding:.5rem 1rem;border-radius:20px;font-size:.78rem;font-weight:700;cursor:pointer;transition:transform .15s ease;" ontouchstart="" onmousedown="this.style.transform='scale(.95)'" onmouseup="this.style.transform='scale(1)'" onmouseleave="this.style.transform='scale(1)'">🛒 Mua Acc</button>
      </div>
    </div>
  </div>

  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:.6rem;margin-bottom:1rem;">
    <div class="quick-card" onclick="showPage('shop',document.getElementById('mi-shop'))">
      <div style="font-size:1.5rem;margin-bottom:.3rem;">🛒</div>
      <div style="font-size:.72rem;font-weight:700;color:var(--primary);">Mua Acc</div>
      <div style="font-size:.65rem;color:var(--muted);margin-top:.15rem;" id="hm-stk-kc">---</div>
    </div>
    <div class="quick-card" onclick="showPage('carry',document.getElementById('mi-carry'))">
      <div style="font-size:1.5rem;margin-bottom:.3rem;">🏆</div>
      <div style="font-size:.72rem;font-weight:700;color:var(--primary);">Kéo Thuê</div>
      <div style="font-size:.65rem;color:var(--muted);margin-top:.15rem;">Từ 1.000đ/sao</div>
    </div>
    <div class="quick-card" onclick="showPage('support',document.getElementById('mi-support'))">
      <div style="font-size:1.5rem;margin-bottom:.3rem;">📲</div>
      <div style="font-size:.72rem;font-weight:700;color:var(--primary);">Admin</div>
      <div style="font-size:.65rem;color:var(--muted);margin-top:.15rem;">24/7</div>
    </div>
  </div>

  <div class="card" style="margin-bottom:.9rem;">
    <div class="card-title">🎮 Dịch Vụ Nổi Bật</div>
    <div onclick="showPage('carry',document.getElementById('mi-carry'))" class="service-card" style="background:linear-gradient(135deg,#fff7ed,#fffbeb);border-color:#fed7aa;margin-bottom:.65rem;">
      <div style="width:44px;height:44px;background:linear-gradient(135deg,#f59e0b,#d97706);border-radius:12px;display:flex;align-items:center;justify-content:center;flex-shrink:0;">
        <svg width="22" height="22" fill="white" viewBox="0 0 24 24"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
      </div>
      <div style="flex:1;min-width:0;">
        <div style="font-weight:700;font-size:.88rem;color:#92400e;">Kéo Thuê Rank Free Fire</div>
        <div style="font-size:.72rem;color:#b45309;margin-top:.1rem;">Đồng→Kim Cương: 1.000đ/sao • Cao Thủ→Thách Đấu: 1.500đ/sao</div>
        <div style="font-size:.68rem;color:#78716c;margin-top:.15rem;">✅ Bao thắng • Tối thiểu 5 sao • Chuyên nghiệp</div>
      </div>
    </div>
    <div onclick="showPage('shop',document.getElementById('mi-shop'))" class="service-card" style="background:linear-gradient(135deg,#faf5ff,#f3e8ff);border-color:#d8b4fe;">
      <div style="width:44px;height:44px;background:linear-gradient(135deg,#7c3aed,#6d28d9);border-radius:12px;display:flex;align-items:center;justify-content:center;flex-shrink:0;">
        <svg width="22" height="22" fill="none" stroke="white" stroke-width="2" viewBox="0 0 24 24"><path d="M6 2L3 6v14a2 2 0 002 2h14a2 2 0 002-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 01-8 0"/></svg>
      </div>
      <div style="flex:1;min-width:0;">
        <div style="font-weight:700;font-size:.88rem;color:#5b21b6;">Bán Acc Clone Free Fire</div>
        <div style="font-size:.72rem;color:#7c3aed;margin-top:.1rem;">Kim Cương 20k • Bạch Kim 15k • Lv5 Google 2.5k</div>
        <div style="font-size:.68rem;color:#78716c;margin-top:.15rem;">✅ Bảo hành 100% • Nhận ngay • Bảo mật</div>
      </div>
    </div>
  </div>

  <div class="card" style="margin-bottom:.9rem;">
    <div class="card-title">🖼️ Acc Nổi Bật</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:.75rem;margin-bottom:.7rem;">
      <div onclick="showPage('shop',document.getElementById('mi-shop'))" style="cursor:pointer;">
        <div class="rainbow-wrap">
          <img src="/acc_kim_cuong.jpg" alt="Kim Cương" style="width:100%;display:block;border-radius:11px;" loading="lazy" onerror="this.parentNode.style.cssText='background:linear-gradient(135deg,#8b5cf6,#7c3aed);border-radius:14px;height:100px;padding:3px;'">
        </div>
        <div style="font-size:.72rem;font-weight:700;color:var(--primary);margin-top:.35rem;text-align:center;">💜 Kim Cương — 20k</div>
      </div>
      <div onclick="showPage('shop',document.getElementById('mi-shop'))" style="cursor:pointer;">
        <div class="rainbow-wrap">
          <img src="/acc_bach_kim.png" alt="Bạch Kim" style="width:100%;display:block;border-radius:11px;" loading="lazy" onerror="this.parentNode.style.cssText='background:linear-gradient(135deg,#0891b2,#0e7490);border-radius:14px;height:100px;padding:3px;'">
        </div>
        <div style="font-size:.72rem;font-weight:700;color:var(--primary);margin-top:.35rem;text-align:center;">🔵 Bạch Kim — 15k</div>
      </div>
    </div>
    <div onclick="showPage('carry',document.getElementById('mi-carry'))" style="cursor:pointer;">
      <div class="rainbow-wrap">
        <img src="/keothue.png" alt="Kéo Thuê FF" style="width:100%;display:block;border-radius:11px;" loading="lazy" onerror="this.parentNode.style.cssText='background:linear-gradient(135deg,#f59e0b,#d97706);border-radius:14px;height:80px;padding:3px;'">
      </div>
    </div>
  </div>

  <div class="card" id="feedback-section" style="margin-bottom:.9rem;display:none;">
    <div class="card-title">🏅 Feedback Kéo Rank Thực Tế</div>
    <div id="feedback-list"></div>
  </div>

  <div class="card" style="margin-bottom:.9rem;">
    <div class="card-title">👤 Admin</div>
    <div style="display:flex;align-items:center;gap:1rem;">
      <div class="av-wrap" style="flex-shrink:0;">
        <img src="/anh_admin.jpg" class="av-img" onerror="this.style.display='none'" alt="Admin">
      </div>
      <div>
        <div style="font-weight:700;font-size:.95rem;color:var(--primary);">VKhanh Admin</div>
        <div style="font-size:.76rem;color:var(--muted);margin-bottom:.6rem;">Bạn Kiếm Tiền • Shop Uy Tín #1</div>
        <div style="display:flex;gap:.4rem;flex-wrap:wrap;">
          <a href="https://t.me/""" + ADMIN_TG_USERNAME + """" target="_blank"><button class="btn btn-tg btn-sm">✈️ Telegram</button></a>
          <a href="https://www.tiktok.com/@midu.c2" target="_blank"><button class="btn btn-tt btn-sm">🎵 TikTok</button></a>
        </div>
      </div>
    </div>
  </div>
  <div class="card">
    <div class="card-title">🛡️ Cam Kết</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:.6rem;font-size:.75rem;">
      <div style="background:#f0fdf4;border-radius:10px;padding:.65rem;"><div style="font-size:1rem;margin-bottom:.2rem;">✅</div><div style="font-weight:600;color:#065f46;">Bảo hành 100%</div></div>
      <div style="background:#eff6ff;border-radius:10px;padding:.65rem;"><div style="font-size:1rem;margin-bottom:.2rem;">⚡</div><div style="font-weight:600;color:#1e40af;">Nhận ngay tức thì</div></div>
      <div style="background:#fef3c7;border-radius:10px;padding:.65rem;"><div style="font-size:1rem;margin-bottom:.2rem;">🔒</div><div style="font-weight:600;color:#92400e;">Bảo mật tuyệt đối</div></div>
      <div style="background:#fdf4ff;border-radius:10px;padding:.65rem;"><div style="font-size:1rem;margin-bottom:.2rem;">💬</div><div style="font-weight:600;color:#6b21a8;">Hỗ trợ 24/7</div></div>
    </div>
  </div>
</div>

<!-- SHOP -->
<div class="page" id="pg-shop">
  <div class="tabs">
    <div class="tab active" id="tab-kim_cuong" onclick="shopTab('kim_cuong',this)">Kim Cương</div>
    <div class="tab" id="tab-bach_kim" onclick="shopTab('bach_kim',this)">Bạch Kim</div>
    <div class="tab" id="tab-lv5" onclick="shopTab('lv5',this)">Lv5 Google</div>
  </div>
  <div id="sh-kim_cuong">
    <div class="acc-card">
      <div class="rainbow-wrap">
        <img src="/acc_kim_cuong.jpg" alt="Kim Cương" style="width:100%;display:block;" loading="lazy" onerror="this.parentNode.style.cssText='background:linear-gradient(135deg,#8b5cf6,#7c3aed);border-radius:14px;height:170px;padding:3px;'">
      </div>
      <div class="acc-body">
        <div class="acc-badge">⭐ Rank Kim Cương I</div>
        <div class="acc-title">Clon Rank Kim Cương Free Fire</div>
        <div class="acc-desc">🛡️ Bảo Hành Acc 100% Cam Kết Uy Tín • Rank Kim Cương I • Thông tin clone bảo mật • Nhận acc ngay sau thanh toán</div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-top:.7rem;flex-wrap:wrap;gap:.5rem;">
          <div><div class="acc-price">20.000đ / acc</div><div class="acc-stock" id="stk-kim_cuong">Đang tải...</div></div>
          <button class="btn btn-primary" onclick="openBuy('kim_cuong')">🛒 Mua Ngay</button>
        </div>
      </div>
    </div>
  </div>
  <div id="sh-bach_kim" style="display:none;">
    <div class="acc-card">
      <div class="rainbow-wrap">
        <img src="/acc_bach_kim.png" alt="Bạch Kim" style="width:100%;display:block;" loading="lazy" onerror="this.parentNode.style.cssText='background:linear-gradient(135deg,#0891b2,#0e7490);border-radius:14px;height:170px;padding:3px;'">
      </div>
      <div class="acc-body">
        <div class="acc-badge" style="background:linear-gradient(135deg,#0891b2,#0e7490);">💎 Rank Bạch Kim I</div>
        <div class="acc-title">Clon Rank Bạch Kim Free Fire</div>
        <div class="acc-desc">🛡️ Bảo Hành Acc 100% Cam Kết Uy Tín • Rank Bạch Kim I • Thông tin clone bảo mật • Nhận acc ngay sau thanh toán</div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-top:.7rem;flex-wrap:wrap;gap:.5rem;">
          <div><div class="acc-price" style="color:#0891b2;">15.000đ / acc</div><div class="acc-stock" id="stk-bach_kim">Đang tải...</div></div>
          <button class="btn btn-primary" style="background:linear-gradient(135deg,#0891b2,#0e7490);" onclick="openBuy('bach_kim')">🛒 Mua Ngay</button>
        </div>
      </div>
    </div>
  </div>
  <div id="sh-lv5" style="display:none;">
    <div class="acc-card">
      <div class="rainbow-wrap">
        <img src="/acc_lv5.jpg" alt="Lv5" style="width:100%;display:block;" loading="lazy" onerror="this.parentNode.style.cssText='background:linear-gradient(135deg,#2563eb,#1d4ed8);border-radius:14px;height:170px;padding:3px;'">
      </div>
      <div class="acc-body">
        <div class="acc-badge" style="background:linear-gradient(135deg,#2563eb,#1d4ed8);">🎮 Lv5 Google</div>
        <div class="acc-title">Clon Lv5 Google Free Fire</div>
        <div class="acc-desc">🛡️ Bảo Hành Acc 100% Cam Kết Uy Tín • Level 5 Google • Tài khoản sạch bảo mật • Giao ngay sau thanh toán</div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-top:.7rem;flex-wrap:wrap;gap:.5rem;">
          <div><div class="acc-price" style="color:#2563eb;">2.500đ / acc</div><div class="acc-stock" id="stk-lv5">Đang tải...</div></div>
          <button class="btn btn-primary" style="background:linear-gradient(135deg,#2563eb,#1d4ed8);" onclick="openBuy('lv5')">🛒 Mua Ngay</button>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- NẠP TIỀN -->
<div class="page" id="pg-topup">
  <div class="card" style="margin-bottom:.9rem;">
    <div class="card-title">💰 Nạp Tiền Tài Khoản</div>
    <div style="background:linear-gradient(135deg,#eef2ff,#f5f3ff);border-radius:12px;padding:.9rem;margin-bottom:.9rem;border:1.5px solid var(--accent);">
      <div style="font-size:.8rem;font-weight:700;color:var(--primary);margin-bottom:.5rem;">🏦 Thông Tin Chuyển Khoản</div>
      <div style="font-size:.8rem;color:var(--text);line-height:1.9;">
        <div>💳 <b>Phương Thức:</b> <span style="font-weight:700;color:var(--accent);">""" + BANK_NAME + """</span></div>
        <div>🔢 <b>Số tài khoản:</b> <span style="font-family:monospace;font-weight:700;color:var(--accent);">""" + BANK_ACCOUNT + """</span></div>
        <div>👤 <b>Chủ tài khoản:</b> <span style="font-weight:700;">""" + BANK_HOLDER + """</span></div>
      </div>
    </div>
    <p style="font-size:.82rem;color:var(--muted);margin-bottom:.9rem;">Nhập số tiền muốn nạp, hệ thống tự tạo mã và thông báo admin duyệt. <b>Bắt buộc ghi đúng nội dung CK.</b></p>
    <div class="fg">
      <label class="fl">Số tiền nạp (đ)</label>
      <input class="fi" type="number" id="topup-amount" placeholder="Ví dụ: 50000" min="1000" inputmode="numeric">
    </div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:.4rem;margin-bottom:.9rem;">
      <button class="btn btn-outline btn-sm" onclick="setTopupAmt(20000)">20.000đ</button>
      <button class="btn btn-outline btn-sm" onclick="setTopupAmt(50000)">50.000đ</button>
      <button class="btn btn-outline btn-sm" onclick="setTopupAmt(100000)">100.000đ</button>
      <button class="btn btn-outline btn-sm" onclick="setTopupAmt(200000)">200.000đ</button>
      <button class="btn btn-outline btn-sm" onclick="setTopupAmt(500000)">500.000đ</button>
      <button class="btn btn-outline btn-sm" onclick="setTopupAmt(1000000)">1.000.000đ</button>
    </div>
    <button class="btn btn-primary btn-full" onclick="requestTopup()">💳 Tạo Yêu Cầu Nạp Tiền</button>
  </div>
  <div class="card" style="margin-bottom:.9rem;">
    <div class="card-title">📋 Lịch Sử Nạp Tiền</div>
    <div id="topup-hist"><div style="text-align:center;color:var(--muted);padding:1.5rem;font-size:.82rem;">Đang tải...</div></div>
  </div>
</div>

<!-- KÉO THUÊ FF -->
<div class="page" id="pg-carry">
  <div class="card" style="margin-bottom:.9rem;padding:0;overflow:hidden;">
    <div class="rainbow-wrap">
      <img src="/keothue.png" alt="Kéo Thuê Free Fire" style="width:100%;display:block;border-radius:14px;" loading="lazy">
    </div>
  </div>
  <div class="card" style="margin-bottom:.9rem;text-align:center;">
    <div style="font-weight:800;font-size:1.1rem;color:var(--primary);margin-bottom:.3rem;">⭐ Kéo Thuê Free Fire</div>
    <div style="font-size:.82rem;color:var(--muted);margin-bottom:.6rem;">Bao thắng • Chuyên nghiệp • Giá rẻ</div>
    <div style="display:flex;justify-content:center;gap:.5rem;flex-wrap:wrap;">
      <span style="background:#fef3c7;color:#92400e;font-size:.72rem;font-weight:700;padding:.25rem .65rem;border-radius:20px;border:1px solid #fde68a;">🥉 Đồng~Kim Cương: 1.000đ/sao</span>
      <span style="background:#fdf4ff;color:#6b21a8;font-size:.72rem;font-weight:700;padding:.25rem .65rem;border-radius:20px;border:1px solid #e9d5ff;">👑 Cao Thủ~Thách Đấu: 1.500đ/sao</span>
      <span style="background:#d1fae5;color:#065f46;font-size:.72rem;font-weight:700;padding:.25rem .65rem;border-radius:20px;border:1px solid #6ee7b7;">🎁 Từ 10 sao: Giảm 10%</span>
    </div>
    <div style="font-size:.72rem;color:var(--red);font-weight:700;margin-top:.5rem;">⚠️ Tối thiểu 5 sao mới nhận đặt</div>
  </div>
  <div class="card" style="margin-bottom:.9rem;">
    <div class="card-title">📋 Đặt Kéo Thuê</div>
    <div class="fg">
      <label class="fl">Rank hiện tại</label>
      <select class="fi fsel" id="carry-rank" onchange="updCarryTotal()">
        <option value="">-- Chọn rank --</option>
        <option value="Đồng">🥉 Đồng (1.000đ/sao)</option>
        <option value="Bạc">🥈 Bạc (1.000đ/sao)</option>
        <option value="Vàng">🥇 Vàng (1.000đ/sao)</option>
        <option value="Bạch Kim">💎 Bạch Kim (1.000đ/sao)</option>
        <option value="Kim Cương">💜 Kim Cương (1.000đ/sao)</option>
        <option value="Cao Thủ">🔥 Cao Thủ (1.500đ/sao)</option>
        <option value="Thách Đấu">🏆 Thách Đấu (1.500đ/sao)</option>
      </select>
    </div>
    <div class="fg">
      <label class="fl">Số sao cần kéo (tối thiểu 5 sao)</label>
      <input class="fi" type="number" id="carry-stars" placeholder="Ví dụ: 10" min="5" max="200" inputmode="numeric" oninput="updCarryTotal()">
    </div>
    <div class="carry-price-box" id="carry-price-box">
      <div class="carry-price-total" id="carry-total-display">0đ</div>
      <div class="carry-price-note" id="carry-price-per-star">Chọn rank và nhập số sao để tính tiền</div>
    </div>
    <div class="fg">
      <label class="fl">Ghi chú (tùy chọn)</label>
      <textarea class="fi" id="carry-note" placeholder="Ví dụ: kéo nhanh trong hôm nay..." rows="2"></textarea>
    </div>
    <div class="fg" style="margin-bottom:.55rem;">
      <label class="fl">Mã giảm giá (nếu có)</label>
      <div style="display:flex;gap:.5rem;">
        <input class="fi" type="text" id="carry-code-input" placeholder="Nhập mã..." style="flex:1;margin:0;text-transform:uppercase;" oninput="this.value=this.value.toUpperCase()">
        <button class="btn btn-outline btn-sm" onclick="applyCarryCode()">Áp dụng</button>
      </div>
      <div id="carry-code-msg" style="font-size:.75rem;margin-top:.25rem;"></div>
    </div>
    <button class="btn btn-primary btn-full" style="background:linear-gradient(135deg,var(--orange),#d97706);" onclick="orderCarry()" id="carry-submit-btn">⭐ Đặt Kéo Thuê Ngay</button>
  </div>
  <div class="card" style="margin-bottom:.9rem;">
    <div class="card-title">📊 Lịch Sử Kéo Thuê</div>
    <div id="carry-hist"><div style="text-align:center;color:var(--muted);padding:1.5rem;font-size:.82rem;">Đang tải...</div></div>
  </div>
</div>

<!-- MUSIC -->
<div class="page" id="pg-music">
  <div style="max-width:360px;margin:0 auto;">
    <div class="music-disc" id="mdisc"><div class="disc-bg"><div class="disc-center"></div></div></div>
    <div style="font-weight:700;font-size:1rem;text-align:center;color:var(--primary);margin-bottom:.2rem;" id="music-title">Nhạc FF 1</div>
    <div style="text-align:center;font-size:.76rem;color:var(--muted);margin-bottom:.9rem;">Shop VKhanh Music</div>
    <div style="padding:0 .3rem;">
      <input type="range" class="music-seek" id="music-seek" value="0" min="0" max="100" step="0.1" oninput="seekTo(this.value)">
      <div style="display:flex;justify-content:space-between;font-size:.7rem;color:var(--muted);margin:.35rem 0 .9rem;">
        <span id="cur-t">0:00</span><span id="dur-t">0:00</span>
      </div>
    </div>
    <div style="display:flex;align-items:center;justify-content:center;gap:.9rem;margin-bottom:1.25rem;">
      <button class="mc-btn" onclick="prevT()"><svg fill="currentColor" viewBox="0 0 24 24"><polygon points="19,20 9,12 19,4"/><line x1="5" y1="19" x2="5" y2="5" stroke="currentColor" stroke-width="2"/></svg></button>
      <button class="mc-btn mc-play" id="play-btn" onclick="togglePlay()"><svg fill="currentColor" viewBox="0 0 24 24"><polygon points="5,3 19,12 5,21"/></svg></button>
      <button class="mc-btn" onclick="nextT()"><svg fill="currentColor" viewBox="0 0 24 24"><polygon points="5,4 15,12 5,20"/><line x1="19" y1="5" x2="19" y2="19" stroke="currentColor" stroke-width="2"/></svg></button>
    </div>
    <div class="card">
      <div class="card-title" style="margin-bottom:.6rem;">🎵 Danh sách phát</div>
      <div class="pl-item active" onclick="loadTPlay(0)"><div style="width:22px;text-align:center;font-size:.76rem;color:var(--muted);font-weight:600;">1</div><div style="flex:1;"><div style="font-weight:600;font-size:.83rem;">Nhạc FF 1</div><div style="font-size:.7rem;color:var(--muted);">Shop VKhanh</div></div></div>
      <div class="pl-item" onclick="loadTPlay(1)"><div style="width:22px;text-align:center;font-size:.76rem;color:var(--muted);font-weight:600;">2</div><div style="flex:1;"><div style="font-weight:600;font-size:.83rem;">Nhạc FF 2</div><div style="font-size:.7rem;color:var(--muted);">Shop VKhanh</div></div></div>
      <div class="pl-item" onclick="loadTPlay(2)"><div style="width:22px;text-align:center;font-size:.76rem;color:var(--muted);font-weight:600;">3</div><div style="flex:1;"><div style="font-weight:600;font-size:.83rem;">Nhạc FF 3</div><div style="font-size:.7rem;color:var(--muted);">Shop VKhanh</div></div></div>
    </div>
  </div>
</div>

<!-- NOTIFS -->
<div class="page" id="pg-notifs">
  <div class="card">
    <div class="card-title">🔔 Thông Báo</div>
    <div id="notif-list"><div style="text-align:center;color:var(--muted);padding:2rem;font-size:.85rem;">Đang tải...</div></div>
  </div>
</div>

<!-- ADMIN HỖ TRỢ -->
<div class="page" id="pg-support">
  <div class="card" style="margin-bottom:.9rem;">
    <div style="text-align:center;margin-bottom:1.1rem;">
      <div class="av-wrap" style="margin:0 auto .7rem;">
        <img src="/anh_admin.jpg" class="av-img" onerror="this.style.display='none'" alt="Admin">
      </div>
      <div style="font-weight:700;font-size:1.05rem;color:var(--primary);">VKhanh Admin</div>
      <div style="font-size:.78rem;color:var(--muted);margin-top:.2rem;">Hỗ trợ 24/7 • Phản hồi nhanh chóng</div>
    </div>
    <div style="display:flex;flex-direction:column;gap:.55rem;">
      <a href="https://t.me/""" + ADMIN_TG_USERNAME + """" target="_blank">
        <button class="btn btn-tg btn-full" style="font-size:.92rem;padding:.8rem;">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="white" style="flex-shrink:0;"><path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.894 8.221-1.97 9.28c-.145.658-.537.818-1.084.508l-3-2.21-1.447 1.394c-.16.16-.295.295-.605.295l.213-3.053 5.56-5.023c.242-.213-.054-.333-.373-.12L7.19 13.75l-2.968-.924c-.643-.204-.657-.643.136-.953l11.57-4.461c.537-.194 1.006.131.966.809z"/></svg>
          ✈️ Nhắn Tin Telegram
        </button>
      </a>
      <a href="https://www.tiktok.com/@midu.c2" target="_blank">
        <button class="btn btn-tt btn-full" style="font-size:.92rem;padding:.8rem;">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="white" style="flex-shrink:0;"><path d="M19.59 6.69a4.83 4.83 0 01-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 01-2.88 2.5 2.89 2.89 0 01-2.89-2.89 2.89 2.89 0 012.89-2.89c.28 0 .54.04.79.1V9.01a6.33 6.33 0 00-.79-.05 6.34 6.34 0 00-6.34 6.34 6.34 6.34 0 006.34 6.34 6.34 6.34 0 006.33-6.34V9.01a8.16 8.16 0 004.77 1.52V7.1a4.85 4.85 0 01-1-.41z"/></svg>
          🎵 TikTok @midu.c2
        </button>
      </a>
      <a href="https://zalo.me/84383253073" target="_blank">
        <button class="btn btn-zalo btn-full" style="font-size:.92rem;padding:.8rem;">
          <svg width="20" height="20" viewBox="0 0 50 50" style="flex-shrink:0;"><text y="38" font-size="40" font-weight="900" font-family="Arial,sans-serif" fill="white">Z</text></svg>
          💬 Zalo Admin
        </button>
      </a>
    </div>
  </div>
  <div class="card" style="margin-bottom:.9rem;">
    <div class="card-title">📊 Thống Kê Shop</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:.6rem;">
      <div style="background:#eef2ff;border-radius:10px;padding:.75rem;text-align:center;"><div style="font-size:1.3rem;font-weight:800;color:var(--accent);">1000+</div><div style="font-size:.72rem;color:var(--muted);margin-top:.1rem;">Khách hàng</div></div>
      <div style="background:#f0fdf4;border-radius:10px;padding:.75rem;text-align:center;"><div style="font-size:1.3rem;font-weight:800;color:var(--green);">100%</div><div style="font-size:.72rem;color:var(--muted);margin-top:.1rem;">Uy tín</div></div>
      <div style="background:#fffbeb;border-radius:10px;padding:.75rem;text-align:center;"><div style="font-size:1.3rem;font-weight:800;color:var(--orange);">24/7</div><div style="font-size:.72rem;color:var(--muted);margin-top:.1rem;">Hỗ trợ</div></div>
      <div style="background:#fdf4ff;border-radius:10px;padding:.75rem;text-align:center;"><div style="font-size:1.3rem;font-weight:800;color:#7c3aed;">#1</div><div style="font-size:.72rem;color:var(--muted);margin-top:.1rem;">Shop VN</div></div>
    </div>
  </div>
  <div class="card">
    <div class="card-title">❓ Câu Hỏi Thường Gặp</div>
    <div style="font-size:.82rem;color:var(--text);line-height:1.8;">
      <div style="padding:.4rem 0;border-bottom:1px solid var(--border);"><b>Acc có bảo hành không?</b><br>Có, bảo hành 100% hoàn tiền nếu acc lỗi trong 24 giờ.</div>
      <div style="padding:.4rem 0;border-bottom:1px solid var(--border);"><b>Nhận acc trong bao lâu?</b><br>Ngay sau khi thanh toán thành công.</div>
      <div style="padding:.4rem 0;border-bottom:1px solid var(--border);"><b>Nạp tiền như thế nào?</b><br>Vào mục Nạp Tiền, tạo yêu cầu, chuyển khoản đúng nội dung, admin duyệt nhanh.</div>
      <div style="padding:.4rem 0;border-bottom:1px solid var(--border);"><b>Kéo thuê bao lâu?</b><br>Thông thường 1-3 ngày tùy rank và số sao.</div>
      <div style="padding:.4rem 0;border-bottom:1px solid var(--border);"><b>Kéo thuê tối thiểu mấy sao?</b><br>Tối thiểu 5 sao. Đồng~Kim Cương: 1.000đ/sao. Cao Thủ~Thách Đấu: 1.500đ/sao.</div>
      <div style="padding:.4rem 0;"><b>Kéo thuê xong bị khóa acc không?</b><br>Không. Chúng tôi cam kết an toàn tuyệt đối cho tài khoản.</div>
    </div>
  </div>
</div>

<!-- PROFILE -->
<div class="page" id="pg-profile">
  <div class="card" style="margin-bottom:.9rem;">
    <div style="text-align:center;margin-bottom:1rem;">
      <div style="width:60px;height:60px;background:linear-gradient(135deg,var(--accent),var(--accent2));border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto .5rem;">
        <svg width="26" height="26" fill="none" stroke="white" stroke-width="2" viewBox="0 0 24 24"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
      </div>
      <div style="font-weight:700;font-size:1.05rem;color:var(--primary);" id="pd-display">---</div>
      <div style="font-size:.76rem;color:var(--muted);" id="pd-user">---</div>
    </div>
    <div class="info-row"><span class="ik">Số dư</span><span class="iv" style="color:var(--accent);" id="pd-bal">---</span></div>
    <div class="info-row"><span class="ik">ID</span><span class="iv" id="pd-id">---</span></div>
    <div class="info-row"><span class="ik">Ngày tạo</span><span class="iv" id="pd-created" style="font-size:.76rem;">---</span></div>
    <div class="info-row"><span class="ik">IP cuối</span><span class="iv" id="pd-ip" style="font-size:.76rem;">---</span></div>
  </div>
  <div class="card" style="margin-bottom:.9rem;">
    <div class="card-title">🔒 Đổi Mật Khẩu</div>
    <div class="fg"><label class="fl">Mật khẩu hiện tại</label><input class="fi" type="password" id="pw-old" placeholder="Nhập mật khẩu hiện tại"></div>
    <div class="fg"><label class="fl">Mật khẩu mới</label><input class="fi" type="password" id="pw-new" placeholder="Ít nhất 4 ký tự"></div>
    <button class="btn btn-primary btn-full" onclick="changePw()">Đổi Mật Khẩu</button>
    <div id="pw-msg" style="margin-top:.5rem;font-size:.8rem;display:none;padding:.4rem .6rem;border-radius:8px;"></div>
  </div>
  <div style="display:flex;gap:.65rem;">
    <a href="/admin" style="flex:1;"><button class="btn btn-outline btn-full" style="font-size:.8rem;">⚙️ Admin Panel</button></a>
    <a href="/logout" style="flex:1;"><button class="btn btn-red btn-full">Đăng Xuất</button></a>
  </div>
</div>

<!-- THU ACC -->
<div class="page" id="pg-thuacc">
  <div class="card" style="margin-bottom:.9rem;padding:0;overflow:hidden;">
    <div class="rainbow-wrap" style="margin:0;border-radius:0;">
      <img src="/thuacc.png" alt="Thu Acc" style="width:100%;display:block;border-radius:14px;" loading="lazy" onerror="this.parentNode.style.cssText='background:linear-gradient(135deg,#4f46e5,#7c3aed);border-radius:14px;height:160px;padding:3px;'">
    </div>
  </div>
  <div class="card" style="margin-bottom:.9rem;text-align:center;">
    <div style="font-weight:800;font-size:1.1rem;color:var(--primary);margin-bottom:.3rem;">💰 Thu Acc Free Fire</div>
    <div style="font-size:.82rem;color:var(--muted);">Nhập thông tin acc — Xem giá ước tính — Liên hệ admin để chốt giá chính xác</div>
  </div>
  <div class="card" style="margin-bottom:.9rem;">
    <div class="card-title">📋 Kiểm Tra Giá Ước Tính</div>
    <div class="fg">
      <label class="fl">Rank của acc</label>
      <select class="fi fsel" id="ta-rank" onchange="calcThuAcc()">
        <option value="">-- Chọn rank --</option>
        <option value="Bạch Kim">💎 Bạch Kim</option>
        <option value="Kim Cương">💜 Kim Cương</option>
        <option value="Huyền Thoại">🌟 Huyền Thoại</option>
        <option value="Cao Thủ">🔥 Cao Thủ</option>
        <option value="Thách Đấu">🏆 Thách Đấu</option>
      </select>
    </div>
    <div class="fg">
      <label class="fl">Level tài khoản (ít nhất Lv5)</label>
      <input class="fi" type="number" id="ta-lv" placeholder="Ví dụ: 10" min="5" max="60" inputmode="numeric" oninput="calcThuAcc()">
    </div>
    <div id="ta-result" style="display:none;background:linear-gradient(135deg,#eef2ff,#f5f3ff);border:1.5px solid var(--accent);border-radius:14px;padding:1rem;text-align:center;margin-bottom:.9rem;">
      <div style="font-size:.78rem;color:var(--muted);margin-bottom:.3rem;">Giá ước tính</div>
      <div id="ta-price" style="font-size:1.6rem;font-weight:800;color:var(--accent);">0đ</div>
      <div id="ta-note" style="font-size:.7rem;color:var(--muted);margin-top:.2rem;"></div>
      <div style="font-size:.72rem;color:var(--red);margin-top:.4rem;font-weight:600;">⚠️ Đây là giá tham khảo. Liên hệ admin để chốt giá chính xác!</div>
    </div>
    <div style="background:#fffbeb;border:1px solid #fde68a;border-radius:12px;padding:.85rem;font-size:.8rem;color:#92400e;margin-bottom:.85rem;line-height:1.65;">
      <div style="font-weight:700;margin-bottom:.35rem;">📊 Bảng Giá Tham Khảo:</div>
      <div>💎 Bạch Kim Lv5-13: 12.000đ • +1.000đ/lv</div>
      <div>💜 Kim Cương Lv5-13: 15.000đ • +1.500đ/lv</div>
      <div>🌟 Huyền Thoại Lv5-25: 30.000đ • +2.000đ/lv</div>
      <div>🔥 Cao Thủ Lv5-20: 38.000đ • +3.000đ/lv</div>
      <div>🏆 Thách Đấu Lv5-35: 45.000đ • +3.000đ/lv</div>
    </div>
  </div>
  <div class="card" style="margin-bottom:.9rem;">
    <div class="card-title">📞 Liên Hệ Admin Để Bán Acc</div>
    <div style="text-align:center;margin-bottom:1rem;">
      <div class="av-wrap" style="margin:0 auto .7rem;">
        <img src="/anh_admin.jpg" class="av-img" onerror="this.style.display='none'" alt="Admin">
      </div>
      <div style="font-weight:700;font-size:.95rem;color:var(--primary);">VKhanh Admin</div>
      <div style="font-size:.76rem;color:var(--muted);margin-top:.15rem;">Phản hồi nhanh 24/7 • Giá tốt nhất</div>
    </div>
    <div style="display:flex;flex-direction:column;gap:.55rem;">
      <a href="https://t.me/""" + ADMIN_TG_USERNAME + """" target="_blank">
        <button class="btn btn-tg btn-full" style="font-size:.9rem;padding:.75rem;">✈️ Nhắn Tin Telegram</button>
      </a>
      <a href="https://www.tiktok.com/@midu.c2" target="_blank">
        <button class="btn btn-tt btn-full" style="font-size:.9rem;padding:.75rem;">🎵 TikTok @midu.c2</button>
      </a>
      <a href="https://zalo.me/84383253073" target="_blank">
        <button class="btn btn-zalo btn-full" style="font-size:.9rem;padding:.75rem;">💬 Zalo Admin</button>
      </a>
    </div>
  </div>
</div>

<!-- ACC TỰ CHỌN -->
<div class="page" id="pg-tuchon">
  <div class="card" style="margin-bottom:.9rem;padding:0;overflow:hidden;">
    <div class="rainbow-wrap" style="margin:0;border-radius:0;">
      <img src="/tuchon.png" alt="Acc Tự Chọn" style="width:100%;display:block;border-radius:14px;" loading="lazy" onerror="this.parentNode.style.cssText='background:linear-gradient(135deg,#0891b2,#7c3aed);border-radius:14px;height:160px;padding:3px;'">
    </div>
  </div>
  <div class="card" style="margin-bottom:.9rem;text-align:center;">
    <div style="font-weight:800;font-size:1.1rem;color:var(--primary);margin-bottom:.3rem;">🎮 Acc Tự Chọn Free Fire</div>
    <div style="font-size:.82rem;color:var(--muted);">Chọn acc ưng ý — Liên hệ admin để sở hữu ngay</div>
  </div>
  <div id="tuchon-list">
    <div style="text-align:center;color:var(--muted);padding:2rem;font-size:.85rem;">Đang tải...</div>
  </div>
  <div class="card" style="margin-top:.9rem;">
    <div class="card-title">📞 Liên Hệ Mua Acc</div>
    <div style="display:flex;flex-direction:column;gap:.5rem;">
      <a href="https://t.me/""" + ADMIN_TG_USERNAME + """" target="_blank">
        <button class="btn btn-tg btn-full">✈️ Telegram Admin</button>
      </a>
      <a href="https://www.tiktok.com/@midu.c2" target="_blank">
        <button class="btn btn-tt btn-full">🎵 TikTok @midu.c2</button>
      </a>
      <a href="https://zalo.me/84383253073" target="_blank">
        <button class="btn btn-zalo btn-full">💬 Zalo Admin</button>
      </a>
    </div>
  </div>
</div>

<!-- BUY MODAL -->
<div class="modal-ov" id="buy-modal">
  <div class="modal">
    <div class="modal-title" id="buy-title">Mua Acc</div>
    <div style="display:flex;gap:.5rem;margin-bottom:.65rem;font-size:.82rem;color:var(--muted);">
      <span>Giá: <b id="buy-price-show">---</b></span><span>•</span><span>Còn: <b id="buy-stock-show">---</b></span>
    </div>
    <div class="fg"><label class="fl">Số lượng (tối đa 10)</label><input class="fi" type="number" id="buy-qty" value="1" min="1" max="10" oninput="updBuyTotal()"></div>
    <div class="fg" style="margin-bottom:.55rem;">
      <label class="fl">Mã giảm giá (nếu có)</label>
      <div style="display:flex;gap:.5rem;">
        <input class="fi" type="text" id="buy-code-input" placeholder="Nhập mã..." style="flex:1;margin:0;text-transform:uppercase;" oninput="this.value=this.value.toUpperCase()">
        <button class="btn btn-outline btn-sm" onclick="applyBuyCode()">Áp dụng</button>
      </div>
      <div id="buy-code-msg" style="font-size:.75rem;margin-top:.25rem;"></div>
    </div>
    <div style="background:#f3f4f6;border-radius:11px;padding:.7rem;margin-bottom:.9rem;">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <span style="font-size:.85rem;font-weight:600;">Tổng tiền:</span>
        <span style="font-weight:800;color:var(--accent);font-size:1rem;" id="buy-total">---</span>
      </div>
      <div id="buy-discount-info" style="font-size:.75rem;color:var(--green);margin-top:.2rem;display:none;"></div>
    </div>
    <div style="display:flex;gap:.65rem;">
      <button class="btn btn-outline btn-sm" style="flex:1;" onclick="closeBuy()">Hủy</button>
      <button class="btn btn-primary" style="flex:1;" id="confirm-buy-btn" onclick="confirmBuy()">✅ Xác Nhận</button>
    </div>
  </div>
</div>

<!-- RESULT MODAL -->
<div class="modal-ov" id="res-modal">
  <div class="modal">
    <div style="text-align:center;margin-bottom:.9rem;">
      <div class="st-check" style="margin:0 auto .65rem;display:flex;"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg></div>
      <div class="modal-title" style="margin:0;">Mua Thành Công!</div>
    </div>
    <div id="res-list"></div>
    <button class="btn btn-primary btn-full" style="margin-top:.7rem;" onclick="document.getElementById('res-modal').classList.remove('show')">Đóng</button>
  </div>
</div>

<!-- TOPUP MODAL -->
<div class="modal-ov" id="topup-modal">
  <div class="modal">
    <div class="modal-title">💰 Nạp Tiền Vào Tài Khoản</div>
    <div style="font-size:.82rem;color:var(--muted);margin-bottom:.75rem;" id="topup-msg">Chuyển khoản theo thông tin bên dưới — bắt buộc ghi đúng nội dung</div>
    <div style="background:#eef2ff;border:1.5px solid var(--accent);border-radius:12px;padding:.8rem;margin-bottom:.7rem;font-size:.8rem;line-height:1.9;">
      <div style="font-weight:700;color:var(--primary);margin-bottom:.25rem;">💳 THÔNG TIN CHUYỂN KHOẢN</div>
      <div>💳 Phương Thức: <b id="tm-bank">""" + BANK_NAME + """</b></div>
      <div>🔢 Số TK: <b style="color:var(--accent);font-family:monospace;" id="tm-acc">""" + BANK_ACCOUNT + """</b></div>
      <div>👤 Chủ TK: <b id="tm-holder">""" + BANK_HOLDER + """</b></div>
    </div>
    <div class="qr-box" style="margin-bottom:.75rem;">
      <img src="/bank.jpg" alt="QR Ngân Hàng" onerror="this.parentNode.innerHTML='<div style=padding:1rem;color:var(--muted);font-size:.8rem;text-align:center;>QR không tải được. Liên hệ admin.</div>'">
      <div style="font-size:.72rem;color:var(--muted);margin-top:.4rem;">Quét QR hoặc chuyển theo STK trên</div>
    </div>
    <div class="content-box">
      <div style="font-size:.75rem;color:var(--red);font-weight:700;margin-bottom:.3rem;">⚠️ NỘI DUNG CHUYỂN KHOẢN — BẮT BUỘC</div>
      <div class="content-code" id="topup-content">---</div>
      <button class="btn btn-outline btn-sm" style="margin-top:.5rem;" onclick="copyText(document.getElementById('topup-content').textContent,'Nội dung CK')">📋 Sao Chép</button>
    </div>
    <div class="timer-box" id="topup-timer" style="margin-bottom:.75rem;">
      <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
      Hết hạn sau: <span id="topup-countdown">60:00</span>
    </div>
    <div style="font-size:.75rem;color:var(--muted);margin-bottom:.9rem;line-height:1.5;background:#fffbeb;border-radius:10px;padding:.6rem;border:1px solid #fde68a;">
      ⚠️ Chuyển khoản phải ghi <b>đúng nội dung</b> bên trên. Sai nội dung sẽ không được duyệt tự động.
    </div>
    <div style="display:flex;gap:.5rem;">
      <button class="btn btn-outline btn-sm" style="flex:1;min-width:70px;" onclick="document.getElementById('topup-modal').classList.remove('show')">Đóng</button>
      <a id="topup-tg-link" href="https://t.me/""" + ADMIN_TG_USERNAME + """" target="_blank" style="flex:1;min-width:70px;">
        <button class="btn btn-tg btn-sm btn-full">✈️ Telegram</button>
      </a>
      <a href="https://zalo.me/84383253073" target="_blank" style="flex:1;min-width:70px;">
        <button class="btn btn-zalo btn-sm btn-full">💬 Zalo</button>
      </a>
    </div>
  </div>
</div>

<!-- CUSTOM ACC BUY MODAL -->
<div class="modal-ov" id="tca-modal">
  <div class="modal">
    <div class="modal-title">🛒 Mua Acc Tự Chọn</div>
    <div style="background:#f3f4f6;border-radius:11px;padding:.75rem;margin-bottom:.75rem;font-size:.82rem;line-height:1.7;">
      <div>📱 Nền tảng: <b id="tca-platform">---</b></div>
      <div id="tca-desc-row" style="color:var(--muted);font-size:.78rem;"></div>
      <div>💰 Giá niêm yết: <b id="tca-price">---</b></div>
    </div>
    <div class="fg" style="margin-bottom:.55rem;">
      <label class="fl">Mã giảm giá (nếu có)</label>
      <div style="display:flex;gap:.5rem;">
        <input class="fi" type="text" id="tca-code-input" placeholder="Nhập mã..." style="flex:1;margin:0;text-transform:uppercase;" oninput="this.value=this.value.toUpperCase()">
        <button class="btn btn-outline btn-sm" onclick="applyTcaCode()">Áp dụng</button>
      </div>
      <div id="tca-code-msg" style="font-size:.75rem;margin-top:.25rem;"></div>
    </div>
    <div style="background:#eef2ff;border-radius:11px;padding:.7rem;margin-bottom:.9rem;">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <span style="font-size:.85rem;font-weight:600;">Thanh toán:</span>
        <span style="font-weight:800;color:var(--accent);font-size:1.05rem;" id="tca-final-price">---</span>
      </div>
      <div id="tca-discount-info" style="font-size:.75rem;color:var(--green);margin-top:.2rem;display:none;"></div>
    </div>
    <div style="font-size:.75rem;color:var(--muted);background:#fffbeb;border-radius:9px;padding:.55rem .75rem;margin-bottom:.8rem;border:1px solid #fde68a;">
      ⚠️ Tiền sẽ trừ ngay. Sau khi thanh toán, liên hệ admin để nhận thông tin acc.
    </div>
    <div style="display:flex;gap:.65rem;">
      <button class="btn btn-outline btn-sm" style="flex:1;" onclick="document.getElementById('tca-modal').classList.remove('show')">Hủy</button>
      <button class="btn btn-primary" style="flex:1;" id="tca-confirm-btn" onclick="confirmBuyCustomAcc()">✅ Xác Nhận Mua</button>
    </div>
  </div>
</div>

<!-- CUSTOM ACC RESULT MODAL -->
<div class="modal-ov" id="tca-result-modal">
  <div class="modal">
    <div id="tca-result-content"></div>
    <button class="btn btn-outline btn-full btn-sm" style="margin-top:.6rem;" onclick="document.getElementById('tca-result-modal').classList.remove('show')">Đóng</button>
  </div>
</div>

<!-- CARRY MODAL -->
<div class="modal-ov" id="carry-modal">
  <div class="modal">
    <div style="text-align:center;margin-bottom:.9rem;">
      <div class="st-check" style="margin:0 auto .65rem;display:flex;"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg></div>
      <div class="modal-title" style="margin:0;">Đặt Kéo Thuê Thành Công!</div>
    </div>
    <div id="carry-success-msg" style="font-size:.83rem;color:var(--text);margin-bottom:.9rem;text-align:center;line-height:1.55;"></div>
    <div style="display:flex;gap:.5rem;flex-wrap:wrap;">
      <button class="btn btn-outline btn-sm" style="flex:1;min-width:80px;" onclick="document.getElementById('carry-modal').classList.remove('show')">Đóng</button>
      <a id="carry-tg-link" href="https://t.me/""" + ADMIN_TG_USERNAME + """" target="_blank" style="flex:1;min-width:80px;">
        <button class="btn btn-tg btn-sm btn-full">✈️ Telegram</button>
      </a>
      <a id="carry-tt-link" href=""" + '"' + TIKTOK_URL + '"' + """ target="_blank" style="flex:1;min-width:80px;">
        <button class="btn btn-tt btn-sm btn-full">🎵 TikTok</button>
      </a>
      <a href="https://zalo.me/84383253073" target="_blank" style="flex:1;min-width:80px;">
        <button class="btn btn-zalo btn-sm btn-full">💬 Zalo</button>
      </a>
    </div>
  </div>
</div>

<script>
let curCat='kim_cuong',stockMap={},_topupTimer=null;
const PMAP={kim_cuong:20000,bach_kim:15000,lv5:2500};
const CMAP={kim_cuong:'Clon Rank Kim Cương',bach_kim:'Clon Bạch Kim',lv5:'Clon Lv5 Google'};
const RANK_PRICE={'Đồng':1000,'Bạc':1000,'Vàng':1000,'Bạch Kim':1000,'Kim Cương':1000,'Cao Thủ':1500,'Thách Đấu':1500};
function renderStock(){
  const cats=['kim_cuong','bach_kim','lv5'];
  cats.forEach(c=>{
    const el=document.getElementById('stk-'+c);
    if(!el)return;
    const n=stockMap[c]||0;
    el.className='acc-stock '+(n>5?'s-ok':n>0?'s-low':'s-empty');
    el.textContent=n>0?'Còn '+n+' acc':'Hết hàng';
  });
  const hm=document.getElementById('hm-stk-kc');
  if(hm){const n=stockMap['kim_cuong']||0;hm.textContent=n>0?'Còn '+n+' acc':'Hết hàng';}
}
function shopTab(cat,el){
  ['kim_cuong','bach_kim','lv5'].forEach(c=>{
    const s=document.getElementById('sh-'+c);
    if(s)s.style.display=c===cat?'block':'none';
  });
  document.querySelectorAll('#pg-shop .tab').forEach(t=>t.classList.remove('active'));
  if(el)el.classList.add('active');
}
function openBuy(cat){
  curCat=cat;
  const price=PMAP[cat],stock=stockMap[cat]||0;
  document.getElementById('buy-title').textContent='Mua '+CMAP[cat];
  document.getElementById('buy-price-show').textContent=price.toLocaleString('vi-VN')+'đ';
  document.getElementById('buy-stock-show').textContent=stock+' acc';
  const qEl=document.getElementById('buy-qty');qEl.max=Math.min(stock,10);qEl.value=1;
  updBuyTotal();
  document.getElementById('buy-modal').classList.add('show');
}
function closeBuy(){document.getElementById('buy-modal').classList.remove('show');}
function updBuyTotal(){
  const q=parseInt(document.getElementById('buy-qty').value)||1;
  let total=q*(PMAP[curCat]||0);
  if(_buyDiscountPct>0)total=Math.floor(total*(1-_buyDiscountPct/100));
  document.getElementById('buy-total').textContent=total.toLocaleString('vi-VN')+'đ';
}
let _buyDiscountPct=0,_buyDiscountCode='',_tcAccId='',_tcAccPrice=0,_tcAccPlatform='',_tcAccDesc='';
let _carryDiscountPct=0,_carryDiscountCode='';
function applyBuyCode(){
  const code=document.getElementById('buy-code-input').value.trim().toUpperCase();
  const msg=document.getElementById('buy-code-msg');
  const discInfo=document.getElementById('buy-discount-info');
  if(!code){msg.textContent='Nhập mã trước!';msg.style.color='var(--red)';return;}
  const fd=new FormData();fd.append('code',code);
  fetch('/api/check-code',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    if(d.ok){
      _buyDiscountPct=d.discount_pct;_buyDiscountCode=code;
      msg.textContent=d.msg;msg.style.color='var(--green)';
      if(discInfo){discInfo.textContent='🎁 Giảm '+d.discount_pct+'%';discInfo.style.display='block';}
      updBuyTotal();
    } else {
      _buyDiscountPct=0;_buyDiscountCode='';
      msg.textContent=d.msg;msg.style.color='var(--red)';
      if(discInfo)discInfo.style.display='none';
      updBuyTotal();
    }
  }).catch(()=>{msg.textContent='Lỗi kết nối!';msg.style.color='var(--red)';});
}
function applyCarryCode(){
  const code=document.getElementById('carry-code-input').value.trim().toUpperCase();
  const msg=document.getElementById('carry-code-msg');
  if(!code){msg.textContent='Nhập mã trước!';msg.style.color='var(--red)';return;}
  const fd=new FormData();fd.append('code',code);
  fetch('/api/check-code',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    if(d.ok){
      _carryDiscountPct=d.discount_pct;_carryDiscountCode=code;
      msg.textContent=d.msg;msg.style.color='var(--green)';
    } else {
      _carryDiscountPct=0;_carryDiscountCode='';
      msg.textContent=d.msg;msg.style.color='var(--red)';
    }
  }).catch(()=>{msg.textContent='Lỗi kết nối!';msg.style.color='var(--red)';});
}
function buyCustomAcc(id,price,platform,desc){
  _tcAccId=id;_tcAccPrice=price;_tcAccPlatform=platform;_tcAccDesc=desc;
  _buyDiscountPct=0;_buyDiscountCode='';
  document.getElementById('tca-price').textContent=price.toLocaleString('vi-VN')+'đ';
  document.getElementById('tca-platform').textContent=platform||'N/A';
  const descEl=document.getElementById('tca-desc-row');if(descEl)descEl.textContent=desc||'';
  document.getElementById('tca-final-price').textContent=price.toLocaleString('vi-VN')+'đ';
  document.getElementById('tca-discount-info').style.display='none';
  document.getElementById('tca-code-input').value='';
  document.getElementById('tca-code-msg').textContent='';
  document.getElementById('tca-modal').classList.add('show');
}
function applyTcaCode(){
  const code=document.getElementById('tca-code-input').value.trim().toUpperCase();
  const msg=document.getElementById('tca-code-msg');
  if(!code){msg.textContent='Nhập mã trước!';msg.style.color='var(--red)';return;}
  const fd=new FormData();fd.append('code',code);
  fetch('/api/check-code',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    if(d.ok){
      _buyDiscountPct=d.discount_pct;_buyDiscountCode=code;
      msg.textContent=d.msg;msg.style.color='var(--green)';
      const finalPrice=Math.floor(_tcAccPrice*(1-d.discount_pct/100));
      document.getElementById('tca-final-price').textContent=finalPrice.toLocaleString('vi-VN')+'đ';
      const di=document.getElementById('tca-discount-info');
      di.textContent='🎁 Giảm '+d.discount_pct+'% (từ '+_tcAccPrice.toLocaleString('vi-VN')+'đ)';
      di.style.display='block';
    } else {
      _buyDiscountPct=0;_buyDiscountCode='';
      msg.textContent=d.msg;msg.style.color='var(--red)';
      document.getElementById('tca-final-price').textContent=_tcAccPrice.toLocaleString('vi-VN')+'đ';
      document.getElementById('tca-discount-info').style.display='none';
    }
  }).catch(()=>{msg.textContent='Lỗi kết nối!';msg.style.color='var(--red)';});
}
function confirmBuyCustomAcc(){
  const btn=document.getElementById('tca-confirm-btn');
  if(btn){btn.textContent='⏳ Đang xử lý...';btn.disabled=true;}
  const fd=new FormData();fd.append('acc_id',_tcAccId);
  if(_buyDiscountCode)fd.append('code',_buyDiscountCode);
  fetch('/api/buy-custom-acc',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    if(btn){btn.textContent='✅ Xác Nhận Mua';btn.disabled=false;}
    document.getElementById('tca-modal').classList.remove('show');
    if(!d.ok){
      if(d.need_topup){
        if(confirm('⚠️ Số dư không đủ!\n'+d.msg+'\nNạp tiền ngay?')){showTopupModal(d.short,d.needed);}
      } else {showError('❌ Lỗi',d.msg||'Có lỗi xảy ra');}
      return;
    }
    let html=`<div style="background:#f0fdf4;border-radius:12px;padding:.9rem;margin-bottom:.7rem;border:1.5px solid #6ee7b7;">
      <div style="font-weight:700;color:var(--green);margin-bottom:.5rem;">✅ Mua Acc Tự Chọn Thành Công!</div>
      <div style="font-size:.82rem;line-height:1.7;">
        <div>📱 Nền tảng: <b>${_tcAccPlatform||'N/A'}</b></div>
        <div>💰 Đã trừ: <b>${d.total.toLocaleString('vi-VN')}đ</b>${d.discount_pct?` <span style="color:var(--green)">(giảm ${d.discount_pct}%)</span>`:''}</div>
        <div>💳 Số dư còn: <b>${d.new_balance.toLocaleString('vi-VN')}đ</b></div>
        <div style="margin-top:.4rem;color:var(--muted);font-size:.78rem;">🆔 Đơn: ${d.order_id}</div>
      </div>
    </div>
    <div style="background:#fffbeb;border-radius:10px;padding:.75rem;font-size:.8rem;color:#92400e;border:1px solid #fde68a;">
      ⚠️ Liên hệ admin để nhận thông tin acc. Admin sẽ gửi trong vòng 5-15 phút.
    </div>
    <div style="display:flex;flex-direction:column;gap:.45rem;margin-top:.7rem;">
      <a href="${d.tg_link}" target="_blank"><button class="btn btn-tg btn-full btn-sm">✈️ Telegram Admin</button></a>
      <a href="${d.zalo_url}" target="_blank"><button class="btn btn-zalo btn-full btn-sm">💬 Zalo Admin</button></a>
      <a href="${d.tiktok_url}" target="_blank"><button class="btn btn-tt btn-full btn-sm">🎵 TikTok @midu.c2</button></a>
    </div>`;
    document.getElementById('tca-result-content').innerHTML=html;
    document.getElementById('tca-result-modal').classList.add('show');
    updateBalance();
    showToast('✅ Mua acc tự chọn thành công!','Liên hệ admin để nhận acc');
  }).catch(()=>{
    if(btn){btn.textContent='✅ Xác Nhận Mua';btn.disabled=false;}
    showError('Lỗi kết nối','Vui lòng thử lại!');
  });
}
function confirmBuy(){
  const qty=parseInt(document.getElementById('buy-qty').value);
  if(!qty||qty<1){showError('Lỗi','Nhập số lượng hợp lệ!');return;}
  const cbtn=document.getElementById('confirm-buy-btn');
  if(cbtn){cbtn.textContent='⏳ Đang xử lý...';cbtn.disabled=true;}
  closeBuy();
  const fd=new FormData();fd.append('cat',curCat);fd.append('qty',qty);
  if(_buyDiscountCode)fd.append('code',_buyDiscountCode);
  fetch('/api/buy',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    if(cbtn){cbtn.textContent='✅ Xác Nhận';cbtn.disabled=false;}
    if(!d.ok){
      if(d.need_topup){showTopupModal(d.short,d.needed);}
      else{showError('❌ Lỗi',d.msg||'Có lỗi xảy ra');}
      return;
    }
    let html='';
    d.accs.forEach((a,i)=>{
      html+=`<div style="background:#f8f9fb;border-radius:11px;padding:.8rem;margin-bottom:.55rem;border:1px solid var(--border);">
        <div style="font-size:.7rem;color:var(--muted);font-weight:700;text-transform:uppercase;margin-bottom:.35rem;">Acc ${i+1} — ${a.platform||'Facebook'}</div>
        <div style="font-size:.83rem;margin-bottom:.2rem;"><b>Tài khoản:</b> <span style="font-family:monospace;">${a.user}</span></div>
        <div style="font-size:.83rem;margin-bottom:.2rem;"><b>Mật khẩu:</b> <span style="font-family:monospace;">${a.pass}</span></div>
        ${a.desc?`<div style="font-size:.73rem;color:var(--muted);margin-bottom:.35rem;">${a.desc}</div>`:''}
        <div style="font-size:.72rem;color:var(--green);margin-bottom:.45rem;font-weight:600;">🛡️ Bảo Hành Acc 100% Cam Kết Uy Tín</div>
        <button class="btn btn-outline btn-sm btn-full" onclick="copyText('${a.user}:${a.pass}','Acc ${i+1}')">📋 Sao Chép TK & MK</button>
      </div>`;
    });
    html+=`<div style="text-align:center;font-size:.78rem;color:var(--muted);margin-top:.3rem;">Trừ ${d.total.toLocaleString('vi-VN')}đ • Còn lại ${d.new_balance.toLocaleString('vi-VN')}đ</div>`;
    document.getElementById('res-list').innerHTML=html;
    document.getElementById('res-modal').classList.add('show');
    stockMap[curCat]=Math.max(0,(stockMap[curCat]||0)-d.accs.length);
    renderStock();updateBalance();
    showToast('✅ Mua thành công!',d.accs.length+' acc đã nhận');
  }).catch(()=>{
    if(cbtn){cbtn.textContent='✅ Xác Nhận';cbtn.disabled=false;}
    showError('Lỗi kết nối','Vui lòng thử lại!');
  });
}
function showTopupModal(shortAmount,needed){
  const amount=shortAmount||needed||0;
  document.getElementById('topup-msg').textContent=`Cần nạp thêm ${amount.toLocaleString('vi-VN')}đ để mua acc này`;
  openTopupModal(amount);
}
function setTopupAmt(v){const el=document.getElementById('topup-amount');if(el)el.value=v;}
function requestTopup(){
  const amount=parseInt(document.getElementById('topup-amount').value);
  if(!amount||amount<1000){showError('Lỗi','Vui lòng nhập số tiền ít nhất 1.000đ!');return;}
  openTopupModal(amount);
}
function openTopupModal(amount){
  const fd=new FormData();fd.append('amount',amount);
  fetch('/api/topup-request',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    if(!d.ok){showError('❌',d.msg||'Lỗi tạo yêu cầu');return;}
    document.getElementById('topup-content').textContent=d.content;
    if(d.bank_name){const el=document.getElementById('tm-bank');if(el)el.textContent=d.bank_name;}
    if(d.bank_account){const el=document.getElementById('tm-acc');if(el)el.textContent=d.bank_account;}
    if(d.bank_holder){const el=document.getElementById('tm-holder');if(el)el.textContent=d.bank_holder;}
    const tgEl=document.getElementById('topup-tg-link');
    if(tgEl)tgEl.href=d.tg_link||'https://t.me/""" + ADMIN_TG_USERNAME + """';
    if(_topupTimer)clearInterval(_topupTimer);
    const expires=d.expires;
    function updateTimer(){
      const left=Math.max(0,expires-Math.floor(Date.now()/1000));
      const m=Math.floor(left/60),s=left%60;
      const el=document.getElementById('topup-countdown');
      if(el)el.textContent=m+':'+(s<10?'0':'')+s;
      if(left<=0){clearInterval(_topupTimer);const box=document.getElementById('topup-timer');if(box)box.textContent='⏰ Đã hết hạn! Tạo yêu cầu mới.';}
    }
    updateTimer();
    _topupTimer=setInterval(updateTimer,1000);
    document.getElementById('topup-modal').classList.add('show');
    loadMyTopups();
  }).catch(()=>{showError('Lỗi kết nối','Vui lòng thử lại!');});
}
function updCarryTotal(){
  const stars=parseInt(document.getElementById('carry-stars').value)||0;
  const rank=document.getElementById('carry-rank').value;
  const pricePerStar=RANK_PRICE[rank]||0;
  let total=0;
  if(stars>0&&pricePerStar>0){
    total=stars*pricePerStar;
    total=Math.ceil(total/1000)*1000;
    if(stars>=10){
      const discount=Math.floor(total*0.10);
      total=total-discount;
      total=Math.ceil(total/1000)*1000;
    }
  }
  const el=document.getElementById('carry-total-display');
  if(el)el.textContent=total>0?total.toLocaleString('vi-VN')+'đ':'0đ';
  const noteEl=document.getElementById('carry-price-per-star');
  if(noteEl){
    if(rank&&pricePerStar>0){
      let note='1 ⭐ = '+pricePerStar.toLocaleString('vi-VN')+'đ | Tổng cần thanh toán';
      if(stars>=10)note+=' (đã giảm 10% 🎁)';
      noteEl.textContent=note;
    } else {
      noteEl.textContent='Chọn rank và nhập số sao để tính tiền';
    }
  }
}
function orderCarry(){
  const stars=parseInt(document.getElementById('carry-stars').value);
  const rank=document.getElementById('carry-rank').value;
  const note=document.getElementById('carry-note').value;
  if(!stars||stars<5){showError('Lỗi','Tối thiểu 5 sao mới nhận kéo!');return;}
  if(stars>200){showError('Lỗi','Số sao tối đa 200!');return;}
  if(!rank){showError('Lỗi','Vui lòng chọn rank hiện tại!');return;}
  const btn=document.getElementById('carry-submit-btn');
  if(btn){btn.textContent='⏳ Đang xử lý...';btn.disabled=true;}
  const fd=new FormData();
  fd.append('stars',stars);fd.append('rank',rank);fd.append('note',note);
  if(_carryDiscountCode)fd.append('code',_carryDiscountCode);
  fetch('/api/carry-order',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    if(btn){btn.textContent='⭐ Đặt Kéo Thuê Ngay';btn.disabled=false;}
    if(!d.ok){
      if(d.need_topup){
        const short=d.short||d.needed||0;
        if(confirm(`⚠️ Số dư không đủ!\nCần nạp thêm ${short.toLocaleString('vi-VN')}đ.\nBạn có muốn nạp tiền ngay không?`)){
          showTopupModal(short,short);
        }
      } else{showError('❌ Lỗi',d.msg||'Có lỗi xảy ra');}
      return;
    }
    document.getElementById('carry-stars').value='';
    document.getElementById('carry-rank').value='';
    document.getElementById('carry-note').value='';
    document.getElementById('carry-total-display').textContent='0đ';
    document.getElementById('carry-price-per-star').textContent='Chọn rank và nhập số sao để tính tiền';
    const tgLink=document.getElementById('carry-tg-link');
    if(tgLink)tgLink.href=d.tg_link||'https://t.me/""" + ADMIN_TG_USERNAME + """';
    const smsg=document.getElementById('carry-success-msg');
    if(smsg)smsg.textContent='✅ Đặt '+stars+' sao (rank '+rank+') thành công! Trừ '+d.total.toLocaleString('vi-VN')+'đ. Liên hệ admin ngay!';
    document.getElementById('carry-modal').classList.add('show');
    updateBalance();
    loadMyCarries();
    showToast('✅ Đặt kéo thuê thành công!','Liên hệ admin để bắt đầu kéo');
  }).catch(()=>{
    if(btn){btn.textContent='⭐ Đặt Kéo Thuê Ngay';btn.disabled=false;}
    showError('Lỗi kết nối','Vui lòng thử lại!');
  });
}
function changePw(){
  const o=document.getElementById('pw-old').value,n=document.getElementById('pw-new').value;
  const msg=document.getElementById('pw-msg');
  if(!o||!n){msg.textContent='Vui lòng nhập đầy đủ!';msg.style.cssText='display:block;background:#fee2e2;color:#991b1b;border-radius:8px;padding:.4rem .6rem;';return;}
  const fd=new FormData();fd.append('old_pw',o);fd.append('new_pw',n);
  fetch('/change-password',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    msg.textContent=d.msg;
    msg.style.cssText=`display:block;background:${d.ok?'#d1fae5':'#fee2e2'};color:${d.ok?'#065f46':'#991b1b'};border-radius:8px;padding:.4rem .6rem;`;
    if(d.ok){showToast('Thành công!','Đang chuyển về đăng nhập...');setTimeout(()=>window.location='/login',2200);}
  }).catch(()=>{msg.textContent='Lỗi kết nối!';msg.style.cssText='display:block;background:#fee2e2;color:#991b1b;border-radius:8px;padding:.4rem .6rem;';});
}
document.addEventListener('DOMContentLoaded',()=>{
  fetch('/api/acc-count').then(r=>r.json()).then(d=>{stockMap=d;renderStock();}).catch(()=>{});
  const first=document.getElementById('pg-home');
  if(first)setTimeout(()=>first.classList.add('visible'),80);
});
</script>
"""

MAIN_TEMPLATE = LAYOUT(MAIN_BODY)

# ── AUTH TEMPLATE ─────────────────────────────────────────────────────────────
AUTH_TEMPLATE = """<!DOCTYPE html>
<html lang="vi">
<head>""" + BASE_CSS + """
<title>{% if mode=='login' %}Đăng Nhập{% else %}Đăng Ký{% endif %} - Shop VKhanh</title>
<style>
body{display:flex;align-items:center;justify-content:center;min-height:100vh;background:linear-gradient(135deg,#f0f4ff 0%,#fdf4ff 100%);padding:1rem;}
.auth-card{background:#fff;border-radius:22px;padding:1.75rem 1.5rem;width:100%;max-width:380px;box-shadow:0 20px 60px rgba(79,70,229,.11);border:1px solid var(--border);animation:authIn .4s cubic-bezier(.34,1.56,.64,1);}
@keyframes authIn{from{transform:translateY(20px);opacity:0}to{transform:translateY(0);opacity:1}}
.auth-tabs{display:flex;background:#f3f4f6;border-radius:11px;padding:.25rem;margin-bottom:1.35rem;}
.auth-tab{flex:1;padding:.5rem;text-align:center;border-radius:8px;font-size:.84rem;font-weight:600;cursor:pointer;color:var(--muted);text-decoration:none;transition:.2s;}
.auth-tab.active{background:#fff;color:var(--accent);box-shadow:0 2px 8px rgba(0,0,0,.07);}
.err-box{background:#fee2e2;border:1px solid #fca5a5;border-radius:10px;padding:.6rem .85rem;font-size:.8rem;color:#991b1b;margin-bottom:.9rem;font-weight:500;}
.ok-box{background:#d1fae5;border:1px solid #6ee7b7;border-radius:10px;padding:.6rem .85rem;font-size:.8rem;color:#065f46;margin-bottom:.9rem;font-weight:500;}
</style>
</head>
<body>
<div id="st-overlay"></div>
<div id="st"><div class="st-check"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg></div><div class="st-msg"></div><div class="st-sub"></div></div>
<div id="et"><div class="et-x"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></div><div class="et-msg"></div><div class="et-sub"></div></div>
<div class="auth-card">
  <div style="text-align:center;margin-bottom:1.1rem;">
    <div style="font-size:1.45rem;font-weight:800;color:var(--primary);">Shop <span style="color:var(--accent);">VKhanh</span></div>
    <div style="font-size:.78rem;color:var(--muted);margin-top:.2rem;">Cày Thuê & Bán Acc Free Fire Uy Tín</div>
  </div>
  <div class="auth-tabs">
    <a href="/login" class="auth-tab {% if mode=='login' %}active{% endif %}">Đăng Nhập</a>
    <a href="/register" class="auth-tab {% if mode=='register' %}active{% endif %}">Đăng Ký</a>
  </div>
  {% if error %}<div class="err-box">{{ error }}</div>{% endif %}
  {% if request.args.get('registered') %}<div class="ok-box">✅ Đăng ký thành công! Hãy đăng nhập để tiếp tục.</div>{% endif %}
  <form method="POST" autocomplete="on">
    {% if mode=='register' %}
    <div class="fg"><label class="fl">Tên hiển thị (tùy chọn)</label><input class="fi" name="display" placeholder="Tên của bạn" autocomplete="name"></div>
    {% endif %}
    <div class="fg"><label class="fl">Tên đăng nhập</label><input class="fi" name="username" placeholder="Nhập tên đăng nhập" required autocomplete="username" value="{{ prefill_user }}"></div>
    <div class="fg"><label class="fl">Mật khẩu</label><input class="fi" type="password" name="password" placeholder="Nhập mật khẩu" required autocomplete="{% if mode=='login' %}current-password{% else %}new-password{% endif %}"></div>
    {% if need_captcha %}
    <div class="cap-box">
      <div class="cap-q">{{ cap_a }} + {{ cap_b }} = ?</div>
      <input class="cap-input" name="captcha_answer" placeholder="?" type="number" required inputmode="numeric">
    </div>
    {% endif %}
    <button type="submit" class="btn btn-primary btn-full" style="font-size:.9rem;padding:.75rem;">
      {% if mode=='login' %}🔓 Đăng Nhập{% else %}✨ Tạo Tài Khoản{% endif %}
    </button>
  </form>
  <div style="text-align:center;margin-top:.9rem;font-size:.78rem;color:var(--muted);">
    {% if mode=='login' %}Chưa có tài khoản? <a href="/register" style="color:var(--accent);font-weight:600;">Đăng ký ngay</a>
    {% else %}Đã có tài khoản? <a href="/login" style="color:var(--accent);font-weight:600;">Đăng nhập</a>{% endif %}
  </div>
</div>
<script>window.NO_MUSIC=true;</script>
""" + BASE_JS + """
</body></html>"""

# ── ADMIN LOGIN ────────────────────────────────────────────────────────────────
ADMIN_LOGIN_TMPL = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin Login - Shop VKhanh</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',sans-serif;}
body{background:linear-gradient(135deg,#1a1a2e,#16213e,#0f3460);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:1rem;}
.card{background:rgba(255,255,255,.05);backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,.1);border-radius:20px;padding:2rem;width:100%;max-width:380px;animation:fadeIn .4s ease;}
@keyframes fadeIn{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
h1{color:#fff;font-size:1.4rem;font-weight:800;margin-bottom:.3rem;}
p{color:rgba(255,255,255,.6);font-size:.82rem;margin-bottom:1.5rem;}
label{display:block;color:rgba(255,255,255,.7);font-size:.76rem;font-weight:600;margin-bottom:.35rem;text-transform:uppercase;letter-spacing:.04em;}
input{width:100%;padding:.75rem 1rem;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.15);border-radius:10px;color:#fff;font-size:.9rem;outline:none;margin-bottom:1rem;transition:.2s;}
input:focus{border-color:#4f46e5;background:rgba(255,255,255,.12);}
input::placeholder{color:rgba(255,255,255,.4);}
button{width:100%;padding:.8rem;background:linear-gradient(135deg,#4f46e5,#7c3aed);color:#fff;border:none;border-radius:10px;font-size:.9rem;font-weight:700;cursor:pointer;transition:.2s;}
button:active{transform:scale(.97);}
.err{background:rgba(239,68,68,.2);border:1px solid rgba(239,68,68,.4);color:#fca5a5;border-radius:10px;padding:.6rem .85rem;font-size:.82rem;margin-bottom:1rem;}
</style>
</head>
<body>
<div class="card">
  <h1>🔐 Admin Panel</h1>
  <p>Shop VKhanh Management System</p>
  {% if error %}<div class="err">{{ error }}</div>{% endif %}
  <form method="POST">
    <label>Tên đăng nhập</label>
    <input name="username" placeholder="Admin username" required>
    <label>Mật khẩu</label>
    <input type="password" name="password" placeholder="Admin password" required>
    <button type="submit">Đăng Nhập</button>
  </form>
</div>
</body></html>"""

# ── ADMIN PANEL ────────────────────────────────────────────────────────────────
ADMIN_PANEL_TMPL = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin Panel - Shop VKhanh</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',system-ui,sans-serif;}
:root{--acc:#4f46e5;--acc2:#7c3aed;--bg:#f8f9fb;--white:#fff;--text:#1f2937;--muted:#6b7280;--border:#e5e7eb;--green:#10b981;--red:#ef4444;--orange:#f59e0b;}
body{background:var(--bg);color:var(--text);min-height:100vh;}
.topbar{background:linear-gradient(135deg,var(--acc),var(--acc2));color:#fff;padding:.9rem 1.25rem;display:flex;align-items:center;justify-content:space-between;gap:.5rem;flex-wrap:wrap;}
.topbar h1{font-size:1.1rem;font-weight:800;}
.topbar-btns{display:flex;gap:.5rem;}
.tbtn{padding:.4rem .85rem;border-radius:8px;font-size:.78rem;font-weight:600;cursor:pointer;border:none;transition:.2s;}
.tbtn-out{background:rgba(255,255,255,.2);color:#fff;}
.tbtn-home{background:#fff;color:var(--acc);}
.content{padding:1rem;max-width:960px;margin:0 auto;}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:.7rem;margin-bottom:1.25rem;}
.stat{background:#fff;border-radius:14px;padding:.9rem;border:1px solid var(--border);box-shadow:0 2px 8px rgba(0,0,0,.05);text-align:center;}
.stat-val{font-size:1.4rem;font-weight:800;color:var(--acc);}
.stat-lbl{font-size:.7rem;color:var(--muted);margin-top:.15rem;font-weight:500;}
.tabs{display:flex;gap:.2rem;background:#f3f4f6;padding:.25rem;border-radius:11px;margin-bottom:1.1rem;flex-wrap:wrap;}
.atab{flex:1;min-width:60px;padding:.5rem .2rem;border-radius:8px;text-align:center;font-size:.7rem;font-weight:600;cursor:pointer;color:var(--muted);transition:.2s;white-space:nowrap;}
.atab.active{background:#fff;color:var(--acc);box-shadow:0 2px 6px rgba(0,0,0,.07);}
.panel{display:none;}
.panel.active{display:block;}
.card{background:#fff;border-radius:14px;padding:1rem;border:1px solid var(--border);box-shadow:0 2px 8px rgba(0,0,0,.05);margin-bottom:1rem;}
.card h3{font-size:.9rem;font-weight:700;margin-bottom:.85rem;color:var(--text);}
label{display:block;font-size:.73rem;font-weight:700;color:var(--muted);margin-bottom:.3rem;text-transform:uppercase;}
input,select,textarea{width:100%;padding:.6rem .85rem;border:1.5px solid var(--border);border-radius:9px;font-size:.85rem;background:#fff;outline:none;margin-bottom:.65rem;transition:.15s;}
input:focus,select:focus,textarea:focus{border-color:var(--acc);}
textarea{min-height:70px;resize:vertical;font-family:monospace;}
.btn{display:inline-flex;align-items:center;justify-content:center;padding:.5rem 1.1rem;border-radius:9px;font-weight:600;font-size:.82rem;cursor:pointer;border:none;transition:.2s;gap:.35rem;}
.btn:active{transform:scale(.96);}
.btn-p{background:linear-gradient(135deg,var(--acc),var(--acc2));color:#fff;}
.btn-g{background:var(--green);color:#fff;}
.btn-r{background:var(--red);color:#fff;}
.btn-o{background:var(--orange);color:#fff;}
.btn-sm{padding:.3rem .7rem;font-size:.74rem;border-radius:7px;}
.btn-full{width:100%;}
.msg{padding:.5rem .75rem;border-radius:8px;font-size:.8rem;margin-top:.4rem;display:none;}
.msg.ok{background:#d1fae5;color:#065f46;}
.msg.err{background:#fee2e2;color:#991b1b;}
table{width:100%;border-collapse:collapse;font-size:.78rem;}
th{background:#f3f4f6;padding:.5rem .6rem;text-align:left;font-weight:600;color:var(--muted);font-size:.7rem;text-transform:uppercase;}
td{padding:.55rem .6rem;border-bottom:1px solid var(--border);vertical-align:top;}
tr:last-child td{border:none;}
tr:hover td{background:#f9fafb;}
.badge{display:inline-block;padding:.15rem .5rem;border-radius:20px;font-size:.67rem;font-weight:700;}
.badge-g{background:#d1fae5;color:#065f46;}
.badge-r{background:#fee2e2;color:#991b1b;}
.badge-o{background:#fef3c7;color:#92400e;}
.log-row{display:flex;gap:.6rem;padding:.5rem 0;border-bottom:1px solid var(--border);font-size:.78rem;}
.log-time{color:var(--muted);white-space:nowrap;flex-shrink:0;font-size:.72rem;}
.log-event{font-weight:600;color:var(--acc);flex-shrink:0;min-width:110px;}
.log-detail{color:var(--text);flex:1;word-break:break-word;}
.topup-card{background:#f0fdf4;border:1px solid #bbf7d0;border-radius:11px;padding:.9rem;margin-bottom:.7rem;}
.fb-card{background:#f8f9fb;border:1px solid var(--border);border-radius:12px;padding:.9rem;margin-bottom:.7rem;display:flex;gap:.8rem;align-items:flex-start;}
.fb-media{width:80px;height:60px;object-fit:cover;border-radius:8px;flex-shrink:0;background:#e5e7eb;}
.order-detail{background:#f8f9fb;border-radius:8px;padding:.5rem .7rem;margin-top:.35rem;font-size:.72rem;font-family:monospace;border:1px solid var(--border);}
</style>
</head>
<body>
<div class="topbar">
  <h1>⚙️ Admin Panel - Shop VKhanh</h1>
  <div class="topbar-btns">
    <a href="/"><button class="tbtn tbtn-home">🏠 Web</button></a>
    <a href="/admin/logout"><button class="tbtn tbtn-out">Đăng Xuất</button></a>
  </div>
</div>
<div class="content">
  <div class="stats">
    <div class="stat"><div class="stat-val">{{ stats.users }}</div><div class="stat-lbl">👥 Users</div></div>
    <div class="stat"><div class="stat-val">{{ stats.orders }}</div><div class="stat-lbl">🛒 Đơn hàng</div></div>
    <div class="stat"><div class="stat-val">{{ stats.carry_orders }}</div><div class="stat-lbl">🏆 Kéo thuê</div></div>
    <div class="stat"><div class="stat-val">{{ db.get('custom_accs',[])|length }}</div><div class="stat-lbl">🎮 Acc TC</div></div>
    <div class="stat"><div class="stat-val">{{ "{:,.0f}".format(stats.revenue) }}đ</div><div class="stat-lbl">💰 Doanh thu</div></div>
    <div class="stat"><div class="stat-val">{{ stats.acc_kim }}</div><div class="stat-lbl">💜 Kim Cương</div></div>
    <div class="stat"><div class="stat-val">{{ stats.acc_bach }}</div><div class="stat-lbl">🔵 Bạch Kim</div></div>
    <div class="stat"><div class="stat-val">{{ stats.acc_lv5 }}</div><div class="stat-lbl">🟢 Lv5</div></div>
    <div class="stat"><div class="stat-val">{{ stats.feedback_count }}</div><div class="stat-lbl">🏅 Feedback</div></div>
    {% if stats.pending_topup > 0 %}
    <div class="stat" style="border-color:#fbbf24;background:#fffbeb;"><div class="stat-val" style="color:var(--orange);">{{ stats.pending_topup }}</div><div class="stat-lbl">💰 Nạp chờ</div></div>
    {% endif %}
  </div>

  <div class="tabs">
    <div class="atab active" onclick="aTab('acc',this)">📦 Acc</div>
    <div class="atab" onclick="aTab('customacc',this)">🎮 Acc TC</div>
    <div class="atab" onclick="aTab('users',this)">👥 Users</div>
    <div class="atab" onclick="aTab('orders',this)">🛒 Đơn Mua</div>
    <div class="atab" onclick="aTab('carry',this)">🏆 Kéo Thuê</div>
    <div class="atab" onclick="aTab('feedback',this)">🏅 Feedback</div>
    <div class="atab" onclick="aTab('discount',this)">🎟️ Mã GG</div>
    <div class="atab" onclick="aTab('balance',this)">💰 Số Dư</div>
    <div class="atab" onclick="aTab('topup',this)">💳 Nạp Tiền</div>
    <div class="atab" onclick="aTab('notice',this)">📢 TB</div>
    <div class="atab" onclick="aTab('logs',this)">📋 Logs</div>
    <div class="atab" onclick="aTab('msg',this)">✉️ Gửi TB</div>
  </div>

  <!-- CUSTOM ACC TAB -->
  <div class="panel" id="pn-customacc">
    <div class="card">
      <h3>➕ Thêm Acc Tự Chọn</h3>
      <label>Ảnh (upload hoặc URL)</label>
      <input type="file" id="ca-file" accept="image/*" style="margin-bottom:.65rem;">
      <input id="ca-img-url" placeholder="Hoặc nhập URL ảnh (không bắt buộc)">
      <label>Tên đăng nhập acc</label>
      <input id="ca-user" placeholder="Username / Email">
      <label>Mật khẩu acc</label>
      <input id="ca-pass" placeholder="Mật khẩu">
      <label>Nền tảng</label>
      <input id="ca-platform" placeholder="Facebook / Google / Garena..." value="Facebook">
      <label>Mô tả (rank, skin, thông tin nổi bật...)</label>
      <textarea id="ca-desc" placeholder="Ví dụ: Rank Kim Cương I, có skin AK đỏ, Lv15..."></textarea>
      <label>Giá bán (đ)</label>
      <input type="number" id="ca-price" placeholder="Ví dụ: 150000" min="0">
      <button class="btn btn-p btn-full" onclick="addCustomAcc()">➕ Thêm Acc Tự Chọn</button>
      <div class="msg" id="ca-msg"></div>
    </div>
    <div class="card">
      <h3>📋 Danh Sách Acc Tự Chọn ({{ db.get('custom_accs',[])|length }} acc)</h3>
      {% if db.get('custom_accs') %}
        {% for a in db.custom_accs %}
        <div class="fb-card" style="align-items:flex-start;flex-wrap:wrap;">
          {% if a.image_url %}
          <img src="{{ a.image_url }}" class="fb-media" alt="Acc" onerror="this.style.background='#e5e7eb'">
          {% endif %}
          <div style="flex:1;min-width:0;">
            <div style="font-size:.8rem;font-weight:700;color:var(--acc);margin-bottom:.2rem;">{{ a.platform or 'N/A' }}</div>
            {% if a.acc_user %}<div style="font-size:.77rem;font-family:monospace;color:var(--text);">👤 {{ a.acc_user }}</div>{% endif %}
            {% if a.desc %}<div style="font-size:.78rem;color:var(--text);margin-top:.2rem;line-height:1.4;">{{ a.desc }}</div>{% endif %}
            <div style="font-size:.8rem;font-weight:700;color:var(--green);margin-top:.25rem;">{{ "{:,}".format(a.price) }}đ</div>
            <div style="font-size:.7rem;color:var(--muted);margin-top:.15rem;">⏰ {{ a.time if a.get('time') else a.added }}</div>
          </div>
          <button class="btn btn-r btn-sm" style="flex-shrink:0;margin-top:.2rem;" onclick="delCustomAcc('{{ a.id }}')">Xóa</button>
        </div>
        {% endfor %}
      {% else %}
      <div style="color:var(--muted);font-size:.85rem;padding:1rem;text-align:center;">Chưa có acc tự chọn nào</div>
      {% endif %}
    </div>
  </div>

  <!-- ACC TAB -->
  <div class="panel active" id="pn-acc">
    <div class="card">
      <h3>➕ Thêm Acc Mới</h3>
      <label>Loại Acc</label>
      <select id="acc-cat">
        <option value="kim_cuong">💜 Kim Cương (20.000đ)</option>
        <option value="bach_kim">🔵 Bạch Kim (15.000đ)</option>
        <option value="lv5">🟢 Lv5 Google (2.500đ)</option>
      </select>
      <label>Thêm nhiều acc (mỗi dòng: user:pass:platform:mô tả)</label>
      <textarea id="acc-bulk" placeholder="user1:pass1:Facebook:mô tả&#10;user2:pass2:Google:mô tả&#10;..."></textarea>
      <label>Hoặc thêm 1 acc:</label>
      <input id="acc-user" placeholder="Username / Email">
      <input id="acc-pass" placeholder="Mật khẩu">
      <input id="acc-platform" placeholder="Platform (Facebook/Google/...)" value="Facebook">
      <input id="acc-desc" placeholder="Mô tả (tùy chọn)">
      <button class="btn btn-p btn-full" onclick="addAcc()">➕ Thêm Acc</button>
      <div class="msg" id="acc-msg"></div>
    </div>
    <div class="card">
      <h3>📋 Danh Sách Acc</h3>
      {% for cat in ['kim_cuong', 'bach_kim', 'lv5'] %}
      <div style="margin-bottom:1rem;">
        <div style="font-weight:700;font-size:.88rem;margin-bottom:.5rem;">
          {{ '💜' if cat=='kim_cuong' else '🔵' if cat=='bach_kim' else '🟢' }} {{ cat }} —
          <span style="color:var(--green);">{{ db.accounts.get(cat,[])|selectattr('sold','equalto',False)|list|length }} còn</span> /
          {{ db.accounts.get(cat,[])|length }} tổng
        </div>
        {% if db.accounts.get(cat) %}
        <table>
          <tr><th>#</th><th>Username</th><th>Pass</th><th>Platform</th><th>Thêm lúc</th><th>Trạng thái</th><th>Bán cho</th><th>Xóa</th></tr>
          {% for a in db.accounts[cat][-50:]|reverse %}
          <tr>
            <td style="color:var(--muted);font-size:.7rem;">{{ loop.index }}</td>
            <td style="font-family:monospace;font-weight:600;">{{ a.user }}</td>
            <td style="font-family:monospace;">{{ a.pass }}</td>
            <td style="font-size:.74rem;">{{ a.get('platform','') }}</td>
            <td style="font-size:.7rem;color:var(--muted);">{{ a.get('added','') }}</td>
            <td>{% if a.get('sold') %}<span class="badge badge-r">✅ Đã bán</span>{% else %}<span class="badge badge-g">Còn</span>{% endif %}</td>
            <td style="font-size:.72rem;color:var(--acc);">{{ a.get('sold_to_name','') }}{% if a.get('sold_time') %}<br><span style="color:var(--muted);font-size:.68rem;">{{ a.sold_time }}</span>{% endif %}</td>
            <td><button class="btn btn-r btn-sm" onclick="delAcc('{{ cat }}','{{ a.id }}')">Xóa</button></td>
          </tr>
          {% endfor %}
        </table>
        {% else %}<div style="color:var(--muted);font-size:.8rem;">Chưa có acc</div>{% endif %}
      </div>
      {% endfor %}
    </div>
  </div>

  <!-- USERS TAB -->
  <div class="panel" id="pn-users">
    <div class="card">
      <h3>👥 Danh Sách Users ({{ db.users|length }})</h3>
      <table>
        <tr><th>Username</th><th>Số dư</th><th>Ngày tạo</th><th>IP</th><th>Xóa</th></tr>
        {% for uid, u in db.users.items() %}
        <tr>
          <td><b>{{ u.username }}</b>{% if u.get('display') and u.display != u.username %} <span style="color:var(--muted);font-size:.74rem;">({{ u.display }})</span>{% endif %}</td>
          <td style="color:var(--acc);font-weight:700;">{{ "{:,}".format(u.get('balance',0)) }}đ</td>
          <td style="font-size:.74rem;color:var(--muted);">{{ u.get('created','') }}</td>
          <td style="font-size:.74rem;color:var(--muted);">{{ u.get('last_ip','') }}</td>
          <td><button class="btn btn-r btn-sm" onclick="delUser('{{ uid }}')">Xóa</button></td>
        </tr>
        {% endfor %}
      </table>
    </div>
  </div>

  <!-- ORDERS TAB — ĐẦY ĐỦ CHI TIẾT AI MUA ACC NÀO LÚC MẤY GIỜ -->
  <div class="panel" id="pn-orders">
    <div class="card">
      <h3>🛒 Lịch Sử Mua Acc ({{ db.orders|length }} đơn)</h3>
      <div style="font-size:.78rem;color:var(--muted);margin-bottom:.8rem;background:#eef2ff;padding:.5rem .7rem;border-radius:8px;border:1px solid #c7d2fe;">
        💡 Bảng hiển thị đầy đủ: ai mua acc nào, lúc mấy giờ ngày nào (giờ Việt Nam), thông tin acc đã bán.
      </div>
      {% if db.orders %}
      <table>
        <tr><th>⏰ Thời gian (VN)</th><th>👤 User</th><th>📦 Loại</th><th>SL</th><th>💰 Tiền</th><th>📋 Chi tiết Acc</th></tr>
        {% for o in db.orders|reverse %}
        <tr>
          <td style="font-size:.72rem;color:var(--muted);white-space:nowrap;font-weight:600;">{{ o.time }}</td>
          <td><b style="color:var(--acc);">{{ o.username }}</b><br><span style="font-size:.68rem;color:var(--muted);">{{ o.get('id','') }}</span></td>
          <td style="font-size:.78rem;">{{ o.get('cat_name', o.cat) }}</td>
          <td style="text-align:center;font-weight:700;">{{ o.qty }}</td>
          <td style="color:var(--green);font-weight:700;white-space:nowrap;">{{ "{:,}".format(o.total) }}đ</td>
          <td>
            {% for a in o.get('accs',[]) %}
            <div class="order-detail">
              <span style="color:var(--muted);">{{ a.get('platform','FB') }}</span> |
              <b>{{ a.user }}</b> : {{ a.pass }}
              {% if a.get('desc') %}<br><span style="color:var(--muted);">{{ a.desc }}</span>{% endif %}
            </div>
            {% endfor %}
          </td>
        </tr>
        {% else %}
        <tr><td colspan="6" style="text-align:center;color:var(--muted);padding:1.5rem;">Chưa có đơn hàng nào</td></tr>
        {% endfor %}
      </table>
      {% else %}
      <div style="color:var(--muted);font-size:.85rem;padding:1rem;text-align:center;">Chưa có đơn hàng nào</div>
      {% endif %}
    </div>
  </div>

  <!-- CARRY TAB — ĐẦY ĐỦ CHI TIẾT AI GỬI ĐƠN CÀY LÚC MẤY GIỜ -->
  <div class="panel" id="pn-carry">
    <div class="card">
      <h3>🏆 Lịch Sử Đơn Kéo Thuê ({{ db.get('carry_orders',[])|length }} đơn)</h3>
      <div style="font-size:.78rem;color:var(--muted);margin-bottom:.8rem;background:#fffbeb;padding:.5rem .7rem;border-radius:8px;border:1px solid #fde68a;">
        💡 Bảng giá: Đồng~Kim Cương = 1.000đ/sao | Cao Thủ~Thách Đấu = 1.500đ/sao | Từ 10 sao giảm 10%
      </div>
      {% if db.get('carry_orders') %}
      <table>
        <tr><th>⏰ Thời gian (VN)</th><th>👤 User</th><th>⭐ Sao</th><th>🎮 Rank</th><th>Đơn giá</th><th>📝 Ghi chú</th><th>💰 Tổng</th><th>Trạng thái</th><th>Hành động</th></tr>
        {% for o in db.get('carry_orders',[])|reverse %}
        <tr>
          <td style="font-size:.72rem;color:var(--muted);white-space:nowrap;font-weight:600;">{{ o.time }}</td>
          <td><b style="color:var(--acc);">{{ o.username }}</b><br><span style="font-size:.68rem;color:var(--muted);">{{ o.get('id','') }}</span></td>
          <td style="font-weight:700;font-size:.9rem;">⭐ {{ o.stars }}</td>
          <td style="font-weight:600;">{{ o.get('rank','') }}</td>
          <td style="font-size:.74rem;color:var(--muted);">{{ "{:,}".format(o.get('price_per_star',1000)) }}đ/⭐</td>
          <td style="font-size:.74rem;color:var(--text);max-width:120px;word-break:break-word;">{{ o.get('note','') or '—' }}</td>
          <td style="color:var(--green);font-weight:700;white-space:nowrap;">{{ "{:,}".format(o.total) }}đ</td>
          <td><span class="badge {{ 'badge-o' if o.get('status','pending')=='pending' else 'badge-g' }}">{{ '⏳ Chờ' if o.get('status','pending')=='pending' else '✅ Xong' }}</span></td>
          <td style="white-space:nowrap;">
            {% if o.get('status','pending') == 'pending' %}
            <button class="btn btn-g btn-sm" style="margin-bottom:.25rem;" onclick="approveCarry('{{ o.get('id','') }}','{{ o.username }}')">✅ Duyệt xong</button><br>
            {% endif %}
            <a href="https://t.me/{{ ADMIN_TG_USERNAME }}" target="_blank"><button class="btn btn-sm" style="background:linear-gradient(135deg,#0088cc,#006699);color:#fff;margin-bottom:.25rem;">✈️ TG</button></a>
            <a href="{{ TIKTOK_URL }}" target="_blank"><button class="btn btn-sm" style="background:linear-gradient(135deg,#010101,#333);color:#fff;">🎵 TikTok</button></a>
          </td>
        </tr>
        {% endfor %}
      </table>
      {% else %}
      <div style="color:var(--muted);font-size:.85rem;padding:1rem;text-align:center;">Chưa có đơn kéo thuê nào</div>
      {% endif %}
    </div>
  </div>

  <!-- FEEDBACK TAB -->
  <div class="panel" id="pn-feedback">
    <div class="card">
      <h3>🏅 Thêm Feedback Kéo Rank</h3>
      <p style="font-size:.8rem;color:var(--muted);margin-bottom:.8rem;">Upload ảnh/video feedback kéo rank của khách hàng. Sẽ hiển thị trên trang chủ.</p>
      <label>Ảnh hoặc Video (jpg/png/gif/webp/mp4/webm)</label>
      <input type="file" id="fb-file" accept="image/*,video/mp4,video/webm" style="padding:.4rem;">
      <label>Hoặc nhập URL ảnh/video</label>
      <input id="fb-url" placeholder="https://... hoặc /tên-file.jpg">
      <label>Mô tả (nội dung feedback)</label>
      <textarea id="fb-desc" placeholder="Ví dụ: Khách kéo từ Kim Cương lên Cao Thủ trong 2 ngày..." style="min-height:80px;"></textarea>
      <label>Tên khách hàng (tùy chọn)</label>
      <input id="fb-customer" placeholder="Tên khách hàng (để trống nếu ẩn danh)">
      <button class="btn btn-p btn-full" onclick="addFeedback()">📤 Đăng Feedback</button>
      <div class="msg" id="fb-msg"></div>
    </div>
    <div class="card">
      <h3>📋 Danh Sách Feedback ({{ db.get('feedback_posts',[])|length }} bài)</h3>
      {% if db.get('feedback_posts') %}
        {% for p in db.feedback_posts %}
        <div class="fb-card">
          {% if p.media_url %}
            {% if p.media_type == 'video' %}
            <video src="{{ p.media_url }}" class="fb-media" style="width:80px;height:60px;border-radius:8px;object-fit:cover;" muted></video>
            {% else %}
            <img src="{{ p.media_url }}" class="fb-media" alt="Feedback" onerror="this.style.background='#e5e7eb'">
            {% endif %}
          {% endif %}
          <div style="flex:1;min-width:0;">
            <div style="font-size:.8rem;color:var(--text);margin-bottom:.3rem;line-height:1.45;">{{ p.desc or '(Không có mô tả)' }}</div>
            {% if p.customer %}<div style="font-size:.73rem;color:var(--acc);font-weight:600;">👤 {{ p.customer }}</div>{% endif %}
            <div style="font-size:.7rem;color:var(--muted);margin-top:.2rem;">⏰ {{ p.time }}</div>
          </div>
          <button class="btn btn-r btn-sm" style="flex-shrink:0;" onclick="delFeedback('{{ p.id }}')">Xóa</button>
        </div>
        {% endfor %}
      {% else %}
      <div style="color:var(--muted);font-size:.85rem;padding:1rem;text-align:center;">Chưa có feedback nào</div>
      {% endif %}
    </div>
  </div>

  <!-- DISCOUNT CODE TAB -->
  <div class="panel" id="pn-discount">
    <div class="card">
      <h3>🎟️ Tạo Mã Giảm Giá</h3>
      <label>Mã (để trống = tự động tạo)</label>
      <input id="dc-code" placeholder="Ví dụ: SALE20 (để trống = random)" style="text-transform:uppercase;" oninput="this.value=this.value.toUpperCase()">
      <label>Giảm bao nhiêu % (1–100)</label>
      <input type="number" id="dc-pct" placeholder="Ví dụ: 20" min="1" max="100">
      <label>Thời hạn</label>
      <select id="dc-duration">
        <option value="forever">Vĩnh viễn</option>
        <option value="24h">24 Giờ</option>
        <option value="5d">5 Ngày</option>
        <option value="10d">10 Ngày</option>
        <option value="30d">30 Ngày</option>
        <option value="custom">Tùy chỉnh (giờ)</option>
      </select>
      <div id="dc-custom-hours-row" style="display:none;">
        <label>Số giờ</label>
        <input type="number" id="dc-custom-hours" placeholder="Ví dụ: 48">
      </div>
      <button class="btn btn-p btn-full" onclick="addDiscountCode()">🎟️ Tạo Mã Giảm Giá</button>
      <div class="msg" id="dc-msg"></div>
    </div>
    <div class="card">
      <h3>📋 Danh Sách Mã Giảm Giá ({{ db.get('discount_codes',{})|length }} mã)</h3>
      {% if db.get('discount_codes') %}
        {% for code, c in db.discount_codes.items() %}
        <div style="background:#f8f9fb;border-radius:11px;padding:.8rem;margin-bottom:.6rem;border:1px solid var(--border);display:flex;justify-content:space-between;align-items:flex-start;gap:.5rem;flex-wrap:wrap;">
          <div>
            <div style="font-family:monospace;font-weight:700;font-size:.95rem;color:var(--acc);">{{ code }}</div>
            <div style="font-size:.78rem;color:var(--text);margin-top:.2rem;">🎁 Giảm <b>{{ c.discount_pct }}%</b> | ⏰ {{ c.duration_label }}{% if c.expires_at %} | hết hạn: {{ c.get('expires_at_str', '') }}{% endif %}</div>
            <div style="font-size:.72rem;color:var(--muted);margin-top:.1rem;">Đã dùng: {{ c.used_by|length }} lần | Tạo: {{ c.created }}</div>
          </div>
          <button class="btn btn-r btn-sm" onclick="delDiscountCode('{{ code }}')">Xóa</button>
        </div>
        {% endfor %}
      {% else %}
        <div style="color:var(--muted);font-size:.85rem;padding:1rem;text-align:center;">Chưa có mã giảm giá nào</div>
      {% endif %}
    </div>
  </div>

  <!-- BALANCE TAB -->
  <div class="panel" id="pn-balance">
    <div class="card">
      <h3>💰 Quản Lý Số Dư</h3>
      <label>Tên user</label>
      <input id="bal-user" placeholder="Tên đăng nhập user">
      <label>Số tiền (đ)</label>
      <input type="number" id="bal-amount" placeholder="Số tiền" min="0">
      <div style="display:flex;gap:.6rem;">
        <button class="btn btn-g" style="flex:1;" onclick="doBalance('add')">➕ Cộng Tiền</button>
        <button class="btn btn-r" style="flex:1;" onclick="doBalance('sub')">➖ Trừ Tiền</button>
      </div>
      <div class="msg" id="bal-msg"></div>
    </div>
  </div>

  <!-- TOPUP TAB -->
  <div class="panel" id="pn-topup">
    <div class="card">
      <h3>💳 Yêu Cầu Nạp Tiền</h3>
      <div id="topup-list">
        {% set pending = [] %}
        {% for k, r in db.get('topup_requests', {}).items() %}{% if r.status == 'pending' %}{% set _ = pending.append(r) %}{% endif %}{% endfor %}
        {% if pending %}
          {% for r in pending %}
          <div class="topup-card">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:.5rem;flex-wrap:wrap;">
              <div>
                <div style="font-weight:700;">👤 {{ r.username }}</div>
                <div style="font-size:.82rem;color:var(--muted);">💵 {{ "{:,}".format(r.amount) }}đ</div>
                <div style="font-size:.76rem;color:var(--muted);">🏦 {{ r.get('bank_name','MBBank') }} | 💳 {{ r.get('bank_account','') }}</div>
                <div style="font-size:.76rem;color:var(--muted);">📝 Mã: <code style="background:#f3f4f6;padding:.1rem .35rem;border-radius:4px;">{{ r.content }}</code></div>
                <div style="font-size:.74rem;color:var(--muted);">⏰ {{ r.created }}</div>
              </div>
              <div style="display:flex;gap:.4rem;">
                <button class="btn btn-g btn-sm" onclick="approveTopup('{{ r.content }}',{{ r.amount }})">✅ Duyệt</button>
                <button class="btn btn-r btn-sm" onclick="rejectTopup('{{ r.content }}')">❌ Từ chối</button>
              </div>
            </div>
          </div>
          {% endfor %}
        {% else %}
          <div style="color:var(--muted);font-size:.85rem;padding:1rem;text-align:center;">✅ Không có yêu cầu nào đang chờ</div>
        {% endif %}
      </div>
      <div style="border-top:1px solid var(--border);padding-top:.9rem;margin-top:.9rem;">
        <h3 style="margin-bottom:.7rem;">Duyệt thủ công theo mã</h3>
        <label>Mã nội dung chuyển khoản</label>
        <input id="tp-content" placeholder="Ví dụ: NAPTIENABCD1234">
        <label>Số tiền (đ)</label>
        <input type="number" id="tp-amount" placeholder="Số tiền">
        <button class="btn btn-p btn-full" onclick="manualApprove()">✅ Duyệt Nạp Tiền</button>
        <div class="msg" id="tp-msg"></div>
      </div>
    </div>
  </div>

  <!-- NOTICE TAB -->
  <div class="panel" id="pn-notice">
    <div class="card">
      <h3>📢 Thông Báo Nổi</h3>
      <label>Nội dung thông báo (để trống để không hiện)</label>
      <textarea id="notice-txt" placeholder="Nhập thông báo hiển thị cho toàn bộ users...">{{ db.admin_notice }}</textarea>
      <label>Mô tả nút bấm (để trống để ẩn)</label>
      <input id="notice-btn-desc" placeholder="Ví dụ: Liên hệ ngay để được hỗ trợ..." value="{{ db.get('notice_btn_desc','') }}">
      <label>Link Telegram (để trống để ẩn nút)</label>
      <input id="notice-tg-link" placeholder="Ví dụ: https://t.me/..." value="{{ db.get('notice_tg_link','') }}">
      <label>Link Zalo (để trống để ẩn nút)</label>
      <input id="notice-zalo-link" placeholder="Ví dụ: https://zalo.me/..." value="{{ db.get('notice_zalo_link','') }}">
      <div style="display:flex;gap:.6rem;">
        <button class="btn btn-p" style="flex:1;" onclick="setNotice()">💾 Lưu Thông Báo</button>
        <button class="btn btn-r" onclick="clearNotice()">🗑️ Xóa Hết</button>
      </div>
      <div class="msg" id="notice-msg"></div>
    </div>
  </div>

  <!-- LOGS TAB -->
  <div class="panel" id="pn-logs">
    <div class="card">
      <h3>📋 Nhật Ký Hoạt Động</h3>
      <div style="display:flex;gap:.5rem;margin-bottom:.9rem;">
        <input id="log-search" placeholder="🔍 Tìm kiếm nhật ký..." style="flex:1;margin:0;" oninput="filterLogs()">
        <button class="btn btn-p btn-sm" onclick="loadLogs(1)">Tải lại</button>
      </div>
      <div id="log-container">
        {% for l in db.logs[:100] %}
        <div class="log-row">
          <span class="log-time">{{ l.time }}</span>
          <span class="log-event">{{ l.event }}</span>
          <span class="log-detail">{{ l.detail }} {% if l.user != 'system' %}<span style="color:var(--muted);font-size:.72rem;">({{ l.user }})</span>{% endif %}</span>
        </div>
        {% else %}
        <div style="color:var(--muted);font-size:.82rem;padding:.5rem;">Chưa có nhật ký</div>
        {% endfor %}
      </div>
      <div id="log-pages" style="display:flex;gap:.4rem;margin-top:.75rem;flex-wrap:wrap;"></div>
    </div>
  </div>

  <!-- MSG TAB -->
  <div class="panel" id="pn-msg">
    <div class="card">
      <h3>✉️ Gửi Thông Báo Cho User</h3>
      <label>Tên user</label>
      <input id="msg-user" placeholder="Tên đăng nhập">
      <label>Nội dung thông báo</label>
      <textarea id="msg-txt" placeholder="Nhập nội dung cần gửi..."></textarea>
      <button class="btn btn-p btn-full" onclick="sendMsg()">✉️ Gửi Thông Báo</button>
      <div class="msg" id="msg-res"></div>
    </div>
  </div>
</div>

<script>
function aTab(id,el){
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.atab').forEach(t=>t.classList.remove('active'));
  const pn=document.getElementById('pn-'+id);if(pn)pn.classList.add('active');
  if(el)el.classList.add('active');
  if(id==='logs')loadLogs(1);
}
function showMsg(id,ok,txt){
  const el=document.getElementById(id);if(!el)return;
  el.textContent=txt;el.className='msg '+(ok?'ok':'err');el.style.display='block';
  setTimeout(()=>el.style.display='none',3500);
}
function addAcc(){
  const fd=new FormData();
  fd.append('cat',document.getElementById('acc-cat').value);
  fd.append('bulk_accs',document.getElementById('acc-bulk').value);
  fd.append('acc_user',document.getElementById('acc-user').value);
  fd.append('acc_pass',document.getElementById('acc-pass').value);
  fd.append('acc_platform',document.getElementById('acc-platform').value||'Facebook');
  fd.append('acc_desc',document.getElementById('acc-desc').value);
  fetch('/admin/api/add-acc',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    showMsg('acc-msg',d.ok,d.ok?'✅ Đã thêm '+d.added+' acc!':'❌ Lỗi!');
    if(d.ok){document.getElementById('acc-bulk').value='';document.getElementById('acc-user').value='';document.getElementById('acc-pass').value='';}
  }).catch(()=>showMsg('acc-msg',false,'❌ Lỗi kết nối!'));
}
function delAcc(cat,id){
  if(!confirm('Xóa acc này?'))return;
  const fd=new FormData();fd.append('cat',cat);fd.append('id',id);
  fetch('/admin/api/del-acc',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    if(d.ok){alert('Đã xóa!');location.reload();}
    else alert('Lỗi xóa acc!');
  });
}
function delUser(uid){
  if(!confirm('Xóa user này?'))return;
  const fd=new FormData();fd.append('uid',uid);
  fetch('/admin/api/del-user',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    if(d.ok){alert('Đã xóa!');location.reload();}
    else alert('Lỗi!');
  });
}
function doBalance(action){
  const user=document.getElementById('bal-user').value;
  const amount=document.getElementById('bal-amount').value;
  if(!user||!amount){showMsg('bal-msg',false,'Nhập đủ thông tin!');return;}
  const fd=new FormData();fd.append('user',user);fd.append('action',action);fd.append('amount',amount);
  fetch('/admin/api/balance',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    showMsg('bal-msg',d.ok,d.ok?`✅ ${action==='add'?'Cộng':'Trừ'} ${Number(amount).toLocaleString('vi-VN')}đ cho ${d.username}. Số dư: ${(d.new_balance||0).toLocaleString('vi-VN')}đ`:d.msg||'❌ Lỗi!');
  }).catch(()=>showMsg('bal-msg',false,'❌ Lỗi kết nối!'));
}
function approveTopup(content,amount){
  if(!confirm(`Duyệt ${typeof amount==='number'?amount.toLocaleString('vi-VN'):amount}đ?`))return;
  const fd=new FormData();fd.append('content',content);fd.append('amount',amount);
  fetch('/admin/api/approve-topup',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    alert(d.ok?'✅ Đã duyệt!':'❌ Lỗi!');if(d.ok)location.reload();
  });
}
function rejectTopup(content){
  if(!confirm('Từ chối yêu cầu này?'))return;
  const fd=new FormData();fd.append('content',content);
  fetch('/admin/api/reject-topup',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    alert(d.ok?'✅ Đã từ chối!':'❌ Lỗi!');if(d.ok)location.reload();
  });
}
function manualApprove(){
  const content=document.getElementById('tp-content').value.trim();
  const amount=parseInt(document.getElementById('tp-amount').value);
  if(!content||!amount){showMsg('tp-msg',false,'Nhập đủ mã và số tiền!');return;}
  const fd=new FormData();fd.append('content',content);fd.append('amount',amount);
  fetch('/admin/api/approve-topup',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    showMsg('tp-msg',d.ok,'✅ Đã duyệt thành công!');
  }).catch(()=>showMsg('tp-msg',false,'❌ Lỗi kết nối!'));
}
function setNotice(){
  const fd=new FormData();
  fd.append('notice',document.getElementById('notice-txt').value);
  fd.append('btn_desc',(document.getElementById('notice-btn-desc')||{}).value||'');
  fd.append('tg_link',(document.getElementById('notice-tg-link')||{}).value||'');
  fd.append('zalo_link',(document.getElementById('notice-zalo-link')||{}).value||'');
  fetch('/admin/api/notice',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    showMsg('notice-msg',d.ok,d.ok?'✅ Đã cập nhật thông báo!':'❌ Lỗi!');
  });
}
function clearNotice(){
  const fd=new FormData();
  fd.append('notice','');fd.append('btn_desc','');fd.append('tg_link','');fd.append('zalo_link','');
  fetch('/admin/api/notice',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    showMsg('notice-msg',d.ok,d.ok?'✅ Đã xóa thông báo!':'❌ Lỗi!');
    if(d.ok){
      ['notice-txt','notice-btn-desc','notice-tg-link','notice-zalo-link'].forEach(id=>{const el=document.getElementById(id);if(el)el.value='';});
    }
  });
}
function approveCarry(orderId,username){
  if(!confirm('Đánh dấu đơn kéo thuê của '+username+' là đã hoàn thành?'))return;
  const fd=new FormData();fd.append('order_id',orderId);
  fetch('/admin/api/approve-carry',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    alert(d.ok?'✅ Đã duyệt! User sẽ nhận thông báo.':'❌ '+(d.msg||'Lỗi!'));
    if(d.ok)location.reload();
  }).catch(()=>alert('❌ Lỗi kết nối!'));
}
function sendMsg(){
  const user=document.getElementById('msg-user').value;
  const msg=document.getElementById('msg-txt').value;
  if(!user||!msg){showMsg('msg-res',false,'Nhập đủ thông tin!');return;}
  const fd=new FormData();fd.append('user',user);fd.append('msg',msg);
  fetch('/admin/api/send-msg',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    showMsg('msg-res',d.ok,d.ok?'✅ Đã gửi thông báo!':d.msg||'❌ Lỗi!');
  }).catch(()=>showMsg('msg-res',false,'❌ Lỗi kết nối!'));
}
let _allLogs=[];
function loadLogs(page){
  fetch('/admin/api/logs?page='+(page||1)).then(r=>r.json()).then(d=>{
    if(!d.ok)return;
    _allLogs=d.logs;
    renderLogs(_allLogs);
    const pg=document.getElementById('log-pages');if(!pg)return;
    pg.innerHTML='';
    for(let i=1;i<=d.pages;i++){
      const b=document.createElement('button');b.className='btn btn-sm '+(i===page?'btn-p':'btn-o');
      b.textContent=i;b.onclick=(()=>{const pp=i;return()=>loadLogs(pp);})();
      pg.appendChild(b);
    }
  });
}
function renderLogs(logs){
  const con=document.getElementById('log-container');if(!con)return;
  if(!logs||!logs.length){con.innerHTML='<div style="color:var(--muted);font-size:.82rem;padding:.5rem;">Không có nhật ký</div>';return;}
  con.innerHTML=logs.map(l=>`<div class="log-row"><span class="log-time">${l.time}</span><span class="log-event">${l.event}</span><span class="log-detail">${l.detail}${l.user&&l.user!=='system'?` <span style="color:var(--muted);font-size:.72rem;">(${l.user})</span>`:''}</span></div>`).join('');
}
function filterLogs(){
  const q=document.getElementById('log-search').value.toLowerCase();
  if(!q){renderLogs(_allLogs);return;}
  renderLogs(_allLogs.filter(l=>(l.event+l.detail+l.user).toLowerCase().includes(q)));
}
function addCustomAcc(){
  const fd=new FormData();
  const fileInput=document.getElementById('ca-file');
  if(fileInput&&fileInput.files.length)fd.append('image_file',fileInput.files[0]);
  fd.append('image_url',(document.getElementById('ca-img-url')||{}).value||'');
  fd.append('acc_user',(document.getElementById('ca-user')||{}).value||'');
  fd.append('acc_pass',(document.getElementById('ca-pass')||{}).value||'');
  fd.append('platform',(document.getElementById('ca-platform')||{}).value||'Facebook');
  fd.append('desc',(document.getElementById('ca-desc')||{}).value||'');
  fd.append('price',(document.getElementById('ca-price')||{}).value||'0');
  const btn=document.querySelector('#pn-customacc .btn-p');
  if(btn){btn.textContent='⏳ Đang thêm...';btn.disabled=true;}
  fetch('/admin/api/add-custom-acc',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    if(btn){btn.textContent='➕ Thêm Acc Tự Chọn';btn.disabled=false;}
    showMsg('ca-msg',d.ok,d.ok?'✅ Đã thêm acc!':d.msg||'❌ Lỗi!');
    if(d.ok){
      if(fileInput)fileInput.value='';
      ['ca-img-url','ca-user','ca-pass','ca-desc','ca-price'].forEach(id=>{const el=document.getElementById(id);if(el)el.value='';});
      const pl=document.getElementById('ca-platform');if(pl)pl.value='Facebook';
      setTimeout(()=>location.reload(),1200);
    }
  }).catch(()=>{if(btn){btn.textContent='➕ Thêm Acc Tự Chọn';btn.disabled=false;}showMsg('ca-msg',false,'❌ Lỗi kết nối!');});
}
function delCustomAcc(id){
  if(!confirm('Xóa acc tự chọn này?'))return;
  const fd=new FormData();fd.append('id',id);
  fetch('/admin/api/del-custom-acc',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    if(d.ok){alert('✅ Đã xóa!');location.reload();}
    else alert('❌ Lỗi xóa!');
  });
}
document.addEventListener('DOMContentLoaded',function(){
  const durSel=document.getElementById('dc-duration');
  if(durSel)durSel.addEventListener('change',function(){
    const row=document.getElementById('dc-custom-hours-row');
    if(row)row.style.display=this.value==='custom'?'block':'none';
  });
});
function addDiscountCode(){
  const code=(document.getElementById('dc-code').value||'').trim().toUpperCase();
  const pct=document.getElementById('dc-pct').value;
  const duration=document.getElementById('dc-duration').value;
  const customH=(document.getElementById('dc-custom-hours')||{}).value||0;
  if(!pct||parseInt(pct)<1||parseInt(pct)>100){showMsg('dc-msg',false,'Nhập % giảm hợp lệ (1-100)!');return;}
  const fd=new FormData();
  if(code)fd.append('code',code);
  fd.append('discount_pct',pct);fd.append('duration',duration);
  if(duration==='custom')fd.append('custom_hours',customH);
  fetch('/admin/api/add-discount-code',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    if(d.ok){
      showMsg('dc-msg',true,'✅ Tạo mã thành công: '+d.code);
      document.getElementById('dc-code').value='';document.getElementById('dc-pct').value='';
      setTimeout(()=>location.reload(),1500);
    } else {showMsg('dc-msg',false,'❌ '+(d.msg||'Lỗi!'));}
  }).catch(()=>showMsg('dc-msg',false,'❌ Lỗi kết nối!'));
}
function delDiscountCode(code){
  if(!confirm('Xóa mã '+code+'?'))return;
  const fd=new FormData();fd.append('code',code);
  fetch('/admin/api/del-discount-code',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    if(d.ok){alert('✅ Đã xóa mã '+code);location.reload();}
    else alert('❌ Lỗi xóa mã!');
  });
}
function addFeedback(){
  const fileInput=document.getElementById('fb-file');
  const url=document.getElementById('fb-url').value.trim();
  const desc=document.getElementById('fb-desc').value.trim();
  const customer=document.getElementById('fb-customer').value.trim();
  if(!fileInput.files.length&&!url&&!desc){showMsg('fb-msg',false,'Cần nhập mô tả hoặc chọn ảnh/video!');return;}
  const fd=new FormData();
  if(fileInput.files.length)fd.append('media_file',fileInput.files[0]);
  fd.append('media_url',url);
  fd.append('desc',desc);
  fd.append('customer',customer);
  const btn=document.querySelector('#pn-feedback .btn-p');
  if(btn){btn.textContent='⏳ Đang tải...';btn.disabled=true;}
  fetch('/admin/api/add-feedback',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    if(btn){btn.textContent='📤 Đăng Feedback';btn.disabled=false;}
    showMsg('fb-msg',d.ok,d.ok?'✅ Đã đăng feedback!':d.msg||'❌ Lỗi!');
    if(d.ok){fileInput.value='';document.getElementById('fb-url').value='';document.getElementById('fb-desc').value='';document.getElementById('fb-customer').value='';setTimeout(()=>location.reload(),1200);}
  }).catch(()=>{if(btn){btn.textContent='📤 Đăng Feedback';btn.disabled=false;}showMsg('fb-msg',false,'❌ Lỗi kết nối!');});
}
function delFeedback(id){
  if(!confirm('Xóa feedback này?'))return;
  const fd=new FormData();fd.append('id',id);
  fetch('/admin/api/del-feedback',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    if(d.ok){alert('✅ Đã xóa!');location.reload();}
    else alert('❌ Lỗi!');
  });
}
</script>
</body></html>"""

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
