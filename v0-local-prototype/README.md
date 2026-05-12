# Warehouse Safety Expert Agent (Google ADK + FastAPI)

An AI-powered Safety Agent built with FastAPI, Vertex AI (Gemini 2.5 Flash), and the Google Agent Development Kit (ADK). The agent evaluates real-time robotics sensor data using a CRAWL/WALK/RUN operational framework to determine collision risks in warehouse environments.

> **NOTE:** Weigh whether or not you should just fire up a Cloud Shell and run CLI commands with everything "baked in" (pre-authenticated, zero setup) vs. setting this up yourself on a Cloudtop. Cloud Shell is faster for 5-minute tasks, but Cloudtop gives you a professional, persistent IDE, Docker power, and "Jetski" AI assistance. It is fun though, so give it a try and **feel the power**.

---

## 🏗️ 1. The Cloudtop Golden Workflow (Bootup)

Developing GenAI applications on Google Cloudtop requires managing multiple layers of identity. If you ever run into authentication or Airlock issues, run through this bootup sequence:

| Step | Location | Command | Purpose |
| :--- | :--- | :--- | :--- |
| **1** | Local Laptop | `gcert` | Authenticate your physical SKMS/gnubby security key. |
| **2** | Local Laptop | `code .` | Open VS Code. This inherits the live LOAS cert into the session. |
| **3** | Cloudtop VS Code | `gcert` | Ensure the remote machine sees your forwarded agent. |
| **4** | Cloudtop VS Code | `gcloud auth login ... --update-adc` | Set Cloud identity (ADC) for Vertex AI (see exact command below). |
| **5** | Cloudtop VS Code | `glogin` | Refresh OAuth2 tokens for internal tools like `gpkg` (Fixes 401 Airlock errors). |

**The Identity Split (ADC) Command:**
```bash
gcloud auth login admin@brianltang.altostrat.com --update-adc --no-launch-browser
```
*(Note: This overrides your personal Cloud identity so the Python code talks to Gemini as the Altostrat Admin, but doesn’t touch your LOAS identity so you can still use internal tools as `brianltang`).*

---

## 🚀 2. Local Environment Setup (Using `uv`)

This project uses **`uv`** as a high-performance replacement for `pip` and `venv`. It is written in Rust, 10x-100x faster, and handles its own Python versions.

### Installing `uv` (Bypass Skippy)
```bash
curl -LsSf -o install_uv.sh https://astral.sh/uv/install.sh
chmod +x install_uv.sh
./install_uv.sh
export PATH="$HOME/.local/bin:$PATH"
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
rm install_uv.sh
```

### Initializing the Project
1. Clone the repository and navigate into the folder.
2. Create the `.env` file based on your project configuration:
```env
GOOGLE_CLOUD_PROJECT_ID="blt-test-project-1"
GOOGLE_CLOUD_LOCATION="us-central1"
GOOGLE_GENAI_USE_VERTEXAI="true"
```
3. Initialize and install dependencies (Auto-Syncs `pyproject.toml`):
```bash
uv init
uv add fastapi uvicorn pydantic python-dotenv google-genai google-adk
```

### Running the Application
Because `uv` is a single binary, you don't need to manually activate virtual environments:
```bash
uv run python main.py
```

---

## 🔐 3. Security & IAM Context

### BeyondCorp mTLS Override
In the Python code, you will see this line:
```python
os.environ["GOOGLE_API_USE_CLIENT_CERTIFICATE"] = "false"
```
**Why?** When the `google-genai` library tries to talk to Vertex AI from a Cloudtop, it detects the corporate network and tries to upgrade the connection to mTLS. However, because client-side SSL certs are often restricted, the system crashes. Setting this to `false` forces the library to act like a normal laptop and use standard TLS.

### IAM Setup
Ensure your Altostrat identity has the **Service Usage Consumer** role to consume quota/billing using ADC:
```bash
gcloud projects add-iam-policy-binding blt-test-project-1 \
  --member="user:admin@brianltang.altostrat.com" \
  --role="roles/serviceusage.serviceUsageConsumer"
```

---

## 🧠 4. ADK Architecture Learnings

This project leverages the Google Agent Development Kit (ADK) using the following core concepts:

| Concept | Description |
| :--- | :--- |
| **Pydantic** | Handles data validation without messy `if` statements and forces Gemini to return structured JSON via `output_schema`. |
| **Session Service** | Stores event history. We use `InMemorySessionService` for demos, but `VertexAiSessionService` is for production. |
| **Runner** | The manager between the API and the Agent. Fetches history from the Session Service and hands it to Gemini. |
| **Tools** | Functions (like `check_robot_sensors`) provided to the agent, forcing it to fetch real-time data before reasoning. |

---

## 🐙 5. Git & GitHub Enterprise Setup

To push this code to the Cloud GTM GitHub, ensure your Cloudtop is configured correctly.

### 1. Basic Git Hygiene
```bash
git config --global user.email "brianltang@google.com"
git config --global user.name "Brian Tang"
git config --global init.defaultBranch main
git config --global protocol.sso.allow always
git config --global pull.rebase true
```

### 2. GitHub CLI (OAuth Setup)
Instead of manual SSH keys, use the `gh` CLI for secure SAML SSO provisioning:
```bash
sudo apt update && sudo apt install gh
gh auth login --hostname github.com -p https -w
```
*(Follow the interactive prompts to authorize via browser).*

### 3. Pushing the Repo
Ensure your `.gitignore` includes `.env`, `.venv`, and `__pycache__`, then:
```bash
git init
git branch -M main
git add .
git commit -m "Initial commit: ADK Safety Agent"
git remote add origin https://github.com/cloud-gtm/YOUR_REPO_NAME.git
git push -u origin main
```

---

## 🤖 6. AI Coding Assistants (Internal Rules)
According to internal security guidelines (`go/using-genai-internally`), third-party AI tools (Copilot, ChatGPT, Claude) are strictly forbidden on corporate equipment.

*   **Use Jetski**: The AI-native fork of VS Code for internal developers.
*   **Gemini Code Assist**: Install the extension in VS Code and log in with your `@google.com` account. Go to the Cloud Console -> Vertex AI -> Agent Platform and **Enable APIs** to activate your internal VIP access.
