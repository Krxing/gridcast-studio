import os
import secrets
import time
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, Response

from backend import store

secret_path = store.DATA / '.jwt-secret'
if not secret_path.exists():
    try:
        with secret_path.open('x', encoding='utf-8') as handle:
            handle.write(secrets.token_hex(48))
        secret_path.chmod(0o600)
    except FileExistsError:
        pass
SECRET = secret_path.read_text(encoding='utf-8')
ATTEMPTS = {}


def password_hash(password):
    if len(password) < 8 or len(password.encode('utf-8')) > 72:
        raise HTTPException(422, '密码至少 8 个字符，且 UTF-8 编码不超过 72 字节')
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('ascii')


def session(response: Response, user):
    token = jwt.encode({'sub': user['id'], 'exp': datetime.now(UTC) + timedelta(hours=8)}, SECRET, algorithm='HS256')
    response.set_cookie('gridcast_session', token, max_age=28800, httponly=True, samesite='strict',
                        secure=os.environ.get('APP_COOKIE_SECURE', 'false').lower() == 'true')


def login(request, response, username, password):
    address = request.client.host if request.client else 'unknown'
    attempts = [stamp for stamp in ATTEMPTS.get(address, []) if time.time() - stamp < 60]
    if len(attempts) >= 8:
        raise HTTPException(429, '尝试过于频繁，请一分钟后再试')
    user = store.one('SELECT * FROM users WHERE username=?', (username,))
    valid = user and len(password.encode()) <= 72 and bcrypt.checkpw(password.encode(), user['password'].encode())
    if not valid:
        ATTEMPTS[address] = attempts + [time.time()]
        raise HTTPException(401, '用户名或密码不正确')
    ATTEMPTS.pop(address, None)
    session(response, user)
    return public_user(user)


def current_user(request: Request):
    token = request.cookies.get('gridcast_session')
    if not token:
        raise HTTPException(401, '请先登录')
    try:
        payload = jwt.decode(token, SECRET, algorithms=['HS256'])
        user = store.one('SELECT * FROM users WHERE id=?', (payload['sub'],))
        if not user:
            raise ValueError('用户不存在')
        return public_user(user)
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(401, '登录已过期，请重新登录') from None


def public_user(user):
    return {key: user[key] for key in ['id', 'username', 'role', 'created_at']}


def engineer(user=Depends(current_user)):
    if user['role'] not in ['admin', 'engineer']:
        raise HTTPException(403, '需要算法工程师或管理员权限')
    return user


def administrator(user=Depends(current_user)):
    if user['role'] != 'admin':
        raise HTTPException(403, '需要管理员权限')
    return user
