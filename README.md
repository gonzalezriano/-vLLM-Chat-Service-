## Two-Instance vLLM Chat Service

This was my final deployment project for DA 510 Cloud Computing. The goal was to deploy a working LLM-backed chat app on AWS — not just get a model running, but build the full thing: two separate EC2 instances, user accounts, login, sessions, chat history, and a proper security boundary between the public app and the model server.

The model specified for the assignment is `HuggingFaceTB/SmolLM2-135M-Instruct`, served through vLLM's OpenAI-compatible HTTP server on a CPU-only free-tier EC2 instance. The focus of the assignment is the architecture and security design rather than inference performance.

---

## What this does

- Users can register with an email and password
- Passwords are hashed with bcrypt — never stored in plaintext
- After login, a session cookie is created and checked on every protected route
- The chat page is only accessible to logged-in users
- Each user only sees their own chat history
- The model server (vLLM) is completely private — only the web app can reach it over the VPC internal network
- nginx is the only thing exposed to the public internet

---

## Architecture

```
Internet
    │
    ▼
[nginx : port 80]          ← only public entry point
    │
    ▼
[FastAPI : 127.0.0.1:8000] ← not directly reachable from outside
    │
    ▼  (VPC private network)
[vLLM : port 8000]         ← locked to web-app security group only
```

Two EC2 instances, both in the same VPC:

- **Web-app instance** — runs nginx + FastAPI + SQLite. Only ports 22 and 80 are open publicly. The web app uses the OpenAI Python SDK pointed at the private vLLM server instead of the real OpenAI API, with passlib/bcrypt handling password hashing and a SQLite database storing users, sessions, and chat messages.
- **Model server instance** — runs vLLM in Docker. Port 8000 is only open to the web-app security group. No public access.

---

## The hardest parts

Getting vLLM to actually run on a CPU-only instance was genuinely painful. The latest Docker image crashed on startup with an engine core initialization error. An older version had a different bug where the chat completions endpoint threw an XFormers error. The fix that finally worked was using the CPU-specific image with `--enforce-eager`, `--gpu-memory-utilization 0.7`, and `--max-model-len 2048` to stay within the memory limits of a free-tier instance.

The security group configuration also caused problems. The rule for port 8000 was added to the right security group, but the model server instance was actually attached to a different security group (`launch-wizard-1`, the default one AWS creates) — so the rule never applied. Once I found that mismatch everything clicked.

On the app side, the Jinja2 `TemplateResponse` call format changed in newer versions of Starlette, and there was a bcrypt backend compatibility issue with passlib that caused internal server errors on registration. Both needed small fixes but took a while to track down from the stack traces.

---

## Project structure

```
da510-vllm-chat-service/
├── README.md
├── webapp/
│   ├── main.py
│   ├── auth.py
│   ├── db.py
│   ├── chat.py
│   └── templates/
│       ├── base.html
│       ├── register.html
│       ├── login.html
│       └── chat.html
└── evidence/
```

---

## How to run it

### Model server (EC2 instance 1)

```bash
sudo apt update
sudo apt install -y docker.io tmux
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
newgrp docker

tmux new -s vllm
docker run \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  -p 8000:8000 \
  -e VLLM_API_KEY=secret123 \
  vllm/vllm-openai-cpu:latest-x86_64 \
  --model HuggingFaceTB/SmolLM2-135M-Instruct \
  --dtype float32 \
  --api-key secret123 \
  --enforce-eager \
  --gpu-memory-utilization 0.7 \
  --max-model-len 2048
```

Wait for `Application startup complete` before testing. The first run takes a while — it pulls the image and downloads the model.

### Web app (EC2 instance 2)

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv nginx
mkdir ~/webapp && cd ~/webapp
python3 -m venv env
source env/bin/activate
pip install fastapi uvicorn jinja2 "passlib[bcrypt]" bcrypt==4.0.1 openai python-multipart
```

Create a `.env` file (do not commit this):
```
VLLM_BASE_URL=http://<MODEL_SERVER_PRIVATE_IP>:8000/v1
VLLM_API_KEY=secret123
```

Start the app in tmux:
```bash
tmux new -s webapp
cd ~/webapp
source env/bin/activate
export $(cat .env | xargs)
uvicorn main:app --host 127.0.0.1 --port 8000
```

### nginx

```bash
sudo nano /etc/nginx/sites-available/webapp
```

Paste this config:
```
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 120;
    }
}
```

Then:
```bash
sudo ln -s /etc/nginx/sites-available/webapp /etc/nginx/sites-enabled/webapp
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
```

---

## Security notes

- vLLM is not reachable from the public internet — the security group only allows port 8000 from the web-app instance
- FastAPI binds to `127.0.0.1` and is proxied through nginx on port 80
- Passwords are stored as bcrypt hashes
- Session tokens are 32-byte random strings; only their SHA-256 hash is stored in the database
- Login errors are intentionally generic — the app does not reveal whether an email address exists
- The vLLM API key is read from an environment variable and never sent to the browser
- Chat history is always filtered by the user ID from the session, never from user input
