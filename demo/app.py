import os
import openai
import bcrypt
from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from dotenv import load_dotenv
from math import ceil

# =========================
# 1. 加载环境 & 基本配置
# =========================

load_dotenv()

app = Flask(__name__)

# 生成随机密钥并设置为 SECRET_KEY
app.config['SECRET_KEY'] = os.urandom(24)

# 从环境变量中读取你的 GPT Key
openai.api_key = os.getenv("OPENAI_API_KEY")

# 配置数据库，这里以 SQLite 为例
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///demo.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)



# =========================
# 2. 数据库模型
# =========================

class User(db.Model):
    """用户表"""
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(60), nullable=False)  # 存储哈希后的密码
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # def __init__(self, username, password_hash):
    #     self.username = username
    #     self.password_hash = password_hash

class ChatRecord(db.Model):
    """聊天记录表"""
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, nullable=False)
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# =========================
# 3. 路由逻辑
# =========================

@app.route('/')
def index():
    """
    首页
    """
    if session.get("logged_in"):
        return render_template("index.html", logged_in=True, username=session.get("username"))
    else:
        return render_template("index.html", logged_in=False)

@app.route('/register', methods=['GET', 'POST'])
def register():
    """
    用户注册
    """
    if request.method == 'GET':
        return render_template("register.html")

    # POST 提交表单数据
    username = request.form.get('username')
    password = request.form.get('password')

    if not username or not password:
        return "用户名或密码不能为空", 400

    existing_user = User.query.filter_by(username=username).first()
    if existing_user:
        return "该用户名已被注册", 400

    # 加密并写入数据库
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    new_user = User(username=username, password_hash=hashed.decode('utf-8'))
    db.session.add(new_user)
    db.session.commit()

    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    用户登录
    """
    if request.method == 'GET':
        if session.get("logged_in"):
            return redirect(url_for("index"))
        return render_template("login.html")

    username = request.form.get('username')
    password = request.form.get('password')

    if not username or not password:
        return "用户名或密码不能为空", 400

    user = User.query.filter_by(username=username).first()
    if not user:
        return "用户名不存在", 400

    # 验证密码
    if bcrypt.checkpw(password.encode('utf-8'),  user.password_hash.encode('utf-8')):
        session["logged_in"] = True
        session["username"] = user.username
        session["user_id"] = user.id
        return redirect(url_for('index'))
    else:
        return "密码错误", 401

@app.route('/logout')
def logout():
    """
    用户登出
    """
    session.clear()
    return redirect(url_for('index'))

@app.route("/chat", methods=["POST"])
def chat():
    """
    聊天接口 (GPT 调用 + 保存聊天记录)
    """
    if not session.get("logged_in"):
        return jsonify({"error": "未登录，无法访问此接口"}), 401

    data = request.get_json()
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({"error": "message cannot be empty"}), 400

    try:
        # 调用 GPT 接口
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": user_message}]
        )
        reply = response.choices[0].message.content.strip()

        # 将聊天记录保存到数据库
        user_id = session["user_id"]  # 当前登录用户ID
        record = ChatRecord(
            user_id=user_id,
            question=user_message,
            answer=reply
        )
        db.session.add(record)
        db.session.commit()

        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/history", methods=["GET"])
def get_chat_history():
    """
    获取当前用户的聊天历史(分页)
    - 支持 ?page=1&size=10 (默认为 page=1, size=10)
    """
    if not session.get("logged_in"):
        return jsonify({"error": "未登录，无法访问此接口"}), 401

    page = request.args.get("page", 1, type=int)
    size = request.args.get("size", 10, type=int)
    user_id = session["user_id"]

    # 查出当前用户的所有聊天记录，按时间倒序
    query = ChatRecord.query.filter_by(user_id=user_id).order_by(ChatRecord.created_at.desc())

    # 分页处理
    total = query.count()
    records = query.offset((page - 1) * size).limit(size).all()

    # 格式化返回
    data = []
    for r in records:
        data.append({
            "id": r.id,
            "question": r.question,
            "answer": r.answer,
            "created_at": r.created_at.strftime('%Y-%m-%d %H:%M:%S')
        })

    # 也可返回更多分页信息，比如总页数
    total_pages = ceil(total / size)

    return jsonify({
        "records": data,
        "total": total,
        "total_pages": total_pages,
        "current_page": page,
        "page_size": size
    })


# =========================
# 4. 启动应用入口
# =========================

if __name__ == "__main__":
    # 在应用上下文中创建表
    with app.app_context():
        db.create_all()

    app.run(debug=True, port=5001)
