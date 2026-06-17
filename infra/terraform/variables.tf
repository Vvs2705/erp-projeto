variable "vercel_api_token" {
  type        = string
  description = "Token da API Vercel"
  sensitive   = true
}

variable "vercel_team_id" {
  type        = string
  description = "Team ID do Vercel (opcional)"
  default     = ""
}

variable "supabase_access_token" {
  type        = string
  description = "Token de acesso pessoal do Supabase"
  sensitive   = true
}

variable "supabase_organization_id" {
  type        = string
  description = "ID da organização no Supabase"
}

variable "supabase_db_password" {
  type        = string
  description = "Senha do banco de dados Supabase (mínimo 16 chars)"
  sensitive   = true
}

variable "fly_api_token" {
  type        = string
  description = "Token da API Fly.io"
  sensitive   = true
}

variable "fly_org" {
  type        = string
  description = "Slug da organização no Fly.io"
  default     = "personal"
}

variable "github_repo" {
  type        = string
  description = "Repositório GitHub no formato owner/repo"
  default     = "Vvs2705/erp-projeto"
}

variable "project_name" {
  type        = string
  description = "Prefixo usado em todos os recursos"
  default     = "erp-v"
}

variable "environment" {
  type        = string
  description = "Ambiente alvo: development | staging | production"
  default     = "production"

  validation {
    condition     = contains(["development", "staging", "production"], var.environment)
    error_message = "environment deve ser development, staging ou production."
  }
}
