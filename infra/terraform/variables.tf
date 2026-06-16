variable "vercel_api_token" {
  type        = string
  description = "Vercel API Token used for authentication"
  sensitive   = true
}

variable "vercel_team_id" {
  type        = string
  description = "Optional Vercel Team ID to scope operations"
  default     = ""
}

variable "supabase_access_token" {
  type        = string
  description = "Supabase personal access token"
  sensitive   = true
}

variable "supabase_organization_id" {
  type        = string
  description = "Supabase Organization ID"
}

variable "fly_api_token" {
  type        = string
  description = "Fly.io API token"
  sensitive   = true
}

variable "project_name" {
  type        = string
  description = "Name of the project used as a prefix for resources"
  default     = "erp-v"
}

variable "environment" {
  type        = string
  description = "Target deployment environment (e.g., development, production)"
  default     = "production"
}
