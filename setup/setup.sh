#!/usr/bin/env bash
# Sets up Application Default Credentials (ADC) against a Google Cloud
# project, either an existing one or a freshly created one.
set -euo pipefail

require() {
	if ! command -v "$1" >/dev/null 2>&1; then
		echo "Missing dependency: $1" >&2
		echo "$2" >&2
		exit 1
	fi
}

install_gum() {
	if command -v brew >/dev/null 2>&1; then
		brew install gum
	elif command -v apt-get >/dev/null 2>&1; then
		sudo mkdir -p /etc/apt/keyrings
		curl -fsSL https://repo.charm.sh/apt/gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/charm.gpg
		echo "deb [signed-by=/etc/apt/keyrings/charm.gpg] https://repo.charm.sh/apt/ * *" |
			sudo tee /etc/apt/sources.list.d/charm.list >/dev/null
		sudo apt-get update
		sudo apt-get install -y gum
	elif command -v dnf >/dev/null 2>&1 || command -v yum >/dev/null 2>&1; then
		printf '[charm]\nname=Charm\nbaseurl=https://repo.charm.sh/yum/\nenabled=1\ngpgcheck=1\ngpgkey=https://repo.charm.sh/yum/gpg.key\n' |
			sudo tee /etc/yum.repos.d/charm.repo >/dev/null
		if command -v dnf >/dev/null 2>&1; then
			sudo dnf install -y gum
		else
			sudo yum install -y gum
		fi
	elif command -v pacman >/dev/null 2>&1; then
		sudo pacman -Sy --noconfirm gum
	elif command -v apk >/dev/null 2>&1; then
		echo 'https://repo.charm.sh/apk/' | sudo tee -a /etc/apk/repositories >/dev/null
		sudo curl -fsSL https://repo.charm.sh/apk/charm.rsa.pub -o /etc/apk/keys/charm.rsa.pub
		sudo apk update
		sudo apk add gum
	elif command -v go >/dev/null 2>&1; then
		go install github.com/charmbracelet/gum@latest
		export PATH="$PATH:$(go env GOPATH)/bin"
	else
		return 1
	fi
}

ensure_gum() {
	command -v gum >/dev/null 2>&1 && return 0

	echo "gum (https://github.com/charmbracelet/gum) is required for this script's UI and isn't installed."
	read -r -p "Install it now? [Y/n] " REPLY
	if [[ "$REPLY" =~ ^[Nn] ]]; then
		echo "Install it yourself from https://github.com/charmbracelet/gum#installation and re-run." >&2
		exit 1
	fi

	if ! install_gum || ! command -v gum >/dev/null 2>&1; then
		echo "Automatic install failed. Install it yourself from https://github.com/charmbracelet/gum#installation and re-run." >&2
		exit 1
	fi
}

ensure_gum
require gcloud "Install it from https://cloud.google.com/sdk/docs/install"

gum style --border normal --margin "1 0" --padding "0 1" --border-foreground 212 \
	"Google Cloud ADC setup"

if ! gcloud auth list --format="value(account)" 2>/dev/null | grep -q .; then
	gum confirm "No gcloud user account found. Log in now?" && gcloud auth login
fi

