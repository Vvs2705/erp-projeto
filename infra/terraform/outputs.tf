output "supabase_project_ref" {
  description = "Ref do projeto Supabase (usada em connection strings)"
  value       = supabase_project.db.id
  sensitive   = true
}

output "fly_backend_hostname" {
  description = "Hostname público do backend no Fly.io"
  value       = "${fly_app.backend.name}.fly.dev"
}

output "vercel_frontend_url" {
  description = "URL de produção do frontend no Vercel"
  value       = "https://${vercel_project.frontend.name}.vercel.app"
}
