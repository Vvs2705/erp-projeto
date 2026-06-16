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

# --- SUPABASE RESOURCES ---
# Initial declaration for a Supabase Project
resource "supabase_project" "db_project" {
  organization_id   = var.supabase_organization_id
  name              = "${var.project_name}-database-${var.environment}"
  database_password = "ReplaceWithAStrongSecurePasswordOrVariable123!"
  region            = "us-east-1"
}

# --- VERCEL RESOURCES ---
# Initial declaration for the Frontend Project on Vercel
resource "vercel_project" "frontend_project" {
  name      = "${var.project_name}-frontend-${var.environment}"
  framework = "nextjs"
  git_repository = {
    type = "github"
    repo = "viniciussouza/${var.project_name}"
  }
}

# Example deployment environment variables on Vercel
resource "vercel_project_environment_variable" "backend_url" {
  project_id = vercel_project.frontend_project.id
  key        = "NEXT_PUBLIC_API_URL"
  value      = "https://${var.project_name}-backend.fly.dev"
  target     = ["production", "preview"]
}

# --- FLY.IO RESOURCES ---
# Initial declaration for Backend App on Fly.io
resource "fly_app" "backend_app" {
  name = "${var.project_name}-backend-${var.environment}"
  org  = "personal"
}