create_project() {
	while true; do
		PROJECT_ID=$(gum input --header "New project ID (lowercase letters, digits, hyphens; 6-30 chars)" \
			--placeholder "my-app-dev")
		[[ -n "$PROJECT_ID" ]] || { echo "Project ID is required."; continue; }
		if [[ ! "$PROJECT_ID" =~ ^[a-z][a-z0-9-]{5,29}$ ]]; then
			gum style --foreground 196 "Invalid project ID format, try again."
			continue
		fi
		break
	done

	PROJECT_NAME=$(gum input --header "Display name" --value "$PROJECT_ID")

	gum spin --title "Creating project $PROJECT_ID..." -- \
		gcloud projects create "$PROJECT_ID" --name="$PROJECT_NAME"

	if gum confirm "Link a billing account? (required for the Vertex AI API used by Gemini embeddings)"; then
		mapfile -t BILLING_ACCOUNTS < <(gcloud billing accounts list \
			--filter="open=true" --format="value(name,displayName)" | sed 's/\t/  —  /')
		if [[ ${#BILLING_ACCOUNTS[@]} -eq 0 ]]; then
			gum style --foreground 196 "No open billing accounts found; skipping."
		else
			CHOICE=$(printf '%s\n' "${BILLING_ACCOUNTS[@]}" | gum choose --header "Billing account")
			BILLING_ID=${CHOICE%%  —  *}
			gum spin --title "Linking billing account..." -- \
				gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ID"
		fi
	else
		gum style --foreground 214 "Skipping billing — Vertex AI calls (including Gemini embeddings) will fail until a billing account is linked."
	fi
}

CREATE_NEW="+ Create a new project"

MODE=$(gum choose --header "Use an existing project or create a new one?" \
	"Use an existing project" "Create a new project")

if [[ "$MODE" == "Create a new project" ]]; then
	create_project
else
	gum style --faint "Fetching your projects..."
	mapfile -t PROJECTS < <(gcloud projects list --format="value(projectId,name)" | sed 's/\t/  —  /')

	CHOICE=$(printf '%s\n' "$CREATE_NEW" "${PROJECTS[@]}" | gum filter --header "Select a project (or create a new one)")

	if [[ "$CHOICE" == "$CREATE_NEW" ]]; then
		create_project
	else
		PROJECT_ID=${CHOICE%%  —  *}
	fi
fi

gum spin --title "Setting active project to $PROJECT_ID..." -- \
	gcloud config set project "$PROJECT_ID"

gum spin --title "Enabling Vertex AI API (required for Gemini embeddings)..." -- \
	gcloud services enable aiplatform.googleapis.com --project="$PROJECT_ID"

gum style --margin "1 0" "Opening browser to authorize Application Default Credentials..."
gcloud auth application-default login

gum spin --title "Setting ADC quota project..." -- \
	gcloud auth application-default set-quota-project "$PROJECT_ID"

if gum confirm "Enable any other APIs on $PROJECT_ID?"; then
	APIS=$(gum input --header "Comma-separated API service names (e.g. storage.googleapis.com)" \
		--placeholder "storage.googleapis.com")
	if [[ -n "$APIS" ]]; then
		IFS=',' read -ra API_LIST <<<"$APIS"
		for api in "${API_LIST[@]}"; do
			api=$(echo "$api" | xargs)
			[[ -n "$api" ]] || continue
			gum spin --title "Enabling $api..." -- gcloud services enable "$api" --project="$PROJECT_ID"
		done
	fi
fi

ADC_PATH="${CLOUDSDK_CONFIG:-$HOME/.config/gcloud}/application_default_credentials.json"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
ENV_EXAMPLE="$REPO_ROOT/.env.example"

if [[ ! -f "$ENV_FILE" ]]; then
	if [[ -f "$ENV_EXAMPLE" ]]; then
		cp "$ENV_EXAMPLE" "$ENV_FILE"
	else
		touch "$ENV_FILE"
	fi
fi

set_env_var() {
	local key=$1 value=$2
	if grep -q "^${key}=" "$ENV_FILE"; then
		sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
	else
		printf '%s=%s\n' "$key" "$value" >>"$ENV_FILE"
	fi
}

if [[ -s "$ENV_FILE" ]] && ! grep -qE '^(GOOGLE_CLOUD_PROJECT|GOOGLE_GENAI_USE_VERTEXAI)=' "$ENV_FILE"; then
	printf '\n# Google Cloud\n' >>"$ENV_FILE"
fi
set_env_var "GOOGLE_CLOUD_PROJECT" "$PROJECT_ID"
set_env_var "GOOGLE_GENAI_USE_VERTEXAI" "true"

gum style --border normal --margin "1 0" --padding "0 1" --border-foreground 46 \
	"Done." \
	"Project:    $PROJECT_ID" \
	"ADC file:   $ADC_PATH" \
	"Vertex AI:  enabled (Gemini embeddings ready)" \
	"" \
	"Wrote GOOGLE_CLOUD_PROJECT and GOOGLE_GENAI_USE_VERTEXAI to $ENV_FILE"
