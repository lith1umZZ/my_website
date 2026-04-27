from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import re
from datetime import datetime, timezone, timedelta
import hashlib


app = Flask(__name__)
app.secret_key = 'your-secret-key-12345'

basedir = os.path.abspath(os.path.dirname(__file__))
MUSIC_DIR = os.path.join(basedir, 'static', 'music')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'site.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB
ALLOWED_EXTENSIONS = {'mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a'}

os.makedirs(MUSIC_DIR, exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = '请先登录！'

# ===== Jinja2 自定义过滤器 =====
def time_ago(dt):
    if not dt:
        return ''
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = now - dt
    seconds = int(diff.total_seconds())
    if seconds < 60: return '刚刚'
    if seconds < 3600: return f'{seconds // 60} 分钟前'
    if seconds < 86400: return f'{seconds // 3600} 小时前'
    if seconds < 2592000: return f'{seconds // 86400} 天前'
    if seconds < 31536000: return f'{seconds // 2592000} 个月前'
    return f'{seconds // 31536000} 年前'

def str_hash(s):
    return int(hashlib.md5(s.encode()).hexdigest()[:8], 16)

app.jinja_env.filters['time_ago'] = time_ago
app.jinja_env.filters['hash'] = str_hash


# ===== 生成头像颜色 =====
def avatar_color(name):
    h = hashlib.md5(name.encode()).hexdigest()
    hue = int(h[:6], 16) % 360
    return f'hsl({hue}, 50%, 55%)'

# ===== 管理员装饰器 =====
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.username != 'admin':
            flash('仅管理员可执行此操作！', 'error')
            return redirect(url_for('guestbook'))
        return f(*args, **kwargs)
    return decorated

# ===== 用户模型 =====
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# ===== 留言模型 =====
class Guestbook(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    content = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

# ===== 音乐模型 =====
class Music(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    file_name = db.Column(db.String(100), nullable=False)

# ===== 登录管理器 =====
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# ===== 初始化数据库 =====
with app.app_context():
    db.create_all()

    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print(">>> 默认管理员账号已创建（admin / admin123）")

    # 如果数据库为空，添加默认歌曲（仅首次运行）
    if Music.query.count() == 0:
        songs_to_add = [
            {"title": "secret", "file_name": "track1.mp3"},
            {"title": "壱雫空", "file_name": "track2.mp3"},
            {"title": "春日影", "file_name": "【Official Music Video】春日影(MyGO!!!!! ver.) MyGO!!!!!【原创歌曲】.mp3"},
            {"title": "迷星叫", "file_name": "【Hi·Res4k60】迷星叫 （Mayoiuta）Mygo!!!!! 网易云超清母带版.mp3"},
        ]
        for song in songs_to_add:
            db.session.add(Music(title=song["title"], file_name=song["file_name"]))
        db.session.commit()
        print(f">>> 首次初始化：已添加 {len(songs_to_add)} 首默认歌曲")

# ===== 路由：首页 =====
@app.route('/')
def index():
    all_musics = Music.query.all()
    all_messages = Guestbook.query.all()
    return render_template('index.html', musics=all_musics, messages=all_messages)

# ===== 路由：留言板 =====
@app.route('/guestbook', methods=['GET', 'POST'])
def guestbook():
    if request.method == 'POST':
        user_name = request.form.get('name')
        user_msg = request.form.get('content')
        new_msg = Guestbook(name=user_name, content=user_msg)
        db.session.add(new_msg)
        db.session.commit()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return guestbook_messages_html()
        return redirect('/guestbook')

    messages = Guestbook.query.all()
    if request.args.get('ajax') == '1':
        return guestbook_messages_html()
    return render_template('guestbook.html', messages=messages)

def guestbook_messages_html():
    """生成留言列表的 HTML 片段"""
    messages = Guestbook.query.all()
    html = ''
    for i, msg in enumerate(reversed(messages)):
        idx = len(messages) - i
        color = avatar_color(msg.name)
        initial = msg.name[0].upper() if msg.name else '?'
        time_str = time_ago(msg.created_at)
        html += f'''<div class="msg-card" data-msg-id="{msg.id}">
            <div class="msg-avatar" style="background:{color}">{initial}</div>
            <div class="msg-content">
                <div class="msg-header">
                    <strong>{msg.name}</strong>
                    <span class="msg-time">#{idx} · {time_str}</span>
                </div>
                <div class="msg-body">{msg.content}</div>
            </div>'''
        if current_user.is_authenticated:
            html += f'''<form class="delete-form" method="POST" action="/delete/{msg.id}" onsubmit="return deleteMessage(event, this, {msg.id})">
                <button type="submit" class="btn btn-danger">🗑️</button>
            </form>'''
        html += '</div>'
    return html

# ===== 路由：删除留言 =====
@app.route('/delete/<int:msg_id>', methods=['POST'])
@login_required
def delete_message(msg_id):
    msg = db.session.get(Guestbook, msg_id)
    if msg:
        db.session.delete(msg)
        db.session.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return '', 200
    return redirect('/guestbook')

# ===== 路由：主题切换 =====
@app.route('/api/theme', methods=['POST'])
def set_theme():
    data = request.get_json()
    theme = data.get('theme', 'dark')
    return jsonify({'theme': theme})

# ===== 路由：登录 =====
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect('/guestbook')

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            flash('登录成功！', 'success')
            return redirect('/guestbook')
        else:
            flash('用户名或密码错误！', 'error')

    return render_template('login.html')

# ===== 路由：注册 =====
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect('/guestbook')

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirm = request.form.get('confirm')

        if not username or not password:
            flash('用户名和密码不能为空！', 'error')
        elif password != confirm:
            flash('两次密码输入不一致！', 'error')
        elif User.query.filter_by(username=username).first():
            flash('用户名已存在！', 'error')
        else:
            user = User(username=username)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash('注册成功，请登录！', 'success')
            return redirect('/login')

    return render_template('register.html')

# ===== 路由：退出登录 =====
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('已退出登录！', 'info')
    return redirect('/guestbook')

# ===== 路由：音乐管理页面 =====
@app.route('/music-manage')
@login_required
@admin_required
def music_manage():
    all_musics = Music.query.all()
    return render_template('music_manage.html', musics=all_musics)

# ===== 路由：添加音乐（管理员） =====
@app.route('/api/music/add', methods=['POST'])
@login_required
@admin_required
def add_music():
    title = request.form.get('title', '').strip()
    file = request.files.get('file')

    if not title:
        return jsonify({'success': False, 'error': '请输入歌曲名称'}), 400
    if not file or file.filename == '':
        return jsonify({'success': False, 'error': '请选择音频文件'}), 400

    # 安全处理文件名
    orig_name = secure_filename(file.filename)
    ext = orig_name.rsplit('.', 1)[-1].lower() if '.' in orig_name else ''
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({'success': False, 'error': f'不支持的格式：{ext}，仅支持 {", ".join(ALLOWED_EXTENSIONS)}'}), 400

    # 检查重名
    exists = Music.query.filter_by(file_name=orig_name).first()
    if exists:
        return jsonify({'success': False, 'error': f'文件 "{orig_name}" 已存在'}), 400

    # 保存文件
    file_path = os.path.join(MUSIC_DIR, orig_name)
    file.save(file_path)

    # 写入数据库
    new_music = Music(title=title, file_name=orig_name)
    db.session.add(new_music)
    db.session.commit()

    return jsonify({
        'success': True,
        'music': {
            'id': new_music.id,
            'title': new_music.title,
            'file_name': new_music.file_name,
            'url': url_for('static', filename='music/' + new_music.file_name)
        }
    })

# ===== 路由：删除音乐（管理员） =====
@app.route('/api/music/delete/<int:music_id>', methods=['POST'])
@login_required
@admin_required
def delete_music(music_id):
    music = db.session.get(Music, music_id)
    if not music:
        return jsonify({'success': False, 'error': '音乐不存在'}), 404

    # 删除文件
    file_path = os.path.join(MUSIC_DIR, music.file_name)
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        pass  # 文件删除失败不阻拦数据库删除

    # 删除数据库记录
    db.session.delete(music)
    db.session.commit()

    return jsonify({'success': True, 'music_id': music_id})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('DEBUG', '0') == '1')
