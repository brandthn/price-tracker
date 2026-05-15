output "service_accounts" {
  description = "Map of role => google_service_account resource (email, name, member)."
  value = {
    for role_key, sa in google_service_account.this : role_key => {
      email      = sa.email
      account_id = sa.account_id
      member     = "serviceAccount:${sa.email}"
      name       = sa.name
    }
  }
}

output "emails" {
  description = "Map of role => SA email (convenience accessor)."
  value       = { for role_key, sa in google_service_account.this : role_key => sa.email }
}
