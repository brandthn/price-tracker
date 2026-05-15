output "secrets" {
  description = "Map of secret_id => { id, name, secret_id }."
  value = {
    for k, s in google_secret_manager_secret.this : k => {
      id        = s.id
      name      = s.name
      secret_id = s.secret_id
    }
  }
}

output "secret_ids" {
  description = "Map of secret_id => fully qualified secret resource ID."
  value       = { for k, s in google_secret_manager_secret.this : k => s.id }
}
