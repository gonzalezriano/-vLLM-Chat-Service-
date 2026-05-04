# DA 410/510 — Two-Instance vLLM Chat Service with User Login

## Overview

This project deploys a small LLM-backed chat application on AWS using two separate EC2 instances. The first instance runs vLLM as a private model server. The second instance runs a FastAPI web application behind nginx that handles user registration, login, session management, and chat history. Users must create an account and log in before they can send prompts to the model.

The model used is `HuggingFaceTB/SmolLM2-135M-Instruct`, served through vLLM's OpenAI-compatible HTTP server on a CPU-only free-tier EC2 instance.

---

## Architecture

```
Internet
    │
    ▼
[nginx : port 80]  ← only public entry point
    │
    ▼
[FastAPI : 127.0.0.1:8000]  ← not exposed publicly
    │
    ▼ (VPC private network)
[vLLM : port 8000]  ← only reachable from web-app security group
```

- **Web-app instance** (`web-sg-app`): runs nginx + FastAPI + SQLite. Public HTTP on port 80 only.
- **Model server instance** (`model-sg-server`): runs vLLM via Docker. Port 8000 open only to the web-app security group. Not reachable from the public internet.

---

## Security Boundary

The vLLM server is intentionally kept off the public internet. The AWS security group on the model server only allows inbound traffic on port 8000 from the web-app instance's security group. No public IP or DNS name can reach vLLM directly.

The FastAPI application is the only component that calls vLLM. It reads the vLLM base URL and API key from environment variables, never from user input or browser-side code. The browser never receives the vLLM API key.

nginx sits in front of FastAPI and is the only process listening on the public port 80. FastAPI binds to `127.0.0.1:8000` and is not directly reachable from outside the instance.

Passwords are never stored in plaintext. The application uses bcrypt via passlib to hash passwords before storing them. Login failures return a generic error message that does not reveal whether the email address exists.

Sessions use a cryptographically random token. Only a SHA-256 hash of the token is stored in the database. The raw token is sent to the browser as an HttpOnly, SameSite=Lax cookie. Every protected route checks the session before returning any data. Chat history is always filtered by the authenticated user's ID derived from the session — never from a user-supplied value.

---

## Stack

| Component | Technology |
|---|---|
| Web framework | FastAPI (Python) |
| Templates | Jinja2 |
| Database | SQLite |
| Password hashing | passlib + bcrypt |
| Reverse proxy | nginx |
| Model server | vLLM (Docker, CPU) |
| Model | HuggingFaceTB/SmolLM2-135M-Instruct |
| Model client | OpenAI Python SDK (custom base_url) |
| Cloud | AWS EC2 (us-east-2) |

---

## Project Structure

```
da510-vllm-chat-service/
├── README.md
├── .gitignore
├── webapp/
│   ├── main.py           # FastAPI routes
│   ├── auth.py           # Session and password logic
│   ├── db.py             # Database setup and user creation
│   ├── chat.py           # Chat message storage
│   └── templates/
│       ├── base.html
│       ├── register.html
│       ├── login.html
│       └── chat.html
├── nginx/
│   └── webapp.conf       # nginx reverse proxy config
└── screenshots/          # All submission evidence
```

---

## Deployment Steps

### Part 1 — EC2 Instances

- Launch two EC2 instances in the same VPC (Ubuntu 22.04 LTS)
- Model server: configure security group to allow port 8000 only from the web-app security group
- Web-app server: configure security group to allow port 80 (public) and port 22 (SSH only)

### Part 2 — vLLM on Model Server

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

### Part 3 — Web App on Web-App Instance

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv nginx
mkdir ~/webapp && cd ~/webapp
python3 -m venv env
source env/bin/activate
pip install fastapi uvicorn jinja2 "passlib[bcrypt]" bcrypt==4.0.1 openai python-multipart
```

Create a `.env` file (not committed to version control):
```
VLLM_BASE_URL=http://<MODEL_SERVER_PRIVATE_IP>:8000/v1
VLLM_API_KEY=secret123
```

### Part 4 — nginx Configuration

```bash
sudo nano /etc/nginx/sites-available/webapp
sudo ln -s /etc/nginx/sites-available/webapp /etc/nginx/sites-enabled/webapp
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
```

### Part 5 — Run the App

```bash
tmux new -s webapp
cd ~/webapp
source env/bin/activate
export $(cat .env | xargs)
uvicorn main:app --host 127.0.0.1 --port 8000
```

---

## Environment Variables

| Variable | Description |
|---|---|
| `VLLM_BASE_URL` | Private URL of the vLLM server, e.g. `http://10.0.9.164:8000/v1` |
| `VLLM_API_KEY` | API key configured on the vLLM server |

These must be set in a `.env` file on the web-app instance. The `.env` file is excluded from version control via `.gitignore`.

---

## Security Notes

- vLLM port 8000 is not open to the public internet
- FastAPI does not listen on a public port — nginx proxies all traffic
- Passwords are stored as bcrypt hashes, never plaintext
- Session tokens are random 32-byte URL-safe strings; only their SHA-256 hash is stored
- Login errors are generic and do not reveal whether an email exists
- Chat history is enforced server-side by session — users cannot access each other's messages
- API keys and secrets are loaded from environment variables, not hardcoded
