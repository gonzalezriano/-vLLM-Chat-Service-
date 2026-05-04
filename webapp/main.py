import os
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from auth import create_session, get_user_from_session, verify_user, revoke_session
from chat import get_chat_history, save_message
from db import create_user, init_db

app = FastAPI()
templates = Jinja2Templates(directory="templates")
init_db()


@app.get("/register", response_class=HTMLResponse)
async def register_get(request: Request):
    return templates.TemplateResponse(request, "register.html", {"error": ""})


@app.post("/register", response_class=HTMLResponse)
async def register_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    email = email.strip().lower()
    if not email or not password:
        return templates.TemplateResponse(
            request, "register.html", {"error": "Email and password are required."}
        )
    if password != confirm_password:
        return templates.TemplateResponse(
            request, "register.html", {"error": "Passwords do not match."}
        )
    success = create_user(email, password)
    if not success:
        return templates.TemplateResponse(
            request, "register.html", {"error": "An account with that email already exists."}
        )
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": ""})


@app.post("/login", response_class=HTMLResponse)
async def login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    email = email.strip().lower()
    user = verify_user(email, password)
    if user is None:
        return templates.TemplateResponse(
            request, "login.html", {"error": "Invalid email or password."}
        )
    session_token = create_session(user["id"])
    response = RedirectResponse("/chat", status_code=303)
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@app.post("/logout")
async def logout(request: Request):
    session_token = request.cookies.get("session_token")
    if session_token:
        revoke_session(session_token)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("session_token", path="/")
    return response


@app.get("/chat", response_class=HTMLResponse)
async def chat_get(request: Request):
    session_token = request.cookies.get("session_token")
    if not session_token:
        return RedirectResponse("/login", status_code=303)
    user = get_user_from_session(session_token)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    history = get_chat_history(user["id"])
    return templates.TemplateResponse(
        request, "chat.html", {"user": user, "history": history}
    )


@app.post("/chat", response_class=HTMLResponse)
async def chat_post(request: Request, prompt: str = Form(...)):
    session_token = request.cookies.get("session_token")
    if not session_token:
        return RedirectResponse("/login", status_code=303)
    user = get_user_from_session(session_token)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    save_message(user["id"], "user", prompt)
    from openai import OpenAI
    client = OpenAI(
        base_url=os.environ["VLLM_BASE_URL"],
        api_key=os.environ["VLLM_API_KEY"],
    )
    history = get_chat_history(user["id"])
    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    try:
        response = client.chat.completions.create(
            model="HuggingFaceTB/SmolLM2-135M-Instruct",
            messages=messages,
            max_tokens=200,
        )
        assistant_reply = response.choices[0].message.content
    except Exception as e:
        assistant_reply = f"[Model error: {e}]"
    save_message(user["id"], "assistant", assistant_reply)
    history = get_chat_history(user["id"])
    return templates.TemplateResponse(
        request, "chat.html", {"user": user, "history": history}
    )


@app.get("/")
async def root():
    return RedirectResponse("/login", status_code=303)
