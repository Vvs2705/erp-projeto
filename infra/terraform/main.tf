terraform {
  required_version = ">= 1.5.0"

  required_providers {
    vercel = {
      source  = "vercel/vercel"
      version = "~> 1.0"
    }
    supabase = {
      source  = "supabase/supabase"
      version = "~> 0.1"
    }
    fly = {
      source  = "fly-apps/fly"
      version = "~> 0.1"
    }
  }

  # Mover para backend remoto (S3/GCS) ao atingir staging/prod.
  backend "local" {
    path = "terraform.tfstate"
  }
}

provider "vercel" {
  api_token = var.vercel_api_token
  team      = var.vercel_team_id != "" ? var.vercel_team_id : null
}

provider "supabase" {
  access_token = var.supabase_access_token
}

provider "fly" {
  use_token = true
}

# ── SUPABASE (banco) ──────────────────────────────────────────────────────────
# Região: sa-east-1 → São Paulo; dados nunca saem do Brasil (LGPD).
resource "supabase_project" "db" {
  organization_id   = var.supabase_organization_id
  name              = "${var.project_name}-db-${var.environment}"
  database_password = var.supabase_db_password
  region            = "sa-east-1"
}

# ── FLY.IO (backend) ─────────────────────────────────────────────────────────
resource "fly_app" "backend" {
  name = "${var.project_name}-api-${var.environment}"
  org  = var.fly_org
}

# ── VERCEL (frontend) ────────────────────────────────────────────────────────
resource "vercel_project" "frontend" {
  name      = "${var.project_name}-web-${var.environment}"
  framework = "vite"
  git_repository = {
    type = "github"
    repo = var.github_repo
  }
}

resource "vercel_project_environment_variable" "api_url" {
  project_id = vercel_project.frontend.id
  key        = "VITE_API_URL"
  value      = "https://${fly_app.backend.name}.fly.dev"
  target     = ["production", "preview"]
}

# ── UPSTASH REDIS (cache / rate-limit / locks) ────────────────────────────────
# Upstash não tem provider Terraform oficial maduro; criamos via data source
# ou output de referência para configuração manual na primeira execução.
# Substitua por um resource real quando o provider upstash/upstash estiver
# disponível e estável.
output "upstash_setup_note" {
  value = "Crie um banco Redis Upstash na região sa-east-1 manualmente e injete REDIS_URL via secrets do Fly.io: fly secrets set REDIS_URL=rediss://..."
}
