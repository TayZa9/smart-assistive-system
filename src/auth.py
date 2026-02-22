from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from authlib.integrations.starlette_client import OAuth
from sqlalchemy.orm import Session
from pydantic import BaseModel
import hashlib
import secrets
import config
from src.database import get_db, User

auth_router = APIRouter()
templates = Jinja2Templates(directory="src/templates")

def hash_password(password: str) -> str:
    salt = secrets.token_hex(8)
    pw_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000).hex()
    return f"{salt}${pw_hash}"

def verify_password(password: str, hashed: str) -> bool:
    if not hashed or '$' not in hashed: return False
    salt, pw_hash = hashed.split('$')
    expected_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000).hex()
    return expected_hash == pw_hash

class LoginRequest(BaseModel):
    email: str
    password: str

class SignupRequest(BaseModel):
    name: str
    email: str
    password: str

@auth_router.get('/login', response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get('user_id'):
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request})

@auth_router.get('/signup', response_class=HTMLResponse)
async def signup_page(request: Request):
    if request.session.get('user_id'):
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("signup.html", {"request": request})

@auth_router.post('/auth/signup')
async def signup(req: SignupRequest, request: Request, db: Session = Depends(get_db)):
    # Check if user exists
    user = db.query(User).filter(User.email == req.email).first()
    if user:
        raise HTTPException(status_code=400, detail="Email is already registered.")
        
    new_user = User(
        email=req.email,
        name=req.name,
        hashed_password=hash_password(req.password)
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # Auto loop login
    request.session['user_id'] = new_user.id
    return {"status": "success"}

@auth_router.post('/auth/login')
async def login_local(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
        
    if not user.hashed_password:
        raise HTTPException(status_code=401, detail="This account uses Google Sign-In. Please use the Google button.")
        
    if not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
        
    request.session['user_id'] = user.id
    return {"status": "success"}

oauth = OAuth()
oauth.register(
    name='google',
    client_id=config.GOOGLE_CLIENT_ID,
    client_secret=config.GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile'
    }
)

@auth_router.get('/auth/google')
async def login_google(request: Request):
    if not config.GOOGLE_CLIENT_ID or not config.GOOGLE_CLIENT_SECRET:
        return {"error": "Google Auth is not configured in .env"}
    redirect_uri = request.url_for('auth_callback')
    return await oauth.google.authorize_redirect(request, redirect_uri)

@auth_router.get('/auth/callback')
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    user_info = token.get('userinfo')
    if not user_info:
        raise HTTPException(status_code=400, detail="Could not fetch user info")
        
    email = user_info.get('email')
    name = user_info.get('name')
    google_id = user_info.get('sub')
    picture = user_info.get('picture')

    # Find or create user
    user = db.query(User).filter(User.google_id == google_id).first()
    if not user:
        user = User(
            google_id=google_id,
            email=email,
            name=name,
            avatar_url=picture
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    
    # Store user id in session
    request.session['user_id'] = user.id
    
    # Redirect back to frontend
    return RedirectResponse(url="/")

@auth_router.get('/auth/logout')
async def logout(request: Request):
    request.session.pop('user_id', None)
    return RedirectResponse(url="/")

@auth_router.get("/api/user/me")
async def get_current_user(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get('user_id')
    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")
        
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
        
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "avatar_url": user.avatar_url,
        "settings_json": user.settings_json
    }
